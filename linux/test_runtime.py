# SPDX-License-Identifier: GPL-3.0-only
"""Offline checks for per-user paths and executable discovery."""

import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import runtime


class RuntimePathTests(unittest.TestCase):
    def test_defaults_follow_each_users_home(self):
        for home in ("/home/alice", "/home/bob"):
            with self.subTest(home=home), mock.patch.dict(os.environ, {"HOME": home}, clear=True):
                self.assertEqual(runtime.settings_path(), Path(home) / ".config/codex-quota-float/settings.json")
                self.assertEqual(runtime.log_path(), Path(home) / ".local/state/codex-quota-float/app.log")

    def test_absolute_xdg_values_override_home(self):
        with mock.patch.dict(os.environ, {
            "HOME": "/home/example", "XDG_CONFIG_HOME": "/custom/config", "XDG_STATE_HOME": "/custom/state",
        }, clear=True):
            self.assertEqual(runtime.settings_path(), Path("/custom/config/codex-quota-float/settings.json"))
            self.assertEqual(runtime.log_path(), Path("/custom/state/codex-quota-float/app.log"))

    def test_relative_empty_and_tilde_xdg_values_are_ignored(self):
        for value in ("relative", "", "~/config"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {
                "HOME": "/home/example", "XDG_CONFIG_HOME": value, "XDG_STATE_HOME": value,
            }, clear=True):
                self.assertEqual(runtime.settings_path(), Path("/home/example/.config/codex-quota-float/settings.json"))
                self.assertEqual(runtime.log_path(), Path("/home/example/.local/state/codex-quota-float/app.log"))

    def test_import_and_path_queries_do_not_write_to_read_only_locations(self):
        with mock.patch.dict(os.environ, {
            "HOME": "/read-only/home", "XDG_CONFIG_HOME": "/read-only/config", "XDG_STATE_HOME": "/read-only/state",
        }, clear=True), mock.patch.object(Path, "mkdir", side_effect=PermissionError) as mkdir, \
                mock.patch.object(Path, "write_text", side_effect=PermissionError) as write_text, \
                mock.patch.object(Path, "open", side_effect=PermissionError) as open_file:
            importlib.reload(runtime)
            self.assertEqual(runtime.PROJECT_ROOT, Path(__file__).resolve().parent)
            self.assertEqual(runtime.settings_path(), Path("/read-only/config/codex-quota-float/settings.json"))
            self.assertEqual(runtime.log_path(), Path("/read-only/state/codex-quota-float/app.log"))
            mkdir.assert_not_called()
            write_text.assert_not_called()
            open_file.assert_not_called()


class BinaryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        platform = mock.patch.object(runtime.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)
        self.directory = tempfile.TemporaryDirectory(prefix="quota-runtime-test-")
        self.addCleanup(self.directory.cleanup)

    def executable(self, name="codex"):
        path = Path(self.directory.name) / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_explicit_path_wins_over_alias_and_path_search(self):
        explicit = self.executable()
        with mock.patch.dict(os.environ, {"CODEX_BIN": explicit, "CODEX_CLI_PATH": "/ignored"}), \
                mock.patch.object(runtime.shutil, "which") as which:
            self.assertEqual(runtime.resolve_codex_binary(), explicit)
            which.assert_not_called()

    def test_compatibility_alias_accepts_command_names(self):
        executable = self.executable()
        with mock.patch.dict(os.environ, {"CODEX_CLI_PATH": "codex-custom"}), \
                mock.patch.object(runtime.shutil, "which", return_value=executable) as which:
            self.assertEqual(runtime.resolve_codex_binary(), executable)
            which.assert_called_once_with("codex-custom")

    def test_explicit_command_is_found_in_path(self):
        executable = self.executable("custom-codex")
        with mock.patch.dict(os.environ, {"CODEX_BIN": "custom-codex", "PATH": self.directory.name}):
            self.assertEqual(runtime.resolve_codex_binary(), executable)

    def test_tilde_in_explicit_path_uses_current_home(self):
        executable = self.executable()
        with mock.patch.dict(os.environ, {"CODEX_BIN": "~/codex", "HOME": self.directory.name}):
            self.assertEqual(runtime.resolve_codex_binary(), executable)

    def test_invalid_explicit_paths_do_not_fall_back_or_disclose_path(self):
        not_executable = Path(self.directory.name) / "private-user-binary"
        not_executable.write_text("not executable", encoding="utf-8")
        for value in (str(not_executable), str(not_executable.parent), "/private-user/missing", ""):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CODEX_BIN": value}), \
                    mock.patch.object(runtime.shutil, "which") as which:
                with self.assertRaisesRegex(RuntimeError, "CODEX_BIN 配置无效") as caught:
                    runtime.resolve_codex_binary()
                self.assertNotIn("private-user", str(caught.exception))
                self.assertNotIn(self.directory.name, str(caught.exception))
                which.assert_not_called()

    def test_invalid_explicit_command_does_not_search_default_command(self):
        with mock.patch.dict(os.environ, {"CODEX_BIN": "missing-command"}), \
                mock.patch.object(runtime.shutil, "which", return_value=None) as which:
            with self.assertRaisesRegex(RuntimeError, "CODEX_BIN 配置无效"):
                runtime.resolve_codex_binary()
            which.assert_called_once_with("missing-command")

    def test_path_command_wins_over_fixed_linux_locations(self):
        executable = self.executable()
        with mock.patch.dict(os.environ, {"PATH": self.directory.name}), \
                mock.patch.object(runtime, "_is_executable") as fixed_check:
            self.assertEqual(runtime.resolve_codex_binary(), executable)
            fixed_check.assert_not_called()

    def test_fixed_linux_locations_are_checked_in_order(self):
        expected = runtime._LINUX_CODEX_PATHS[1]
        with mock.patch.object(runtime.shutil, "which", return_value=None), \
                mock.patch.object(runtime, "_is_executable", side_effect=lambda path: path == expected) as check:
            self.assertEqual(runtime.resolve_codex_binary(), expected)
            self.assertEqual(check.call_args_list, [mock.call(path) for path in runtime._LINUX_CODEX_PATHS[:2]])

    def test_missing_executable_reports_actionable_error(self):
        with mock.patch.object(runtime.shutil, "which", return_value=None), \
                mock.patch.object(runtime, "_is_executable", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "未找到 Codex") as caught:
                runtime.resolve_codex_binary()
            self.assertIn("CODEX_BIN", str(caught.exception))
            self.assertNotIn("/usr/lib", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
