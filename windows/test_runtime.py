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
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="quota-path-test-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.home = self.base / "home"
        for patcher in (
            mock.patch.object(runtime.sys, "platform", "linux"),
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_defaults_follow_each_users_home(self):
        for home in (self.base / "alice", self.base / "bob"):
            with self.subTest(home=home), mock.patch.object(Path, "home", return_value=home):
                self.assertEqual(runtime.settings_path(), Path(home) / ".config/codex-quota-float/settings.json")
                self.assertEqual(runtime.log_path(), Path(home) / ".local/state/codex-quota-float/app.log")

    def test_absolute_xdg_values_override_home(self):
        config = self.base / "custom" / "config"
        state = self.base / "custom" / "state"
        with mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(config), "XDG_STATE_HOME": str(state),
        }, clear=True):
            self.assertEqual(runtime.settings_path(), config / "codex-quota-float/settings.json")
            self.assertEqual(runtime.log_path(), state / "codex-quota-float/app.log")

    def test_relative_empty_and_tilde_xdg_values_are_ignored(self):
        for value in ("relative", "", "~/config"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {
                "XDG_CONFIG_HOME": value, "XDG_STATE_HOME": value,
            }, clear=True):
                self.assertEqual(runtime.settings_path(), self.home / ".config/codex-quota-float/settings.json")
                self.assertEqual(runtime.log_path(), self.home / ".local/state/codex-quota-float/app.log")

    def test_windows_appdata_paths_override_xdg_settings(self):
        roaming = self.base / "Roaming"
        local = self.base / "Local"
        with mock.patch.object(runtime.sys, "platform", "win32"), mock.patch.dict(os.environ, {
            "APPDATA": str(roaming), "LOCALAPPDATA": str(local),
            "XDG_CONFIG_HOME": str(self.base / "ignored"),
        }):
            self.assertEqual(runtime.settings_path(), roaming / "codex-quota-float/settings.json")
            self.assertEqual(runtime.log_path(), local / "codex-quota-float/app.log")

    def test_windows_missing_or_relative_appdata_uses_home_fallback(self):
        for value in (None, "", "relative", "~/data"):
            environment = {} if value is None else {"APPDATA": value, "LOCALAPPDATA": value}
            with self.subTest(value=value), mock.patch.object(runtime.sys, "platform", "win32"), \
                    mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(runtime.settings_path(), self.home / "AppData/Roaming/codex-quota-float/settings.json")
                self.assertEqual(runtime.log_path(), self.home / "AppData/Local/codex-quota-float/app.log")

    def test_import_and_path_queries_do_not_write_to_read_only_locations(self):
        config = self.base / "read-only" / "config"
        state = self.base / "read-only" / "state"
        with mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(config), "XDG_STATE_HOME": str(state),
        }, clear=True), mock.patch.object(Path, "mkdir", side_effect=PermissionError) as mkdir, \
                mock.patch.object(Path, "write_text", side_effect=PermissionError) as write_text, \
                mock.patch.object(Path, "open", side_effect=PermissionError) as open_file:
            importlib.reload(runtime)
            self.assertEqual(runtime.PROJECT_ROOT, Path(__file__).resolve().parent)
            self.assertEqual(runtime.settings_path(), config / "codex-quota-float/settings.json")
            self.assertEqual(runtime.log_path(), state / "codex-quota-float/app.log")
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
        executable = self.executable("custom-codex.exe")
        with mock.patch.dict(os.environ, {
            "CODEX_BIN": "custom-codex.exe", "PATH": self.directory.name, "PATHEXT": ".EXE",
        }):
            self.assertEqual(runtime.resolve_codex_binary(), executable)

    def test_tilde_in_explicit_path_uses_current_home(self):
        executable = self.executable()
        with mock.patch.dict(os.environ, {
            "CODEX_BIN": "~/codex", "HOME": self.directory.name, "USERPROFILE": self.directory.name,
        }):
            self.assertEqual(runtime.resolve_codex_binary(), executable)

    def test_invalid_explicit_paths_do_not_fall_back_or_disclose_path(self):
        not_executable = Path(self.directory.name) / "private-user-binary"
        not_executable.write_text("not executable", encoding="utf-8")
        for value in (str(not_executable), str(not_executable.parent), "/private-user/missing", ""):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CODEX_BIN": value}), \
                    mock.patch.object(runtime, "_is_executable", return_value=False), \
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
        with mock.patch.object(runtime.shutil, "which", return_value=executable), \
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


class WindowsBinaryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="quota-windows-test-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        for patcher in (
            mock.patch.object(runtime.sys, "platform", "win32"),
            mock.patch.object(runtime.platform, "machine", return_value="AMD64"),
            mock.patch.object(Path, "home", return_value=self.base / "home"),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "Local")}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def file(self, relative):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("offline discovery fixture; never execute", encoding="utf-8")
        return path

    def test_native_override_with_spaces_never_uses_shell_or_path_search(self):
        executable = self.file("Codex Tools/codex.EXE")
        with mock.patch.dict(os.environ, {"CODEX_BIN": str(executable)}), \
                mock.patch.object(runtime.shutil, "which") as which:
            self.assertEqual(runtime.resolve_codex_binary(), str(executable))
            which.assert_not_called()

    def test_native_path_binary_wins_over_desktop_install(self):
        executable = self.file("path/codex.exe")
        with mock.patch.object(runtime.shutil, "which", return_value=str(executable)) as which, \
                mock.patch.object(runtime, "_windows_codex_candidates") as desktop:
            self.assertEqual(runtime.resolve_codex_binary(), str(executable))
            which.assert_called_once_with("codex")
            desktop.assert_not_called()

    def test_global_npm_cmd_and_powershell_shims_resolve_bundled_native_binary(self):
        native = self.file("npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe")
        for extension in ("cmd", "ps1"):
            shim = self.file("npm/codex." + extension)
            with self.subTest(extension=extension), mock.patch.object(runtime.shutil, "which", return_value=str(shim)):
                self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_explicit_npm_shim_uses_current_hoisted_platform_package(self):
        shim = self.file("npm/codex.cmd")
        native = self.file("npm/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
        with mock.patch.dict(os.environ, {"CODEX_BIN": str(shim)}), \
                mock.patch.object(runtime.shutil, "which") as which:
            self.assertEqual(runtime.resolve_codex_binary(), str(native))
            which.assert_not_called()

    def test_local_npm_shim_uses_nested_optional_dependency(self):
        shim = self.file("project/node_modules/.bin/codex.cmd")
        native = self.file(
            "project/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/"
            "vendor/x86_64-pc-windows-msvc/bin/codex.exe"
        )
        with mock.patch.dict(os.environ, {"CODEX_CLI_PATH": str(shim)}):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_arm64_npm_shim_selects_arm64_package(self):
        shim = self.file("npm/codex.ps1")
        native = self.file("npm/node_modules/@openai/codex-win32-arm64/vendor/aarch64-pc-windows-msvc/bin/codex.exe")
        self.file("npm/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
        with mock.patch.object(runtime.platform, "machine", return_value="ARM64"), \
                mock.patch.dict(os.environ, {"CODEX_BIN": str(shim)}):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_unresolvable_explicit_wrapper_does_not_fall_back(self):
        shim = self.file("private-user/codex.cmd")
        self.file("Local/OpenAI/Codex/bin/available/codex.exe")
        with mock.patch.dict(os.environ, {"CODEX_BIN": str(shim)}), \
                mock.patch.object(runtime.shutil, "which") as which, \
                mock.patch.object(runtime, "_windows_codex_candidates") as desktop:
            with self.assertRaisesRegex(RuntimeError, "CODEX_BIN 配置无效") as caught:
                runtime.resolve_codex_binary()
            self.assertNotIn("private-user", str(caught.exception))
            which.assert_not_called()
            desktop.assert_not_called()

    def test_broken_path_wrapper_does_not_prevent_desktop_discovery(self):
        shim = self.file("npm/codex.cmd")
        native = self.file("Local/OpenAI/Codex/bin/current/codex.exe")
        with mock.patch.object(runtime.shutil, "which", return_value=str(shim)):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_powershell_wrapper_is_found_when_plain_command_lookup_misses_it(self):
        shim = self.file("npm/codex.ps1")
        native = self.file("npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
        with mock.patch.dict(os.environ, {"PATH": str(shim.parent), "PATHEXT": ".EXE"}), \
                mock.patch.object(runtime.shutil, "which", return_value=None):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_explicit_powershell_command_works_without_ps1_in_pathext(self):
        shim = self.file("npm/codex.ps1")
        native = self.file("npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
        with mock.patch.dict(os.environ, {
            "CODEX_BIN": "codex.ps1", "PATH": str(shim.parent), "PATHEXT": ".EXE",
        }):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_newest_desktop_binary_is_selected_without_fixed_version_paths(self):
        old = self.file("Local/OpenAI/Codex/bin/older-hash/codex.exe")
        new = self.file("Local/OpenAI/Codex/bin/newer-hash/codex.exe")
        os.utime(old, (100, 100))
        os.utime(new, (200, 200))
        with mock.patch.object(runtime.shutil, "which", return_value=None):
            self.assertEqual(runtime.resolve_codex_binary(), str(new))

    def test_store_resources_binary_is_discovered(self):
        native = self.file("Program Files/WindowsApps/OpenAI.Codex_1.0_x64__publisher/app/resources/codex.exe")
        with mock.patch.dict(os.environ, {"ProgramFiles": str(self.base / "Program Files")}), \
                mock.patch.object(runtime.shutil, "which", return_value=None):
            self.assertEqual(runtime.resolve_codex_binary(), str(native))

    def test_inaccessible_store_directory_yields_actionable_missing_error(self):
        with mock.patch.object(runtime.shutil, "which", return_value=None), \
                mock.patch.object(Path, "glob", side_effect=PermissionError):
            with self.assertRaisesRegex(RuntimeError, "未找到 Codex"):
                runtime.resolve_codex_binary()

    def test_native_binary_requires_exe_instead_of_windows_script(self):
        for suffix in ("cmd", "ps1", "bat", "py"):
            file = self.file("scripts/codex." + suffix)
            with self.subTest(suffix=suffix):
                self.assertFalse(runtime._is_executable(file))


if __name__ == "__main__":
    unittest.main()
