from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from pal_breed_helper import save_parser
from pal_breed_helper.app import App, GenerationGate


class GenerationGateTests(unittest.TestCase):
    def test_start_cancels_previous_generation(self) -> None:
        gate = GenerationGate()
        first_generation, first_cancel = gate.start()
        second_generation, second_cancel = gate.start()
        self.assertTrue(first_cancel.is_set())
        self.assertFalse(second_cancel.is_set())
        self.assertFalse(gate.is_current(first_generation))
        self.assertTrue(gate.is_current(second_generation))

    def test_cancel_invalidates_late_result(self) -> None:
        gate = GenerationGate()
        generation, cancel = gate.start()
        gate.cancel(invalidate=True)
        self.assertTrue(cancel.is_set())
        self.assertFalse(gate.is_current(generation))


class WorkerEventTests(unittest.TestCase):
    def test_scan_worker_passes_forced_deep_flag_case(self) -> None:
        app = App.__new__(App)
        app.events = queue.Queue()
        cancel = threading.Event()
        with mock.patch.object(save_parser, "list_saves", return_value=[{"path": "x"}]) as scan:
            app._scan_worker(7, cancel, True)
        self.assertTrue(scan.call_args.kwargs["deep"])
        self.assertEqual("scan_done", app.events.get_nowait()["kind"])

    def test_empty_default_scan_does_not_fall_back_to_full_disk(self) -> None:
        app = App.__new__(App)
        app.events = queue.Queue()
        cancel = threading.Event()
        with mock.patch.object(save_parser, "list_saves", return_value=[]) as scan:
            app._scan_worker(3, cancel, False)
        scan.assert_called_once()
        self.assertFalse(scan.call_args.kwargs["deep"])
        self.assertEqual("scan_done", app.events.get_nowait()["kind"])

    def test_stale_count_event_cannot_update_new_scan(self) -> None:
        app = App.__new__(App)
        app.scan_gate = GenerationGate()
        app.analysis_gate = GenerationGate()
        app._set_count = mock.Mock()
        old_generation, _ = app.scan_gate.start()
        app.scan_gate.start()
        app._handle_event(
            {
                "kind": "scan_count",
                "generation": old_generation,
                "pathKey": "old",
                "count": 99,
            }
        )
        app._set_count.assert_not_called()

    def test_stale_analysis_bundle_is_discarded_before_publish(self) -> None:
        app = App.__new__(App)
        app.scan_gate = GenerationGate()
        app.analysis_gate = GenerationGate()
        old_generation, _ = app.analysis_gate.start()
        app.analysis_gate.start()
        with mock.patch.object(save_parser, "discard_generated_bundle") as discard:
            app._handle_event(
                {
                    "kind": "analysis_ready",
                    "generation": old_generation,
                    "stagingDir": r"C:\temp\.analysis-old",
                }
            )
        discard.assert_called_once_with(r"C:\temp\.analysis-old")


class ConfigMigrationTests(unittest.TestCase):
    def test_old_forward_slash_path_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "世界" / "Level.sav"
            save.parent.mkdir()
            save.touch()
            app = App.__new__(App)
            app.config = {"last_save": str(save).replace("\\", "/")}
            app._write_config = mock.Mock()
            normalized = app._normalized_config_path("last_save")
            self.assertEqual(save_parser.normalize_path(save), normalized)
            app._write_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
