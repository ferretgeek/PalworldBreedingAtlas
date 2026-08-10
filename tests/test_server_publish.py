from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pal_breed_helper import server_publish


class ServerPublishTests(unittest.TestCase):
    def test_publish_builds_once_and_skips_unchanged_save(self) -> None:
        analyzed = {
            "source": "测试服务器",
            "savePath": "private",
            "globalStoragePath": None,
            "globalStorageStatus": "missing",
            "globalStorageError": "",
            "ownedKeys": ["1", "2"],
            "owned": [{"key": "1", "count": 2}, {"key": "2", "count": 1}],
            "crossWorldGeneKeys": [],
            "crossWorldGenes": [],
            "excluded": [],
            "unknownData": [],
            "crossWorldGeneExcluded": [],
            "crossWorldGeneUnknownData": [],
            "skipped": [],
            "rawCounts": {"ownedWorld": 3, "crossWorldGenes": 0},
            "dataInfo": {},
        }
        captured_meta = {}

        def fake_write_json(result, path):
            self.assertEqual("Level.sav", result["savePath"])
            Path(path).write_text("{}", encoding="utf-8")
            return str(path)

        def fake_build(_keys, path, _cancel=None, **kwargs):
            captured_meta.update(kwargs["save_meta"])
            Path(path).write_text("<!doctype html>", encoding="utf-8")
            return str(path)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "Level.sav"
            save.write_bytes(b"stable-save")
            output = root / "public"
            with (
                mock.patch.object(
                    server_publish.save_parser, "analyze_save", return_value=analyzed
                ) as analyze,
                mock.patch.object(
                    server_publish.save_parser,
                    "write_json",
                    side_effect=fake_write_json,
                ),
                mock.patch.object(
                    server_publish.save_parser,
                    "build_injected_html",
                    side_effect=fake_build,
                ),
            ):
                first = server_publish.publish_latest(save, output, log=lambda _: None)
                second = server_publish.publish_latest(save, output, log=lambda _: None)

            self.assertTrue(first["changed"])
            self.assertTrue(first["fresh"])
            self.assertEqual(2, first["speciesCount"])
            self.assertEqual(3, first["palCount"])
            self.assertFalse(second["changed"])
            self.assertTrue(second["fresh"])
            self.assertEqual(1, analyze.call_count)
            self.assertEqual("server", captured_meta["deployment"])
            self.assertEqual(first["publishedSignature"], captured_meta["signature"])
            persisted = json.loads(
                (output / server_publish.STATUS_FILE_NAME).read_text(encoding="utf-8")
            )
            self.assertFalse(persisted["busy"])
            self.assertEqual(first["publishedSignature"], persisted["publishedSignature"])

    def test_failed_refresh_keeps_previous_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "Level.sav"
            save.write_bytes(b"new-save")
            output = root / "public"
            output.mkdir()
            previous = {
                "schema": server_publish.STATUS_SCHEMA,
                "publishedSignature": "old-signature",
                "analyzedAt": "2026-07-20T00:00:00+00:00",
            }
            (output / server_publish.STATUS_FILE_NAME).write_text(
                json.dumps(previous), encoding="utf-8"
            )
            with mock.patch.object(
                server_publish.save_parser,
                "analyze_save",
                side_effect=RuntimeError("解析失败"),
            ):
                with self.assertRaisesRegex(RuntimeError, "解析失败"):
                    server_publish.publish_latest(save, output, log=lambda _: None)
            persisted = json.loads(
                (output / server_publish.STATUS_FILE_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual("old-signature", persisted["publishedSignature"])
            self.assertFalse(persisted["busy"])
            self.assertFalse(persisted["fresh"])
            self.assertNotIn("解析失败", persisted["lastError"])
            self.assertIn("详细原因仅保留", persisted["lastError"])

    def test_failed_refresh_does_not_persist_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "Level.sav"
            save.write_bytes(b"new-save")
            output = root / "public"
            with mock.patch.object(
                server_publish.save_parser,
                "analyze_save",
                side_effect=RuntimeError(f"cannot parse {save}"),
            ):
                with self.assertRaises(RuntimeError):
                    server_publish.publish_latest(save, output, log=lambda _: None)
            persisted = (output / server_publish.STATUS_FILE_NAME).read_text(encoding="utf-8")
            self.assertNotIn(str(root), persisted)


if __name__ == "__main__":
    unittest.main()
