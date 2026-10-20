#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Per-user Windows shortcuts with JSON data for environment overrides.

Shell links use the native Unicode COM interfaces, including file persistence.
Importing this module never writes files or runs commands.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
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
        # Resolve redirected paths without requiring a Desktop to exist.
        if function(ctypes.byref(guid), 0x4000, None, ctypes.byref(value)) != 0 or not value.value:
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


def application_directory(project_root=None):
    """Keep installed shortcuts beside the real EXE, outside PyInstaller's temp tree."""
    if project_root is not None:
        return Path(project_root).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def launcher_config(project_root=None):
    root = application_directory(project_root)
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
    root = application_directory(project_root)
    if getattr(sys, "frozen", False):
        program = Path(sys.executable).resolve()
        arguments = ["--launch", str(configuration)]
    else:
        program = windowless_python(python_executable)
        arguments = [str(root / "windows_shortcut.py"), "--launch", str(configuration)]
    icon = root / "quota-icon.ico"
    return {
        "TargetPath": str(program),
        "Arguments": subprocess.list2cmdline(arguments),
        "WorkingDirectory": str(root),
        "Description": DESCRIPTION,
        "IconLocation": str(icon if icon.is_file() else program) + ",0",
    }


def _shell(operation, path, spec=None):
    """Use IShellLinkW + IPersistFile; WshShortcut.Save uses the ANSI code page.

    COM method slots follow shobjidl_core.h and objidl.h. Every path and string
    uses WCHAR, so shortcut names work independently of the system locale.
    """
    if operation not in ("read", "write"):
        raise InstallError("无效的快捷方式操作。")

    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]

        def __init__(self, value):
            super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))

    def invoke(pointer, slot, argument_types=(), *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argument_types)(table[slot])
        result = method(pointer, *arguments)
        if result < 0:
            raise ctypes.WinError(result)

    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = False
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        result = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        initialized = result in (0, 1)
        if result < 0 and result != -2147417850:  # Existing COM apartment: RPC_E_CHANGED_MODE
            raise ctypes.WinError(result)
        clsid = GUID("00021401-0000-0000-C000-000000000046")
        iid_link = GUID("000214F9-0000-0000-C000-000000000046")
        result = ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid_link), ctypes.byref(link))
        if result < 0:
            raise ctypes.WinError(result)
        iid_persist = GUID("0000010B-0000-0000-C000-000000000046")
        invoke(link, 0, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)),
               ctypes.byref(iid_persist), ctypes.byref(persist))
        if operation == "write":
            for key, slot in (("TargetPath", 20), ("Arguments", 11),
                              ("WorkingDirectory", 9), ("Description", 7)):
                invoke(link, slot, (ctypes.c_wchar_p,), spec[key])
            icon, index = spec["IconLocation"].rsplit(",", 1)
            invoke(link, 17, (ctypes.c_wchar_p, ctypes.c_int), icon, int(index))
            invoke(link, 15, (ctypes.c_int,), 7)
            invoke(persist, 6, (ctypes.c_wchar_p, ctypes.c_int), str(path), 1)
            return None
        invoke(persist, 5, (ctypes.c_wchar_p, ctypes.c_uint32), str(path), 0)
        value = {}
        for key, slot in (("TargetPath", 3), ("Arguments", 10),
                          ("WorkingDirectory", 8), ("Description", 6), ("IconLocation", 16)):
            buffer = ctypes.create_unicode_buffer(32768)
            types = (ctypes.c_wchar_p, ctypes.c_int)
            arguments = (buffer, len(buffer))
            if key == "TargetPath":
                types += (ctypes.c_void_p, ctypes.c_uint32)
                arguments += (None, 4)  # SLGP_RAWPATH; do not resolve or expand the target.
            elif key == "IconLocation":
                index = ctypes.c_int()
                types += (ctypes.POINTER(ctypes.c_int),)
                arguments += (ctypes.byref(index),)
            invoke(link, slot, types, *arguments)
            value[key] = buffer.value + (f",{index.value}" if key == "IconLocation" else "")
        return value
    except (OSError, ValueError, TypeError) as error:
        raise InstallError(f"Windows 快捷方式操作失败：{error}") from error
    finally:
        for pointer in (persist, link):
            if pointer:
                invoke(pointer, 2)  # IUnknown.Release
        if initialized:
            ole.CoUninitialize()


def is_project_shortcut(spec, configuration):
    if not isinstance(spec, dict) or spec.get("Description") != DESCRIPTION:
        return False
    directory = spec.get("WorkingDirectory", "")
    if not _valid_text(directory):
        return False
    root = Path(directory)
    if not root.is_absolute():
        return False
    arguments = spec.get("Arguments")
    if arguments == subprocess.list2cmdline(
            [str(root / "windows_shortcut.py"), "--launch", str(configuration)]):
        return True
    target = spec.get("TargetPath", "")
    return (_valid_text(target) and Path(target).is_absolute()
            and Path(target).suffix.lower() == ".exe" and Path(target).parent == root
            and arguments == subprocess.list2cmdline(["--launch", str(configuration)]))


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
        # Save a new shell link before replacing the final destination.
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
        root = application_directory()
        if not is_project_config(config) or Path(config["project_root"]).resolve() != root:
            raise InstallError("启动器配置无效；请重新安装快捷方式。")
        environment = os.environ.copy()
        environment.update(config["overrides"])
        environment["PYTHONIOENCODING"] = "utf-8"
        if getattr(sys, "frozen", False):
            environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        target = log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        command = ([str(Path(sys.executable).resolve()), "--background"]
                   if getattr(sys, "frozen", False) else
                   [str(windowless_python()), str(root / "app.py"), "--background"])
        with target.open("a", encoding="utf-8") as output:
            subprocess.Popen(command,
                             cwd=root, env=environment, stdin=subprocess.DEVNULL,
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
        print("可在开始菜单中搜索‘Codex 额度悬浮球’。移动程序后，请重新运行安装命令并加 --force。")
        return 0
    except (InstallError, OSError, UnicodeError) as error:
        print(f"安装失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
