# SPDX-License-Identifier: GPL-3.0-only
"""Offline Windows shortcut tests; every write stays in temporary directories."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import install_shortcut
import windows_shortcut as shortcut


class WindowsShortcutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="quota-windows-shortcut-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "中文 project & $env` 20%"
        self.root.mkdir()
        self.python = self.directory / "my venv" / "python.exe"
        self.python.parent.mkdir()
        self.python.touch()
        self.pythonw = self.python.with_name("pythonw.exe")
        self.pythonw.touch()
        self.configuration = self.directory / "state" / "launcher.json"
        self.programs = self.directory / "Start Menu" / "Programs"
        self.desktop = self.directory / "OneDrive 中文" / "Desktop"
        self.desktop.mkdir(parents=True)
        self.output, self.errors = io.StringIO(), io.StringIO()
        self.folder_calls = []
        for patcher in (
                mock.patch.object(shortcut, "PROJECT_ROOT", self.root),
                mock.patch.object(shortcut.sys, "executable", str(self.python)),
                mock.patch.object(shortcut.sys, "platform", "win32"),
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(shortcut, "config_path", return_value=self.configuration),
                mock.patch.object(shortcut, "known_folder", side_effect=self.folder),
                mock.patch.object(shortcut, "_shell", side_effect=self.shell),
                contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.errors)):
            patcher.__enter__()
            self.addCleanup(patcher.__exit__, None, None, None)

    def folder(self, name):
        self.folder_calls.append(name)
        return self.programs if name == "programs" else self.desktop

    @staticmethod
    def shell(operation, target, spec=None):
        if operation == "write":
            target.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        else:
            return json.loads(target.read_text(encoding="utf-8"))

    @property
    def menu(self):
        return self.programs / shortcut.LAUNCHER_NAME

    def test_import_performs_no_commands_or_writes(self):
        with mock.patch.object(shortcut.subprocess, "run") as run, \
                mock.patch.object(Path, "mkdir") as mkdir:
            importlib.reload(shortcut)
        run.assert_not_called()
        mkdir.assert_not_called()

    def test_install_entry_point_delegates_arguments_and_exit_code(self):
        with mock.patch.object(shortcut, "main", return_value=17) as main:
            self.assertEqual(install_shortcut.main(["--dry-run"]), 17)
        main.assert_called_once_with(["--dry-run"])

    def test_dry_run_writes_nothing_and_invokes_no_shell(self):
        with mock.patch.object(shortcut, "_shell") as shell, \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("write")):
            self.assertEqual(shortcut.main(["--dry-run"]), 0)
        shell.assert_not_called()
        self.assertFalse(self.configuration.exists())
        self.assertFalse(self.menu.exists())
        self.assertIn(str(self.menu), self.output.getvalue())
        self.assertIn(str(self.desktop / shortcut.LAUNCHER_NAME), self.output.getvalue())

    def test_install_in_redirected_desktop_and_menu_without_launching_app(self):
        with mock.patch.object(shortcut.subprocess, "Popen") as popen:
            self.assertEqual(shortcut.main([]), 0)
        popen.assert_not_called()
        for target in (self.menu, self.desktop / shortcut.LAUNCHER_NAME):
            self.assertTrue(target.is_file())
            spec = self.shell("read", target)
            self.assertEqual(spec["TargetPath"], str(self.pythonw))
            self.assertEqual(spec["WorkingDirectory"], str(self.root))
            self.assertIn("--launch", spec["Arguments"])
        self.assertTrue(shortcut.is_project_config(json.loads(self.configuration.read_text(encoding="utf-8"))))

    def test_menu_only_does_not_query_desktop(self):
        self.assertEqual(shortcut.main(["--menu-only"]), 0)
        self.assertEqual(self.folder_calls, ["programs"])
        self.assertFalse((self.desktop / shortcut.LAUNCHER_NAME).exists())

    def test_missing_desktop_is_not_created(self):
        self.desktop = self.directory / "missing desktop"
        self.assertEqual(shortcut.main([]), 0)
        self.assertFalse(self.desktop.exists())
        self.assertTrue(self.menu.exists())

    def test_repeat_install_is_idempotent(self):
        self.assertEqual(shortcut.main([]), 0)
        self.assertEqual(shortcut.main([]), 0)

    def test_force_updates_project_launcher_after_moving_project(self):
        self.assertEqual(shortcut.main(["--menu-only"]), 0)
        new_root = self.directory / "new root 中文"
        new_root.mkdir()
        with mock.patch.object(shortcut, "PROJECT_ROOT", new_root):
            self.assertEqual(shortcut.main(["--menu-only"]), 1)
            self.assertEqual(shortcut.main(["--menu-only", "--force"]), 0)
        self.assertEqual(self.shell("read", self.menu)["WorkingDirectory"], str(new_root))

    def test_force_preserves_unrelated_shortcut_and_preflights_all_targets(self):
        target = self.desktop / shortcut.LAUNCHER_NAME
        target.write_text('{"Description": "Other app"}', encoding="utf-8")
        self.assertEqual(shortcut.main(["--force"]), 1)
        self.assertFalse(self.configuration.exists())
        self.assertFalse(self.menu.exists())
        self.assertEqual(self.shell("read", target), {"Description": "Other app"})

    def test_force_preserves_unrelated_and_invalid_configuration(self):
        self.configuration.parent.mkdir()
        for content in ("not json", '{"identity":"other-app"}'):
            with self.subTest(content=content):
                self.configuration.write_text(content, encoding="utf-8")
                self.assertEqual(shortcut.main(["--menu-only", "--force"]), 1)
                self.assertEqual(self.configuration.read_text(encoding="utf-8"), content)
                self.assertFalse(self.menu.exists())

    def test_directory_target_is_preserved(self):
        self.menu.mkdir(parents=True)
        self.assertEqual(shortcut.main(["--menu-only", "--force"]), 1)
        self.assertTrue(self.menu.is_dir())
        self.assertFalse(self.configuration.exists())

    def test_pythonw_is_required_for_console_free_shortcuts(self):
        self.pythonw.unlink()
        self.assertEqual(shortcut.main(["--menu-only"]), 1)
        self.assertIn("pythonw.exe", self.errors.getvalue())
        self.assertFalse(self.configuration.exists())

    def test_overrides_round_trip_as_json_without_shell_expansion(self):
        value = r'C:\中文 $env:HOME `tick` & percent%\codex.cmd'
        with mock.patch.dict(os.environ, {"CODEX_BIN": value, "CODEX_CLI_PATH": "another value"}):
            self.assertEqual(shortcut.main(["--menu-only"]), 0)
        config = json.loads(self.configuration.read_text(encoding="utf-8"))
        self.assertEqual(config["overrides"], {"CODEX_BIN": value, "CODEX_CLI_PATH": "another value"})
        self.assertNotIn(value, self.shell("read", self.menu)["Arguments"])
        with mock.patch("runtime.log_path", return_value=self.directory / "app.log"), \
                mock.patch.object(shortcut.subprocess, "Popen") as popen:
            self.assertEqual(shortcut.launch(self.configuration), 0)
        arguments, keywords = popen.call_args
        self.assertEqual(arguments[0], [str(self.pythonw), str(self.root / "app.py"), "--background"])
        self.assertEqual(keywords["env"]["CODEX_BIN"], value)
        self.assertNotIn("shell", keywords)
        self.assertEqual(keywords["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_launch_rejects_unexpected_configuration_keys_and_logs_error(self):
        self.configuration.parent.mkdir()
        config = shortcut.launcher_config()
        config["overrides"]["PATH"] = "untrusted"
        self.configuration.write_text(json.dumps(config), encoding="utf-8")
        log = self.directory / "state" / "app.log"
        with mock.patch("runtime.log_path", return_value=log), \
                mock.patch.object(shortcut.subprocess, "Popen") as popen:
            self.assertEqual(shortcut.launch(self.configuration), 1)
        popen.assert_not_called()
        self.assertIn("启动器配置无效", log.read_text(encoding="utf-8"))

    def test_frozen_install_targets_real_executable_without_python_or_bundle_files(self):
        executable = self.root / "CodexQuotaFloat.exe"
        executable.touch()
        self.pythonw.unlink()
        with mock.patch.object(shortcut.sys, "frozen", True, create=True), \
                mock.patch.object(shortcut.sys, "executable", str(executable)), \
                mock.patch.object(shortcut, "PROJECT_ROOT", self.directory / "_MEI12345"):
            self.assertEqual(shortcut.main(["--menu-only"]), 0)
        spec = self.shell("read", self.menu)
        self.assertEqual(spec["TargetPath"], str(executable))
        self.assertEqual(spec["Arguments"], subprocess.list2cmdline(["--launch", str(self.configuration)]))
        self.assertEqual(spec["WorkingDirectory"], str(self.root))
        self.assertEqual(spec["IconLocation"], str(executable) + ",0")
        self.assertTrue(shortcut.is_project_shortcut(spec, self.configuration))
        config = json.loads(self.configuration.read_text(encoding="utf-8"))
        self.assertEqual(config["project_root"], str(self.root))

    def test_frozen_launch_preserves_json_overrides_and_resets_pyinstaller_environment(self):
        executable = self.root / "CodexQuotaFloat.exe"
        executable.touch()
        value = r'C:\中文 $env:HOME `tick` & percent%\codex.cmd'
        with mock.patch.object(shortcut.sys, "frozen", True, create=True), \
                mock.patch.object(shortcut.sys, "executable", str(executable)), \
                mock.patch.object(shortcut, "PROJECT_ROOT", self.directory / "_MEI12345"), \
                mock.patch.dict(os.environ, {"CODEX_BIN": value}), \
                mock.patch("runtime.log_path", return_value=self.directory / "app.log"), \
                mock.patch.object(shortcut.subprocess, "Popen") as popen:
            self.assertEqual(shortcut.main(["--menu-only"]), 0)
            self.assertEqual(shortcut.launch(self.configuration), 0)
        arguments, keywords = popen.call_args
        self.assertEqual(arguments[0], [str(executable), "--background"])
        self.assertEqual(keywords["cwd"], self.root)
        self.assertEqual(keywords["env"]["CODEX_BIN"], value)
        self.assertEqual(keywords["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertNotIn("shell", keywords)

    def test_force_can_replace_source_shortcut_with_frozen_shortcut(self):
        self.assertEqual(shortcut.main(["--menu-only"]), 0)
        executable = self.root / "CodexQuotaFloat.exe"
        executable.touch()
        with mock.patch.object(shortcut.sys, "frozen", True, create=True), \
                mock.patch.object(shortcut.sys, "executable", str(executable)):
            self.assertEqual(shortcut.main(["--menu-only", "--force"]), 0)
        self.assertEqual(self.shell("read", self.menu)["TargetPath"], str(executable))

    def test_frozen_shortcut_identity_rejects_program_outside_working_directory(self):
        spec = {"Description": shortcut.DESCRIPTION, "WorkingDirectory": str(self.root),
                "TargetPath": str(self.directory / "Other.exe"),
                "Arguments": subprocess.list2cmdline(["--launch", str(self.configuration)])}
        self.assertFalse(shortcut.is_project_shortcut(spec, self.configuration))

    def test_shell_passes_data_via_stdin_and_constant_encoded_source(self):
        # Bypass the mock COM adapter only to inspect its subprocess boundary.
        with mock.patch.object(shortcut.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, \
                mock.patch.object(shortcut.shutil, "which", return_value="powershell.exe"):
            WindowsShortcutTests.real_shell("write", self.menu, {"TargetPath": "a & $env:HOME `x`"})
        arguments, keywords = run.call_args
        self.assertIn("-EncodedCommand", arguments[0])
        self.assertNotIn("a & $env:HOME `x`", " ".join(arguments[0]))
        self.assertEqual(json.loads(keywords["input"])["spec"]["TargetPath"], "a & $env:HOME `x`")
        self.assertNotIn("shell", keywords)


# Keep the actual COM adapter available while individual unit tests mock it.
WindowsShortcutTests.real_shell = staticmethod(shortcut._shell)


@unittest.skipUnless(sys.platform == "win32", "Native Windows shortcut check")
class NativeWindowsShortcutTests(unittest.TestCase):
    def test_real_com_round_trip_with_unicode_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix="quota-native-") as temporary:
            root = Path(temporary) / "中文 project & $env` 20%"
            root.mkdir()
            config = root / "launcher config.json"
            spec = shortcut.shortcut_spec(config, root, sys.executable)
            target = root / "shortcut 中文.lnk"
            shortcut._write_shortcut(target, spec, config, False)
            actual = shortcut._shell("read", target)
            self.assertEqual(actual, spec)
            shortcut._preflight_shortcut(target, spec, config, False)
            self.assertTrue(shortcut.is_project_shortcut(actual, config))


@unittest.skipUnless(sys.platform == "win32", "Native Windows launcher check")
class NativeWindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="quota-native-launch-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "中文 project & $env` 20%"
        self.root.mkdir()
        source = Path(__file__).resolve().parent
        for name in ("run.ps1", "run.cmd"):
            (self.root / name).write_bytes((source / name).read_bytes())
        (self.root / "app.py").write_text(
            'import json, sys\nprint(json.dumps(sys.argv[1:], ensure_ascii=True))\n'
            'raise SystemExit(7 if "--status" in sys.argv else 0)\n', encoding="utf-8")
        self.environment = os.environ.copy()
        self.environment["PYTHON"] = sys.executable
        self.environment["PYTHONUTF8"] = "1"
        self.powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")

    def run_script(self, name, *arguments):
        if name.endswith(".ps1"):
            command = [self.powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(self.root / name), *arguments]
        else:
            command = [str(self.root / name), *arguments]
        return subprocess.run(command, env=self.environment, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20, check=False)

    def test_powershell_forwards_spaces_unicode_and_status_exit_code(self):
        for arguments in (("--render", str(self.root / "图片 with spaces.png")), ("--status",)):
            with self.subTest(arguments=arguments):
                result = self.run_script("run.ps1", *arguments)
                self.assertEqual(result.returncode, 7 if "--status" in arguments else 0,
                                 result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout), list(arguments))

    def test_cmd_defaults_to_background_and_forwards_arguments(self):
        result = self.run_script("run.cmd")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), ["--background"])
        result = self.run_script("run.cmd", "--status")
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), ["--status"])

    def test_powershell_falls_back_to_python_without_py_or_venv(self):
        self.environment.pop("PYTHON", None)
        self.environment["PATH"] = os.pathsep.join((str(Path(sys.executable).parent),
                                                    str(Path(os.environ["SystemRoot"]) / "System32")))
        result = self.run_script("run.ps1", "--demo")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), ["--demo"])

    def test_powershell_missing_override_reports_actionable_error(self):
        self.environment["PYTHON"] = str(self.root / "missing python.exe")
        result = self.run_script("run.ps1", "--status")
        self.assertEqual(result.returncode, 1)
        self.assertIn("PYTHON", result.stderr)


if __name__ == "__main__":
    unittest.main()
