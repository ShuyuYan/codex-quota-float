# SPDX-License-Identifier: GPL-3.0-only
"""Offline display, settings, and exit behavior; no account requests."""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
import uuid
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
                if os.name != "nt":
                    self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
                window.close()

    def test_invalid_settings_object_does_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefs = Path(temporary) / "settings.json"
            prefs.write_text("[]")
            with mock.patch.object(app, "settings_path", return_value=prefs):
                window = app.QuotaFloat(demo=True)
                window.close()

    def test_shortcut_menu_reports_installer_result_without_network(self):
        import windows_shortcut
        window = app.QuotaFloat(demo=True)
        try:
            for code, dialog in ((0, "information"), (1, "warning")):
                with self.subTest(code=code), mock.patch.object(windows_shortcut, "main", return_value=code) as installer, \
                        mock.patch.object(QtWidgets.QMessageBox, dialog) as message:
                    window.install_shortcuts()
                    installer.assert_called_once_with(["--force"])
                    message.assert_called_once()
        finally:
            window.close()


class ProcessTests(unittest.TestCase):
    def test_shortcut_arguments_dispatch_before_gui_startup(self):
        import windows_shortcut
        for command, forwarded in ((["--launch", "launcher.json"], ["--launch", "launcher.json"]),
                                   (["--install-shortcut", "--dry-run"], ["--dry-run"])):
            with self.subTest(command=command), mock.patch.object(app.sys, "argv", ["app.exe"] + command), \
                    mock.patch.object(windows_shortcut, "main", return_value=0) as shortcut_main, \
                    mock.patch.object(QtWidgets, "QApplication") as application:
                self.assertEqual(app.main(), 0)
                shortcut_main.assert_called_once_with(forwarded)
                application.assert_not_called()

    def test_simultaneous_starts_leave_one_instance_and_status_can_connect(self):
        with tempfile.TemporaryDirectory() as temporary:
            name = "quota-test-" + uuid.uuid4().hex
            stop_file = Path(temporary) / "stop"
            script = f'''
import sys
from pathlib import Path
import app
app.instance_name = lambda: {name!r}
app.log_path = lambda: Path({temporary!r}) / 'app.log'
class TestWindow(app.QuotaFloat):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.exit_timer = app.QtCore.QTimer(self)
        self.exit_timer.timeout.connect(self.maybe_close)
        self.exit_timer.start(50)
        app.QtCore.QTimer.singleShot(10000, self.close)
    def maybe_close(self):
        if Path({str(stop_file)!r}).exists():
            self.close()
app.QuotaFloat = TestWindow
sys.exit(app.main() or 0)
'''
            command = [sys.executable, "-c", script]
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            children = []
            try:
                for _ in range(3):
                    children.append(subprocess.Popen(command + ["--demo"], cwd=app.ROOT,
                                                     env=environment, stdout=subprocess.DEVNULL,
                                                     stderr=subprocess.PIPE, **options))
                deadline = time.monotonic() + 6
                running = False
                while time.monotonic() < deadline:
                    status = subprocess.run(command + ["--status"], cwd=app.ROOT, env=environment,
                                            capture_output=True, timeout=3, check=True, **options)
                    running = json.loads(status.stdout)["running"]
                    if running and sum(child.poll() is None for child in children) == 1:
                        break
                    time.sleep(0.05)
                self.assertTrue(running)
                self.assertEqual(sum(child.poll() is None for child in children), 1)
                for child in children:
                    if child.poll() is not None:
                        self.assertEqual(child.returncode, 0, child.stderr.read().decode(errors="replace"))
            finally:
                stop_file.touch()
                for child in children:
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        child.wait(timeout=3)
                    child.stderr.close()

    def test_windows_instance_name_is_stable_and_contains_no_home_path(self):
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(Path, "home", return_value=Path("C:/Users/alice")):
            first = app.instance_name()
            self.assertEqual(first, app.instance_name())
            self.assertNotIn("alice", first)
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(Path, "home", return_value=Path("C:/Users/bob")):
            self.assertNotEqual(first, app.instance_name())

    def test_background_uses_windows_windowless_python_and_redirected_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interpreter = root / "python.exe"
            windowless = root / "pythonw.exe"
            windowless.touch()
            with mock.patch.object(app.sys, "platform", "win32"), \
                    mock.patch.object(app.sys, "executable", str(interpreter)), \
                    mock.patch.object(app, "log_path", return_value=root / "state/app.log"), \
                    mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                    mock.patch.object(subprocess, "Popen") as spawn:
                self.assertEqual(app.start_background(demo=True), spawn.return_value.pid)
            arguments, options = spawn.call_args
            self.assertEqual(arguments[0], [str(windowless), str(app.ROOT / "app.py"), "--demo"])
            self.assertEqual(options["creationflags"], 0x08000000)
            self.assertNotIn("start_new_session", options)
            self.assertEqual(options["stdin"], subprocess.DEVNULL)
            self.assertIs(options["stdout"], options["stderr"])
            self.assertTrue((root / "state/app.log").is_file())

    def test_frozen_background_relaunches_exe_with_independent_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "download" / "CodexQuotaFloat.exe"
            with mock.patch.object(app.sys, "platform", "win32"), \
                    mock.patch.object(app.sys, "frozen", True, create=True), \
                    mock.patch.object(app.sys, "executable", str(executable)), \
                    mock.patch.object(app, "log_path", return_value=root / "state/app.log"), \
                    mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                    mock.patch.object(subprocess, "Popen") as spawn:
                app.start_background(demo=True)
            arguments, options = spawn.call_args
            self.assertEqual(arguments[0], [str(executable), "--demo"])
            self.assertEqual(options["cwd"], executable.parent)
            self.assertEqual(options["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_status_can_write_result_for_windowed_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "output" / "status.json"
            command = [sys.executable, str(app.ROOT / "app.py"), "--status", "--output", str(destination)]
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            completed = subprocess.run(command, cwd=app.ROOT, capture_output=True, timeout=5, **options)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            self.assertIsInstance(json.loads(destination.read_text(encoding="utf-8"))["running"], bool)
            self.assertEqual(completed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
