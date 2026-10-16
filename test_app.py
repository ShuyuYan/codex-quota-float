# SPDX-License-Identifier: GPL-3.0-only
"""Offline display, settings, and exit behavior; no account requests."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtCore, QtWidgets
import app


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_countdown_boundaries_and_expired_or_missing_values(self):
        now = 1_000_000
        cases = [(None, "--:--"), (float("nan"), "--:--"),
                 (now - 1, "0:00"), (now, "0:00"), (now + 1, "0:01"),
                 (now + 60, "0:01"), (now + 61, "0:02"),
                 (now + 3599, "1:00"), (now + 3601, "1:01"),
                 (now + 12420, "3:27")]
        for reset, expected in cases:
            with self.subTest(reset=reset):
                self.assertEqual(app.reset_countdown(reset, now), expected)
        self.assertEqual(app.reset_countdown(now + 12420, now + 60), "3:26")

    def test_color_thresholds(self):
        for value, expected in [(None, "#98a2ad"), (19.9, "#e05a55"),
                                (20, "#c28a22"), (50, "#c28a22"), (50.1, "#248566")]:
            self.assertEqual(app.color_for(value).name(), expected)

    def test_demo_countdown_tick_never_starts_an_account_request(self):
        with mock.patch.object(app.QuotaWorker, "start") as start:
            window = app.QuotaFloat(demo=True)
            self.assertEqual(window.clock_timer.interval(), 60_000)
            window.clock_timer.timeout.emit()
            window.refresh()
            start.assert_not_called()
            window.close()
            self.assertFalse(window.clock_timer.isActive())

    def test_first_success_log_has_no_real_quota_data(self):
        window = app.QuotaFloat(demo=True)
        snapshot = {"fetched_at": 1000, "five_hour": {"remaining": 57.25, "resets_at": 1730947200},
                    "weekly": {"remaining": 30, "resets_at": None}}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            window.accept_snapshot(snapshot)
        self.assertNotIn("57.25", output.getvalue())
        self.assertNotIn("1730947200", output.getvalue())
        window.close()

    def test_legacy_position_is_saved_to_xdg_not_the_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            legacy = source / "settings.json"
            original = '{"x":12,"y":15,"dark":true}'
            legacy.write_text(original)
            settings = root / "config/codex-quota-float/settings.json"
            with mock.patch.object(app, "ROOT", source), mock.patch.object(app, "settings_path", return_value=settings):
                window = app.QuotaFloat(demo=True)
                self.assertTrue(window.dark)
                window.demo = False
                window.save_position()
                self.assertEqual(json.loads(settings.read_text())["dark"], True)
                self.assertEqual(legacy.read_text(), original)
                self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
                window.close()

    def test_invalid_settings_object_does_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefs = Path(temporary) / "settings.json"
            prefs.write_text("[]")
            with mock.patch.object(app, "settings_path", return_value=prefs):
                window = app.QuotaFloat(demo=True)
                window.close()


if __name__ == "__main__":
    unittest.main()
