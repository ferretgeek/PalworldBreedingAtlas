from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import update_game_data


class OptionalElementTests(unittest.TestCase):
    def test_unversioned_element_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pal_elements.json").write_text(
                '{"SheepBall":["Normal"]}', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                update_game_data.DataUpdateError, "无版本标记"
            ):
                update_game_data.load_optional_elements(root, {"SheepBall"})

    def test_bundled_element_snapshot_covers_current_pals(self) -> None:
        source = update_game_data.DEFAULT_ELEMENT_SOURCE
        payload = __import__("json").loads(source.read_text(encoding="utf-8"))
        expected = set(payload["pals"])
        elements, provenance = update_game_data.load_optional_elements(None, expected)
        self.assertEqual(expected, set(elements))
        self.assertEqual("pinned-build-snapshot", provenance["status"])


class AtomicWriteManyTests(unittest.TestCase):
    def test_commit_failure_rolls_back_previous_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            first.write_bytes(b"old-first")
            second.write_bytes(b"old-second")
            real_replace = os.replace

            def replace_with_second_failure(source, target) -> None:
                source_path = Path(source)
                target_path = Path(target)
                if target_path == second and source_path.suffix == ".tmp":
                    raise OSError("simulated second-file failure")
                real_replace(source, target)

            with mock.patch.object(
                update_game_data.os,
                "replace",
                side_effect=replace_with_second_failure,
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    update_game_data.atomic_write_many(
                        {first: b"new-first", second: b"new-second"}
                    )

            self.assertEqual(b"old-first", first.read_bytes())
            self.assertEqual(b"old-second", second.read_bytes())
            self.assertFalse(list(root.glob(".*.tmp")))
            self.assertFalse(list(root.glob(".*.bak")))


if __name__ == "__main__":
    unittest.main()
