from __future__ import annotations

import json
import os
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from pal_breed_helper import save_parser, updater


class DataTests(unittest.TestCase):
    def test_current_data_counts(self) -> None:
        data = save_parser.breeding_data()
        self.assertEqual(287, len(data["pals"]))
        self.assertEqual(287, len(save_parser.internal_to_english()))
        self.assertEqual("1.0.0", data["meta"]["gameVersion"])

    def test_all_pal_images_exist(self) -> None:
        data = save_parser.breeding_data()
        paldeck_text = (
            save_parser.asset_dir() / "data" / "paldeck.js"
        ).read_text(encoding="utf-8")
        marker = "window.PALDECK = "
        paldeck, _ = json.JSONDecoder().raw_decode(
            paldeck_text[paldeck_text.index(marker) + len(marker) :]
        )
        self.assertEqual(set(data["pals"]), set(paldeck))
        for item in paldeck.values():
            if item.get("img"):
                self.assertTrue((save_parser.asset_dir() / item["img"]).is_file())

    def test_search_alias_bundle_covers_all_pals_case(self) -> None:
        data = save_parser.breeding_data()
        aliases_text = (
            save_parser.asset_dir() / "data" / "search-aliases.js"
        ).read_text(encoding="utf-8")
        prefix = "window.PAL_ALIASES = "
        self.assertTrue(aliases_text.startswith(prefix))
        aliases = json.loads(aliases_text[len(prefix) :].rstrip(";\r\n"))
        self.assertEqual(set(data["pals"]), set(aliases))
        self.assertTrue(all(rows and rows[0] for rows in aliases.values()))


class ParserTests(unittest.TestCase):
    @staticmethod
    def _fstring(value: str) -> bytes:
        payload = value.encode("utf-8") + b"\x00"
        return len(payload).to_bytes(4, "little", signed=True) + payload

    @classmethod
    def _name_property(cls, key: str, value: str) -> bytes:
        payload = cls._fstring(value)
        return cls._fstring(key) + cls._fstring("NameProperty") + len(payload).to_bytes(8, "little") + b"\x00" + payload

    @classmethod
    def _enum_property(cls, key: str, value: str) -> bytes:
        payload = cls._fstring(value)
        return cls._fstring(key) + cls._fstring("EnumProperty") + len(payload).to_bytes(8, "little") + cls._fstring("EPalGenderType") + b"\x00" + payload

    @classmethod
    def _byte_property(cls, key: str, value: int) -> bytes:
        return cls._fstring(key) + cls._fstring("ByteProperty") + (1).to_bytes(8, "little") + cls._fstring("None") + b"\x00" + bytes([value])

    @classmethod
    def _name_array(cls, key: str, values: list[str]) -> bytes:
        payload = len(values).to_bytes(4, "little", signed=True) + b"".join(cls._fstring(value) for value in values)
        return cls._fstring(key) + cls._fstring("ArrayProperty") + len(payload).to_bytes(8, "little") + cls._fstring("NameProperty") + b"\x00" + payload

    def test_decompress_legacy_zlib_save(self) -> None:
        raw = b"legacy-palworld-save"
        payload = zlib.compress(raw)
        header = len(raw).to_bytes(4, "little") + (b"\x00" * 4) + b"PlZ" + b"\x00"
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "Level.sav"
            save.write_bytes(header + payload)
            self.assertEqual(raw, save_parser.decompress_sav(save, None))

    def test_decompress_double_zlib_save_uses_intermediate_size(self) -> None:
        raw = (b"double-zlib-palworld-save" * 64) + b"!"
        intermediate = zlib.compress(raw)
        payload = zlib.compress(intermediate)
        header = (
            len(raw).to_bytes(4, "little")
            + len(intermediate).to_bytes(4, "little")
            + b"PlZ"
            + b"\x32"
        )
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "Level.sav"
            save.write_bytes(header + payload)
            self.assertNotEqual(len(intermediate), len(payload))
            self.assertEqual(raw, save_parser.decompress_sav(save, None))

    def test_zlib_output_is_bounded_by_declared_size(self) -> None:
        payload = zlib.compress(b"A" * (1024 * 1024))
        header = (32).to_bytes(4, "little") + len(payload).to_bytes(4, "little") + b"PlZ\x00"
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "Level.sav"
            save.write_bytes(header + payload)
            with self.assertRaisesRegex(RuntimeError, "超过"):
                save_parser.decompress_sav(save, None)

    def test_save_input_size_is_checked_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "Level.sav"
            save.write_bytes(b"x" * 65)
            with mock.patch.object(save_parser, "MAX_SAVE_INPUT_BYTES", 64):
                with self.assertRaisesRegex(RuntimeError, "安全上限"):
                    save_parser.decompress_sav(save, None)

    def test_extract_species_ascii(self) -> None:
        needle = b"CharacterID\x00\r\x00\x00\x00NameProperty\x00"
        value = b"SheepBall\x00"
        raw = needle + (b"\x00" * 9) + len(value).to_bytes(4, "little", signed=True) + value
        self.assertEqual(1, save_parser.extract_species(raw)["SheepBall"])

    def test_extract_individual_fields(self) -> None:
        raw = b"".join(
            (
                self._name_property("CharacterID", "SheepBall"),
                self._enum_property("Gender", "EPalGenderType::Female"),
                self._byte_property("Level", 42),
                self._byte_property("Talent_HP", 81),
                self._byte_property("Talent_Shot", 72),
                self._byte_property("Talent_Defense", 63),
                self._name_array("PassiveSkillList", ["Legend", "CraftSpeed_up1"]),
                self._name_property("CharacterID", "PinkCat"),
                self._enum_property("Gender", "EPalGenderType::Male"),
                self._byte_property("Level", 12),
                self._name_array("PassiveSkillList", []),
            )
        )
        records = save_parser.extract_individuals(raw)
        self.assertEqual(2, len(records))
        self.assertEqual("SheepBall", records[0]["code"])
        self.assertEqual("female", records[0]["gender"])
        self.assertEqual(42, records[0]["level"])
        self.assertEqual(["Legend", "CraftSpeed_up1"], records[0]["passives"])
        self.assertEqual({"hp": 81, "attack": 72, "defense": 63}, records[0]["talents"])
        self.assertEqual("male", records[1]["gender"])

    def test_find_account_level_global_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_games = Path(directory) / "SaveGames"
            account = save_games / "123456"
            world = account / "WORLD_GUID"
            world.mkdir(parents=True)
            level = world / "Level.sav"
            level.touch()
            global_storage = account / "GlobalPalStorage.sav"
            global_storage.touch()
            result = save_parser.find_global_storage(level)
            self.assertIsNotNone(result)
            self.assertEqual(
                save_parser.path_key(global_storage), save_parser.path_key(result)
            )

    def test_generated_html_contains_owned_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.html"
            result = Path(
                save_parser.build_injected_html(
                    ["1", "2"],
                    target,
                    inventory=[{"key": "1", "count": 2, "male": 1, "female": 1}],
                    save_meta={"source": "测试世界</script>"},
                )
            )
            text = result.read_text(encoding="utf-8")
            self.assertIn('window.__SAVE_OWNED__=["1", "2"]', text)
            self.assertIn('window.__SAVE_INVENTORY__=[{"key": "1", "count": 2', text)
            self.assertIn(
                'window.__SAVE_META__={"source": "测试世界\\u003c/script\\u003e"}',
                text,
            )
            self.assertNotIn("测试世界</script>", text)
            self.assertTrue((result.parent / "app.js").is_file())
            self.assertTrue((result.parent / "data" / "breeding.js").is_file())

    @unittest.skipUnless(os.environ.get("PALWORLD_SAVE"), "未提供 PALWORLD_SAVE")
    def test_real_save_integration(self) -> None:
        result = save_parser.analyze_save(os.environ["PALWORLD_SAVE"], lambda _: None)
        self.assertTrue(result["ownedKeys"])
        self.assertEqual(len(result["ownedKeys"]), len(result["owned"]))


class UpdaterTests(unittest.TestCase):
    def test_updater_is_disabled(self) -> None:
        self.assertFalse(updater.is_enabled())
        self.assertIsNone(updater.check_for_update())

    def test_version_comparison(self) -> None:
        self.assertTrue(updater.is_newer("2.0.4", "2.0.3"))
        self.assertFalse(updater.is_newer("v2.0.3", "2.0.3"))


if __name__ == "__main__":
    unittest.main()
