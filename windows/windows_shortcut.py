#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Per-user Windows shortcuts with JSON data for environment overrides.

WScript.Shell receives data via stdin. No paths or settings are interpolated into
PowerShell source. Importing this module never writes files or runs commands.
"""
import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent
APP_NAME = "Codex 额度悬浮球"
LAUNCHER_NAME = APP_NAME + ".lnk"
IDENTITY = "codex-quota-float/windows-launcher-v1"
DESCRIPTION = APP_NAME + " | " + IDENTITY
OVERRIDE_KEYS = ("CODEX_BIN", "CODEX_CLI_PATH")
_FOLDERS = {
    "programs": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
}
_SHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut([string]$request.path)
if ($request.operation -eq 'write') {
    $link.TargetPath = [string]$request.spec.TargetPath
    $link.Arguments = [string]$request.spec.Arguments
    $link.WorkingDirectory = [string]$request.spec.WorkingDirectory
    $link.Description = [string]$request.spec.Description
    $link.WindowStyle = 7
    $link.IconLocation = [string]$request.spec.IconLocation
    $link.Save()
} elseif ($request.operation -eq 'read') {
    @{
        TargetPath = $link.TargetPath
        Arguments = $link.Arguments
        WorkingDirectory = $link.WorkingDirectory
        Description = $link.Description
        IconLocation = $link.IconLocation
    } | ConvertTo-Json -Compress
} else { throw 'Invalid shortcut operation' }
"""


class InstallError(RuntimeError):
    """A shortcut or configuration could not be installed safely."""


def known_folder(name):
    """Read the user's Known Folder, including redirected desktops."""
    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]

    guid = GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(_FOLDERS[name]).bytes_le))
    shell, ole = ctypes.OleDLL("shell32"), ctypes.OleDLL("ole32")
    function = shell.SHGetKnownFolderPath
    function.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_wchar_p)]
    function.restype = ctypes.c_long
    value = ctypes.c_wchar_p()
    try:
        if function(ctypes.byref(guid), 0, None, ctypes.byref(value)) != 0 or not value.value:
            raise InstallError(f"无法读取 Windows {name} 用户目录。")
        return Path(value.value)
    finally:
        if value:
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree.restype = None
            ole.CoTaskMemFree(ctypes.cast(value, ctypes.c_void_p))


def config_path():
    from runtime import log_path
    return log_path().parent / "launcher.json"


def _valid_text(value):
    return isinstance(value, str) and "\x00" not in value


def launcher_config(project_root=None):
    root = Path(project_root if project_root is not None else PROJECT_ROOT).resolve()
    overrides = {key: os.environ[key] for key in OVERRIDE_KEYS if key in os.environ}
    if not all(_valid_text(value) for value in overrides.values()):
        raise InstallError("CODEX_BIN / CODEX_CLI_PATH 不能包含 NUL 字符。")
    return {"identity": IDENTITY, "project_root": str(root), "overrides": overrides}


def is_project_config(value):
    return (isinstance(value, dict) and set(value) == {"identity", "project_root", "overrides"}
            and value.get("identity") == IDENTITY and _valid_text(value.get("project_root"))
            and Path(value["project_root"]).is_absolute()
            and isinstance(value.get("overrides"), dict)
            and set(value["overrides"]) <= set(OVERRIDE_KEYS)
            and all(_valid_text(item) for item in value["overrides"].values()))


def windowless_python(executable=None):
    executable = Path(executable if executable is not None else sys.executable)
    if not executable.is_absolute():
        raise InstallError("请使用绝对路径的 Python 解释器安装快捷方式。")
    candidate = executable.with_name("pythonw.exe")
    if not candidate.is_file():
        raise InstallError("未找到同环境的 pythonw.exe；请使用包含 Windows GUI 支持的 Python 环境安装快捷方式。")
    return candidate


def shortcut_spec(configuration, project_root=None, python_executable=None):
    root = Path(project_root if project_root is not None else PROJECT_ROOT).resolve()
    python = windowless_python(python_executable)
    icon = root / "quota-icon.ico"
    return {
        "TargetPath": str(python),
        "Arguments": subprocess.list2cmdline([str(root / "windows_shortcut.py"), "--launch", str(configuration)]),
        "WorkingDirectory": str(root),
        "Description": DESCRIPTION,
        "IconLocation": str(icon if icon.is_file() else python) + ",0",
    }


def _shell(operation, path, spec=None):
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    powershell = str(system) if system.is_file() else shutil.which("powershell.exe")
    if not powershell:
        raise InstallError("未找到 Windows PowerShell，无法创建原生快捷方式。")
    encoded = base64.b64encode(_SHELL_SCRIPT.encode("utf-16-le")).decode("ascii")
    request = {"operation": operation, "path": str(path), "spec": spec}
    try:
        result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                input=json.dumps(request, ensure_ascii=True), capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InstallError(f"Windows 快捷方式操作失败：{error}") from error
    if result.returncode:
        raise InstallError(f"Windows 快捷方式操作失败：{result.stderr.strip()}")
    if operation == "read":
        try:
            value = json.loads(result.stdout.lstrip("\ufeff"))
            if not isinstance(value, dict):
                raise ValueError("Expected a shortcut object")
            return value
        except (ValueError, TypeError) as error:
            raise InstallError("无法读取已有快捷方式，已保留原文件。") from error
    return None


def is_project_shortcut(spec, configuration):
    if not isinstance(spec, dict) or spec.get("Description") != DESCRIPTION:
        return False
    directory = spec.get("WorkingDirectory", "")
    if not _valid_text(directory):
        return False
    root = Path(directory)
    if not root.is_absolute():
        return False
    return spec.get("Arguments") == subprocess.list2cmdline(
        [str(root / "windows_shortcut.py"), "--launch", str(configuration)])


def _regular_target(target):
    if target.is_symlink():
        raise InstallError(f"拒绝覆盖符号链接：{target}")
    if not target.exists():
        return False
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise InstallError(f"目标不是普通文件，已保留：{target}")
    return True


def _preflight_config(target, content, force):
    if not _regular_target(target):
        return
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise InstallError(f"已有配置无法识别，已保留：{target}") from error
    if previous == content or (force and is_project_config(previous)):
        return
    raise InstallError(f"已有配置内容不同；仅本项目配置可用 --force 更新：{target}")


def _preflight_shortcut(target, spec, configuration, force):
    if not _regular_target(target):
        return
    previous = _shell("read", target)
    if previous == spec or (force and is_project_shortcut(previous, configuration)):
        return
    raise InstallError(f"已有快捷方式内容不同；仅本项目快捷方式可用 --force 更新：{target}")


def _write_config(target, content, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".launcher-", suffix=".json", delete=False) as file:
            temporary = Path(file.name)
            json.dump(content, file, ensure_ascii=False, indent=2)
            file.write("\n")
        _preflight_config(target, content, force)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_shortcut(target, spec, configuration, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".quota-", suffix=".lnk", delete=False) as file:
            temporary = Path(file.name)
        # WScript.Shell can reject an empty .lnk, so start with a new path.
        temporary.unlink()
        _shell("write", temporary, spec)
        _preflight_shortcut(target, spec, configuration, force)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def launch(configuration):
    """Apply overrides as data, then start the application's background mode."""
    from runtime import log_path
    try:
        config = json.loads(Path(configuration).read_text(encoding="utf-8"))
        if not is_project_config(config) or Path(config["project_root"]).resolve() != PROJECT_ROOT:
            raise InstallError("启动器配置无效；请重新安装快捷方式。")
        environment = os.environ.copy()
        environment.update(config["overrides"])
        environment["PYTHONIOENCODING"] = "utf-8"
        target = log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as output:
            subprocess.Popen([str(windowless_python()), str(PROJECT_ROOT / "app.py"), "--background"],
                             cwd=PROJECT_ROOT, env=environment, stdin=subprocess.DEVNULL,
                             stdout=output, stderr=output,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
        return 0
    except (InstallError, OSError, ValueError, UnicodeError) as error:
        target = log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as file:
            file.write(f"快捷方式启动失败：{error}\n")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装 Codex 额度悬浮球的 Windows 桌面及开始菜单快捷方式。")
    parser.add_argument("--dry-run", action="store_true", help="仅显示路径和配置，不写文件或创建快捷方式")
    parser.add_argument("--menu-only", action="store_true", help="只安装当前用户的开始菜单快捷方式")
    parser.add_argument("--force", action="store_true", help="仅允许更新本项目已有快捷方式和启动器配置")
    parser.add_argument("--launch", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Windows 快捷方式安装只能在 Windows 上运行。", file=sys.stderr)
        return 1
    if options.launch is not None:
        return launch(options.launch)
    try:
        configuration = config_path()
        config = launcher_config()
        spec = shortcut_spec(configuration)
        programs = known_folder("programs")
        targets = [programs / LAUNCHER_NAME]
        if not options.menu_only:
            desktop = known_folder("desktop")
            if desktop.is_dir():
                targets.append(desktop / LAUNCHER_NAME)
            else:
                print("桌面目录不存在；只安装开始菜单快捷方式。")
        targets = list(dict.fromkeys(targets))
        if options.dry_run:
            for target in targets:
                print(f"将生成：{target}")
            print(f"启动器配置：{configuration}")
            print(json.dumps({"shortcut": spec, "configuration": config}, ensure_ascii=False, indent=2))
            return 0
        _preflight_config(configuration, config, options.force)
        for target in targets:
            _preflight_shortcut(target, spec, configuration, options.force)
        _write_config(configuration, config, options.force)
        for target in targets:
            _write_shortcut(target, spec, configuration, options.force)
            print(f"已创建：{target}")
        print("可在开始菜单中搜索‘Codex 额度悬浮球’。移动项目或 Python 环境后，请重新运行安装命令并加 --force。")
        return 0
    except (InstallError, OSError, UnicodeError) as error:
        print(f"安装失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
