# SPDX-License-Identifier: GPL-3.0-only
"""Offline launcher checks: all installations use temporary HOME directories."""

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import install_shortcut as shortcut


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="quota-shortcut-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.home = self.directory / "home"
        self.desktop = self.directory / "Desktop"
        self.desktop.mkdir()
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        platform = mock.patch.object(shortcut.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)
        self.output = io.StringIO()
        self.errors = io.StringIO()
        for redirect in (contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.errors)):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    @property
    def menu(self):
        return self.home / ".local/share/applications" / shortcut.LAUNCHER_NAME

    def test_import_performs_no_installation_or_commands(self):
        with mock.patch.object(shortcut.subprocess, "run") as run, \
                mock.patch.object(Path, "mkdir") as mkdir, \
                mock.patch.object(Path, "write_text") as write:
            importlib.reload(shortcut)
            run.assert_not_called()
            mkdir.assert_not_called()
            write.assert_not_called()

    def test_exec_has_both_quoting_layers(self):
        self.assertEqual(shortcut.exec_argument('a b%"\\$`'), '"a b%%\\\\"\\\\\\\\\\\\$\\\\`"')
        self.assertEqual(shortcut.desktop_string(' path\\icon '), '\\spath\\\\icon\\s')
        self.assertEqual(shortcut.desktop_string('   '), '\\s\\s\\s')
        with self.assertRaises(shortcut.InstallError):
            shortcut.exec_argument("bad\npath")

    def test_content_uses_actual_project_and_current_python(self):
        with mock.patch.object(shortcut, "PROJECT_ROOT", self.directory / "codex-quota-float"), \
                mock.patch.object(shortcut.sys, "executable", "/tmp/my venv/bin/python"):
            content = shortcut.launcher_content()
        self.assertIn('Exec="/tmp/my venv/bin/python" "' + str(self.directory / "codex-quota-float/app.py") + '" "--background"', content)
        self.assertIn("Icon=" + str(self.directory / "codex-quota-float/quota-icon.svg"), content)
        self.assertIn("Path=" + str(self.directory / "codex-quota-float"), content)
        self.assertNotIn("run.sh", content)

    def test_absolute_xdg_data_home_only(self):
        for value in ("", "relative", "~/data"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"XDG_DATA_HOME": value}):
                self.assertEqual(shortcut.applications_directory(), self.menu.parent)
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.directory / "data")}):
            self.assertEqual(shortcut.applications_directory(), self.directory / "data/applications")

    def test_dry_run_outputs_targets_and_content_without_writes_or_gio(self):
        with mock.patch.object(shortcut, "desktop_directory", return_value=(self.desktop, None)), \
                mock.patch.object(shortcut.subprocess, "run") as run, \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected write")), \
                mock.patch.object(Path, "chmod", side_effect=AssertionError("unexpected chmod")):
            self.assertEqual(shortcut.main(["--dry-run"]), 0)
        self.assertIn(str(self.menu), self.output.getvalue())
        self.assertIn(str(self.desktop / shortcut.LAUNCHER_NAME), self.output.getvalue())
        self.assertIn("[Desktop Entry]", self.output.getvalue())
        self.assertFalse(self.home.exists())
        run.assert_not_called()

    def test_menu_only_does_not_query_desktop_or_launch_gui(self):
        with mock.patch.object(shortcut, "desktop_directory") as desktop, \
                mock.patch.object(shortcut, "system_tool", return_value=None), \
                mock.patch.object(shortcut.subprocess, "run") as run:
            self.assertEqual(shortcut.main(["--menu-only"]), 0)
        self.assertTrue(self.menu.is_file())
        self.assertTrue(os.access(self.menu, os.X_OK))
        desktop.assert_not_called()
        run.assert_not_called()

    def test_missing_xdg_tool_still_installs_menu(self):
        with mock.patch.object(shortcut, "system_tool", return_value=None):
            self.assertEqual(shortcut.main([]), 0)
        self.assertTrue(self.menu.exists())
        self.assertIn("只安装应用菜单", self.output.getvalue())

    def test_missing_or_invalid_desktop_does_not_create_a_desktop(self):
        for stdout in ("", "relative\n", str(self.directory / "missing") + "\n", str(self.home) + "\n"):
            with self.subTest(stdout=stdout), mock.patch.object(shortcut, "system_tool", return_value="/fake/xdg-user-dir"), \
                    mock.patch.object(shortcut.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, "")):
                desktop, note = shortcut.desktop_directory()
            self.assertIsNone(desktop)
            self.assertIn("只安装应用菜单", note)
        self.assertFalse((self.directory / "missing").exists())

    def test_xdg_failure_or_timeout_is_nonfatal(self):
        for failure in (OSError("missing"), subprocess.TimeoutExpired([], 5)):
            with self.subTest(failure=failure), mock.patch.object(shortcut, "system_tool", return_value="/fake/xdg"), \
                    mock.patch.object(shortcut.subprocess, "run", side_effect=failure):
                self.assertIsNone(shortcut.desktop_directory()[0])

    def test_force_replaces_only_recognizable_project_launcher(self):
        old = ("[Desktop Entry]\nType=Application\nName=Codex 额度悬浮球\n"
               "Exec=/bin/bash /old/codex-quota-float/run.sh --background\n")
        self.menu.parent.mkdir(parents=True)
        self.menu.write_text(old, encoding="utf-8")
        with mock.patch.object(shortcut, "system_tool", return_value=None):
            self.assertEqual(shortcut.main(["--menu-only"]), 1)
            self.assertEqual(self.menu.read_text(encoding="utf-8"), old)
            self.assertEqual(shortcut.main(["--menu-only", "--force"]), 0)
            self.assertEqual(self.menu.read_text(encoding="utf-8"), shortcut.launcher_content())
            self.assertEqual(shortcut.main(["--menu-only"]), 0)

    def test_force_never_overwrites_unrelated_or_unrecognizable_launchers(self):
        examples = [
            "[Desktop Entry]\nType=Application\nName=Other\nExec=/old/codex-quota-float/app.py\n",
            "[Desktop Entry]\nType=Application\nName=Codex 额度悬浮球\nExec=/usr/bin/true\n",
            "[Desktop Entry]\nType=Application\nName=Codex 额度悬浮球\nExec=/old/codex-quota-float/app.py.backup\n",
            "[Desktop Entry]\nType=Application\nName=Codex 额度悬浮球\nName=Other\nExec=/old/codex-quota-float/app.py\n",
        ]
        self.menu.parent.mkdir(parents=True)
        for previous in examples:
            self.menu.write_text(previous, encoding="utf-8")
            with self.subTest(previous=previous), mock.patch.object(shortcut, "system_tool", return_value=None):
                self.assertEqual(shortcut.main(["--menu-only", "--force"]), 1)
                self.assertEqual(self.menu.read_text(encoding="utf-8"), previous)

    def test_force_updates_own_launcher_from_a_renamed_release_directory(self):
        old_root = self.directory / "codex-quota-float-0.2.0 renamed"
        previous = shortcut.launcher_content(old_root, "/old venv/bin/python")
        self.assertTrue(shortcut.is_project_launcher(previous))
        self.menu.parent.mkdir(parents=True)
        self.menu.write_text(previous, encoding="utf-8")
        with mock.patch.object(shortcut, "system_tool", return_value=None):
            self.assertEqual(shortcut.main(["--menu-only", "--force"]), 0)
        self.assertEqual(self.menu.read_text(encoding="utf-8"), shortcut.launcher_content())

    def test_identity_marker_requires_matching_name_and_path_app_argument(self):
        content = shortcut.launcher_content(self.directory / "renamed", "/usr/bin/python3")
        self.assertFalse(shortcut.is_project_launcher(content.replace("Name=" + shortcut.APP_NAME, "Name=Other")))
        self.assertFalse(shortcut.is_project_launcher(content.replace("Path=" + str(self.directory / "renamed"), "Path=/unrelated")))

    def test_symlink_target_is_not_followed(self):
        other = self.directory / "other.txt"
        other.write_text("keep me", encoding="utf-8")
        self.menu.parent.mkdir(parents=True)
        self.menu.symlink_to(other)
        with mock.patch.object(shortcut, "system_tool", return_value=None):
            self.assertEqual(shortcut.main(["--menu-only", "--force"]), 1)
        self.assertEqual(other.read_text(), "keep me")
        self.assertTrue(self.menu.is_symlink())

    def test_all_targets_preflight_before_writing_menu(self):
        target = self.desktop / shortcut.LAUNCHER_NAME
        target.write_text("unrelated", encoding="utf-8")
        with mock.patch.object(shortcut, "desktop_directory", return_value=(self.desktop, None)):
            self.assertEqual(shortcut.main([]), 1)
        self.assertFalse(self.menu.exists())
        self.assertEqual(target.read_text(), "unrelated")

    def test_system_gio_preferred_over_virtual_environment(self):
        with mock.patch.object(Path, "is_file", return_value=True), \
                mock.patch.object(shortcut.os, "access", return_value=True), \
                mock.patch.object(shortcut.shutil, "which", return_value="/venv/bin/gio") as which:
            self.assertEqual(shortcut.system_tool("gio"), "/usr/bin/gio")
            which.assert_not_called()
        with mock.patch.object(Path, "is_file", return_value=False), \
                mock.patch.object(shortcut.shutil, "which", return_value="/elsewhere/gio"):
            self.assertEqual(shortcut.system_tool("gio"), "/elsewhere/gio")

    def test_gio_failure_does_not_break_menu(self):
        with mock.patch.object(shortcut, "desktop_directory", return_value=(self.desktop, None)), \
                mock.patch.object(shortcut, "system_tool", side_effect=lambda name: "/usr/bin/gio" if name == "gio" else None), \
                mock.patch.object(shortcut.subprocess, "run", side_effect=OSError("not supported")) as run:
            self.assertEqual(shortcut.main([]), 0)
        self.assertTrue(self.menu.exists())
        self.assertIn("允许启动", self.output.getvalue())
        self.assertEqual(run.call_args.args[0], ["/usr/bin/gio", "set", str(self.desktop / shortcut.LAUNCHER_NAME), "metadata::trusted", "true"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_explicit_codex_paths_are_preserved_as_env_argv(self):
        with mock.patch.dict(os.environ, {"CODEX_BIN": '/path with $`"\\%/codex', "CODEX_CLI_PATH": "/compat/codex"}), \
                mock.patch.object(shortcut, "system_tool", return_value="/usr/bin/env"):
            content = shortcut.launcher_content(self.directory / "codex-quota-float", "/usr/bin/python3")
        arguments = shortcut._exec_arguments(shortcut._unescape_string(next(line[5:] for line in content.splitlines() if line.startswith("Exec="))))
        self.assertEqual(arguments[:4], ["/usr/bin/env", 'CODEX_BIN=/path with $`"\\%/codex', "CODEX_CLI_PATH=/compat/codex", "/usr/bin/python3"])
        self.assertTrue(shortcut.is_project_launcher(content))

    def test_non_linux_exits_without_write(self):
        with mock.patch.object(shortcut.sys, "platform", "win32"):
            self.assertEqual(shortcut.main([]), 1)
        self.assertFalse(self.home.exists())

    def test_real_validator_and_independent_exec_parser_for_special_paths(self):
        validator = shutil.which("desktop-file-validate", path="/usr/bin:/bin")
        if validator is None:
            self.skipTest("desktop-file-validate is not installed")
        root = self.directory / 'space 20% "quote" \\slash $dollar `tick` 中文' / "codex-quota-float"
        root.mkdir(parents=True)
        python = root.parent / 'venv % " \\ $ ` /bin/python'
        content = shortcut.launcher_content(root, python)
        target = self.directory / "validate.desktop"
        target.write_text(content, encoding="utf-8")
        result = subprocess.run([validator, str(target)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        perl = shutil.which("perl", path="/usr/bin:/bin")
        if perl and Path("/usr/share/perl5/File/DesktopEntry.pm").exists():
            # parse_Exec only expands argv; it never starts the application.
            result = subprocess.run([perl, "-MFile::DesktopEntry", "-MJSON::PP", "-e",
                '$e=File::DesktopEntry->new($ARGV[0]); print encode_json([$e->parse_Exec()]);',
                str(target)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(python), str(root / "app.py"), "--background"])
        self.assertTrue(shortcut.is_project_launcher(content))


if __name__ == "__main__":
    unittest.main()
