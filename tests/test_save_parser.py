from __future__ import annotations

import collections
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pal_breed_helper import save_parser


class PathTests(unittest.TestCase):
    def test_path_key_normalizes_windows_separators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "世界" / "Level.sav"
            target.parent.mkdir()
            target.touch()
            forward = str(target).replace("\\", "/")
            self.assertEqual(save_parser.path_key(target), save_parser.path_key(forward))
            self.assertEqual(
                save_parser.normalize_path(target),
                save_parser.normalize_path(forward),
            )

    def test_find_global_storage_from_world_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            account = Path(directory) / "SaveGames" / "123456"
            backup = (
                account
                / "WORLD_GUID"
                / "backup"
                / "world"
                / "2026.07.12-01.00.00"
            )
            backup.mkdir(parents=True)
            level = backup / "Level.sav"
            level.touch()
            storage = account / "GlobalPalStorage.sav"
            storage.touch()
            self.assertEqual(
                save_parser.normalize_path(storage),
                save_parser.find_global_storage(level),
            )

    def test_atomic_json_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            save_parser.atomic_write_json(target, {"old": True})
            save_parser.atomic_write_json(target, {"new": "中文"}, indent=2)
            self.assertEqual(
                {"new": "中文"}, json.loads(target.read_text(encoding="utf-8"))
            )
            self.assertFalse(list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_non_object_json_state_falls_back_to_empty_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            target.write_text("[]", encoding="utf-8")
            self.assertEqual({}, save_parser.read_json_object(target))

    def test_stable_reader_retries_when_file_changes(self) -> None:
        class ChangingFile:
            def __init__(self) -> None:
                self.stats = iter(
                    (
                        SimpleNamespace(st_size=3, st_mtime_ns=1),
                        SimpleNamespace(st_size=3, st_mtime_ns=2),
                        SimpleNamespace(st_size=3, st_mtime_ns=3),
                        SimpleNamespace(st_size=3, st_mtime_ns=4),
                    )
                )

            def stat(self):
                return next(self.stats)

            def open(self, mode):
                self.assert_binary_mode = mode
                return io.BytesIO(b"sav")

            def __str__(self) -> str:
                return "changing.sav"

        changing = ChangingFile()
        with mock.patch.object(save_parser, "resolved_path", return_value=changing):
            with self.assertRaisesRegex(RuntimeError, "正在变化"):
                save_parser._read_stable_bytes(
                    "ignored", attempts=2, retry_delay=0
                )

    def test_linux_oodle_save_uses_palooz_backend(self) -> None:
        raw = b"linux-palworld-save"
        compressed = b"oodle-payload"
        header = (
            len(raw).to_bytes(4, "little")
            + len(compressed).to_bytes(4, "little")
            + b"PlM"
            + b"\x31"
        )
        backend = SimpleNamespace(decompress=mock.Mock(return_value=raw))
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "Level.sav"
            save.write_bytes(header + compressed)
            with (
                mock.patch.object(save_parser.sys, "platform", "linux"),
                mock.patch.dict(sys.modules, {"palooz": backend}),
            ):
                self.assertEqual(raw, save_parser.decompress_sav(save, None))
                self.assertEqual("palooz", save_parser.find_oodle_dll())
        backend.decompress.assert_called_once_with(compressed, len(raw))


class ScanTests(unittest.TestCase):
    def test_cancelled_scan_stops_before_filesystem_work(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(save_parser.OperationCancelled):
            save_parser.list_saves(cancel_event=cancel)

    def test_deep_scan_runs_even_when_default_scan_found_save(self) -> None:
        default_candidate = {
            "mtime": 1.0,
            "mtimeNs": 1,
            "path": r"C:\default\Level.sav",
            "pathKey": r"c:\default\level.sav",
            "world": "default",
            "host": None,
            "day": None,
            "guid": "DEFAULT",
        }
        deep_candidate = {
            "mtime": 2.0,
            "mtimeNs": 2,
            "path": r"D:\extra\Level.sav",
            "pathKey": r"d:\extra\level.sav",
            "world": "extra",
            "host": None,
            "day": None,
            "guid": "EXTRA",
        }

        def add_default(root, dll, candidates, seen, cancel_event=None):
            del root, dll, seen, cancel_event
            candidates.append(dict(default_candidate))

        def add_deep(
            dll, candidates, seen, progress=None, cancel_event=None
        ) -> None:
            del dll, seen, progress, cancel_event
            candidates.append(dict(deep_candidate))

        with (
            mock.patch.object(save_parser, "find_oodle_dll", return_value=None),
            mock.patch.object(save_parser, "default_save_roots", return_value=[Path("C:/")]),
            mock.patch.object(save_parser, "_remembered_roots", return_value=[]),
            mock.patch.object(save_parser, "_scan_saves_in", side_effect=add_default),
            mock.patch.object(
                save_parser, "_deep_scan_saves", side_effect=add_deep
            ) as deep_scan,
        ):
            saves = save_parser.list_saves(deep=True)

        deep_scan.assert_called_once()
        self.assertEqual(["extra", "default"], [item["world"] for item in saves])

    def test_default_roots_cover_steam_libraries_and_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "Local"
            steam = Path(directory) / "SteamLibrary"
            package = local / "Packages" / "PocketpairInc.Palworld_test"
            package.mkdir(parents=True)
            with (
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=False),
                mock.patch.object(save_parser, "_steam_roots", return_value={steam}),
            ):
                roots = {save_parser.path_key(path) for path in save_parser.default_save_roots()}
            self.assertIn(
                save_parser.path_key(local / "Pal" / "Saved" / "SaveGames"), roots
            )
            self.assertIn(
                save_parser.path_key(
                    steam / "steamapps" / "common" / "PalServer" / "Pal" / "Saved" / "SaveGames"
                ),
                roots,
            )
            self.assertIn(
                save_parser.path_key(package / "LocalState" / "Pal" / "Saved" / "SaveGames"),
                roots,
            )

    def test_multiple_saves_are_sorted_newest_first(self) -> None:
        older = {
            "mtime": 1.0,
            "mtimeNs": 1,
            "path": r"C:\older\Level.sav",
            "pathKey": r"c:\older\level.sav",
            "world": "older",
            "host": None,
            "day": None,
            "guid": "OLDER",
        }
        newer = {**older, "mtime": 2.0, "mtimeNs": 2, "path": r"C:\newer\Level.sav", "pathKey": r"c:\newer\level.sav", "world": "newer", "guid": "NEWER"}

        def add_candidates(root, dll, candidates, seen, cancel_event=None):
            del root, dll, seen, cancel_event
            candidates.extend((dict(older), dict(newer)))

        with (
            mock.patch.object(save_parser, "find_oodle_dll", return_value=None),
            mock.patch.object(save_parser, "default_save_roots", return_value=[Path("C:/")]),
            mock.patch.object(save_parser, "_remembered_roots", return_value=[]),
            mock.patch.object(save_parser, "_scan_saves_in", side_effect=add_candidates),
        ):
            saves = save_parser.list_saves()
        self.assertEqual(["newer", "older"], [item["world"] for item in saves])


class WebAssetTests(unittest.TestCase):
    def test_generated_page_copies_all_top_level_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.html"
            save_parser.build_injected_html(["1"], target)
            allowed = {
                ".css",
                ".js",
                ".json",
                ".svg",
                ".ico",
                ".png",
                ".webmanifest",
            }
            expected = {
                item.name
                for item in save_parser.asset_dir().iterdir()
                if item.is_file() and item.suffix.lower() in allowed
            }
            self.assertTrue(expected)
            self.assertEqual(
                set(), {name for name in expected if not (target.parent / name).is_file()}
            )

    def test_brand_assets_and_four_theme_contract(self) -> None:
        assets = save_parser.asset_dir()
        for name in (
            "favicon.svg",
            "palicon.ico",
            "apple-touch-icon.png",
            "icon-192.png",
            "icon-512.png",
            "site.webmanifest",
        ):
            self.assertGreater((assets / name).stat().st_size, 0, name)

        html = (assets / "index.html").read_text(encoding="utf-8")
        script = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn("MAX_IMPORT_FILE_BYTES", script)
        self.assertIn("MAX_IMPORT_RECORDS", script)
        self.assertIn("file.size > MAX_IMPORT_FILE_BYTES", script)
        styles = (assets / "styles.css").read_text(encoding="utf-8")
        for theme in ("night", "light", "prism", "grove"):
            self.assertIn(f'data-theme-option="{theme}"', html)
            self.assertIn(f'"{theme}"', script)
        self.assertIn(':root[data-theme="grove"]', styles)
        self.assertIn('rel="manifest" href="site.webmanifest"', html)

        manifest = json.loads((assets / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual("./", manifest["start_url"])
        self.assertEqual(
            {"icon-192.png", "icon-512.png"},
            {item["src"] for item in manifest["icons"]},
        )

    def test_web_asset_fingerprint_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "images").mkdir()
            app = root / "app.js"
            app.write_text("one", encoding="utf-8")
            first = save_parser.web_asset_fingerprint(root)
            app.write_text("two", encoding="utf-8")
            second = save_parser.web_asset_fingerprint(root)
            self.assertNotEqual(first, second)


class GeneratedBundleTests(unittest.TestCase):
    def test_stage_publish_keeps_existing_output_isolated_and_cleans_stale_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_json = root / save_parser.OWNED_FILE_NAME
            existing_html = root / save_parser.GENERATED_HTML_NAME
            existing_json.write_text('{"previous": true}', encoding="utf-8")
            existing_html.write_text("previous page", encoding="utf-8")

            with mock.patch.dict(
                os.environ, {"PAL_BREED_HELPER_DATA_DIR": directory}, clear=False
            ):
                staged = save_parser.stage_generated_bundle(
                    {"ownedKeys": ["1"], "marker": "new-generation"}
                )
                staging_dir = Path(staged["stagingDir"])

                self.assertTrue(staging_dir.is_dir())
                self.assertTrue((staging_dir / save_parser.OWNED_FILE_NAME).is_file())
                self.assertTrue(
                    (staging_dir / save_parser.GENERATED_HTML_NAME).is_file()
                )
                self.assertEqual('{"previous": true}', existing_json.read_text("utf-8"))
                self.assertEqual("previous page", existing_html.read_text("utf-8"))

                published = save_parser.publish_generated_bundle(staging_dir)
                run_dir = Path(published["runDir"])
                self.assertFalse(staging_dir.exists())
                self.assertTrue(run_dir.is_dir())
                self.assertEqual(
                    {"ownedKeys": ["1"]},
                    json.loads(Path(published["jsonPath"]).read_text("utf-8")),
                )
                self.assertTrue(Path(published["html"]).is_file())
                self.assertTrue((run_dir / "app.js").is_file())
                self.assertTrue((run_dir / "data" / "breeding.js").is_file())

                stale = run_dir.parent / ".analysis-stale"
                stale.mkdir()
                (stale / "partial.txt").write_text("partial", encoding="utf-8")
                save_parser.cleanup_staged_bundles()
                self.assertFalse(stale.exists())
                self.assertTrue(run_dir.is_dir())


class GlobalStorageStatusTests(unittest.TestCase):
    def test_storage_read_error_is_explicit_partial_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            level = Path(directory) / "Level.sav"
            storage = Path(directory) / "GlobalPalStorage.sav"
            level.touch()
            storage.touch()
            with (
                mock.patch.object(save_parser, "find_oodle_dll", return_value="oodle"),
                mock.patch.object(
                    save_parser,
                    "decompress_sav",
                    side_effect=[b"world", RuntimeError("storage damaged")],
                ),
                mock.patch.object(
                    save_parser,
                    "extract_species",
                    return_value=collections.Counter({"SheepBall": 1}),
                ),
                mock.patch.object(
                    save_parser, "_world_character_payload", side_effect=lambda raw: raw
                ),
                mock.patch.object(
                    save_parser, "find_global_storage", return_value=str(storage)
                ),
                mock.patch.object(save_parser, "read_meta", return_value={}),
            ):
                result = save_parser.analyze_save(level, lambda _: None)

            self.assertEqual("error", result["globalStorageStatus"])
            self.assertIn("storage damaged", result["globalStorageError"])
            self.assertEqual(1, sum(item["count"] for item in result["owned"]))

    def test_missing_storage_is_not_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            level = Path(directory) / "Level.sav"
            level.touch()
            with (
                mock.patch.object(save_parser, "find_oodle_dll", return_value="oodle"),
                mock.patch.object(save_parser, "decompress_sav", return_value=b"world"),
                mock.patch.object(
                    save_parser,
                    "extract_species",
                    return_value=collections.Counter({"SheepBall": 1}),
                ),
                mock.patch.object(
                    save_parser, "_world_character_payload", side_effect=lambda raw: raw
                ),
                mock.patch.object(save_parser, "find_global_storage", return_value=None),
                mock.patch.object(save_parser, "read_meta", return_value={}),
            ):
                result = save_parser.analyze_save(level, lambda _: None)

            self.assertEqual("missing", result["globalStorageStatus"])
            self.assertEqual("", result["globalStorageError"])


class MappingTests(unittest.TestCase):
    def test_data_status_exposes_verified_release(self) -> None:
        status = save_parser.data_status()
        self.assertTrue(status["verified"])
        self.assertEqual("1.0.0", status["version"])
        self.assertEqual(287, status["palCount"])

    def test_mapping_wrapper_and_excluded_schema_case(self) -> None:
        mapping, excluded = save_parser._mapping_payload(
            {
                "schemaVersion": 1,
                "mapping": {"SheepBall": "Lamball"},
                "excluded": {
                    "YakushimaMonster001": {
                        "category": "special/terraria",
                        "reason": "联动单位",
                    }
                },
            }
        )
        self.assertEqual("Lamball", mapping["SheepBall"])
        self.assertEqual(
            "special/terraria", excluded["YakushimaMonster001"]["category"]
        )

    def test_direct_stable_key_schema_is_supported(self) -> None:
        pals = {"1": {"en": "Lamball"}}
        english = {"lamball": "1"}
        self.assertEqual(
            "1", save_parser._mapping_value_to_key("1", pals, english)
        )
        self.assertEqual(
            "1",
            save_parser._mapping_value_to_key(
                {"stableKey": "1"}, pals, english
            ),
        )

    def test_unknown_data_is_not_mixed_with_known_special_units(self) -> None:
        species = collections.Counter(
            {
                "YakushimaMonster001": 2,
                "BOSS_Male_Soldier04": 1,
                "PalDealer": 1,
                "Believer_CrossBow": 2,
                "GYM_ElecPanda_Otomo": 2,
                "BOSS_FireCult_FlameThrower": 1,
                "BOSS_KingWhale_otomo": 1,
                "DefinitelyNewPalCode": 3,
            }
        )
        _, excluded, unknown = save_parser._resolve_species(species)
        categories = {item["code"]: item["category"] for item in excluded}
        self.assertEqual("special/terraria", categories["YakushimaMonster001"])
        self.assertEqual("npc", categories["BOSS_Male_Soldier04"])
        self.assertEqual("npc", categories["PalDealer"])
        self.assertEqual("npc", categories["Believer_CrossBow"])
        self.assertEqual("npc/boss-helper", categories["GYM_ElecPanda_Otomo"])
        self.assertEqual(
            "npc/boss-helper", categories["BOSS_FireCult_FlameThrower"]
        )
        self.assertEqual("npc/boss-helper", categories["BOSS_KingWhale_otomo"])
        self.assertEqual(["DefinitelyNewPalCode"], [item["code"] for item in unknown])


class RealSaveContractTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PALWORLD_SAVE"), "未提供 PALWORLD_SAVE")
    def test_real_save_has_no_unknown_data_and_balanced_counts(self) -> None:
        result = save_parser.analyze_save(os.environ["PALWORLD_SAVE"], lambda _: None)
        self.assertEqual([], result["unknownData"])
        self.assertEqual([], result["crossWorldGeneUnknownData"])

        world_known = sum(item["count"] for item in result["owned"])
        world_excluded = sum(item["count"] for item in result["excluded"])
        self.assertEqual(
            result["rawCounts"]["world"], world_known + world_excluded
        )

        gene_known = sum(item["count"] for item in result["crossWorldGenes"])
        gene_excluded = sum(
            item["count"] for item in result["crossWorldGeneExcluded"]
        )
        self.assertEqual(result["rawCounts"]["box"], gene_known + gene_excluded)


if __name__ == "__main__":
    unittest.main()
