# SPDX-License-Identifier: GPL-3.0-only
"""Portable runtime paths and native Codex executable discovery.

Importing this module or asking for a path never creates files or directories.
"""

import contextlib
import os
from pathlib import Path
import platform
import shutil
import sys
import threading


PROJECT_ROOT = Path(__file__).resolve().parent
APP_VERSION = "1.1.2"
_APP_DIRECTORY = "codex-quota-float"
_EXTERNAL_PROGRAM_LOCK = threading.RLock()
_LINUX_CODEX_PATHS = (
    "/usr/lib/chatgpt/resources/codex",
    "/opt/chatgpt/resources/codex",
    "/usr/lib/codex/resources/codex",
)


@contextlib.contextmanager
def external_program_environment():
    """Keep bundled DLLs out of external programs, then restore Qt's search.

    DLL search configuration belongs to the whole process. Serialize external
    launches from the GUI and its quota worker so their resets cannot overlap.
    Self-relaunches use PyInstaller's environment reset instead of this helper.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield None
        return
    import ctypes
    from ctypes import wintypes
    with _EXTERNAL_PROGRAM_LOCK:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_directory = kernel.GetDllDirectoryW
        get_directory.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
        get_directory.restype = wintypes.DWORD
        set_directory = kernel.SetDllDirectoryW
        set_directory.argtypes = [wintypes.LPCWSTR]
        set_directory.restype = wintypes.BOOL
        size = get_directory(0, None)
        previous = ctypes.create_unicode_buffer(size + 1)
        get_directory(len(previous), previous)
        bundle = Path(sys._MEIPASS).resolve()
        environment = os.environ.copy()
        paths = []
        for entry in environment.get("PATH", "").split(os.pathsep):
            try:
                if entry and Path(entry).resolve().is_relative_to(bundle):
                    continue
            except (OSError, ValueError):
                pass
            paths.append(entry)
        environment["PATH"] = os.pathsep.join(paths)
        if not set_directory(None):
            raise OSError("Cannot reset DLL directory")
        try:
            yield environment
        finally:
            set_directory(previous.value or None)


def launch_command():
    """Return a direct relaunch command for a source tree or a frozen EXE.

    Bundled resources live under PROJECT_ROOT; PyInstaller extracts them to a
    temporary directory. Relaunch the real executable rather than those files.
    """
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return [str(executable)]
    if sys.platform == "win32":
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
    return [str(executable), str(PROJECT_ROOT / "app.py")]


def launch_directory():
    """Keep an EXE's working directory independent of its temporary bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def ensure_output_streams():
    """Give windowed Python/EXE builds usable output streams for diagnostics.

    Importing this module stays side-effect free. The application calls this
    only at startup; existing console streams are always preserved.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        destination = log_path()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = destination.open("a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _xdg_directory(variable, default):
    value = os.environ.get(variable)
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / default


def settings_path() -> Path:
    """Return the user settings path without accessing or creating the file."""
    if sys.platform == "win32":
        return _xdg_directory("APPDATA", "AppData/Roaming") / _APP_DIRECTORY / "settings.json"
    return _xdg_directory("XDG_CONFIG_HOME", ".config") / _APP_DIRECTORY / "settings.json"


def log_path() -> Path:
    """Return the background log path without accessing or creating the file."""
    if sys.platform == "win32":
        return _xdg_directory("LOCALAPPDATA", "AppData/Local") / _APP_DIRECTORY / "app.log"
    return _xdg_directory("XDG_STATE_HOME", ".local/state") / _APP_DIRECTORY / "app.log"


def _is_executable(path):
    try:
        if sys.platform == "win32":
            return str(path).lower().endswith(".exe") and os.path.isfile(path)
        return os.path.isfile(path) and os.access(path, os.X_OK)
    except (OSError, ValueError):
        return False


def _windows_npm_binary(shim):
    """Resolve npm's wrappers to their binary without executing a shell or JS."""
    shim = Path(shim)
    if shim.suffix.lower() not in (".cmd", ".bat", ".ps1") or not shim.is_file():
        return None
    # Global npm installs put wrappers beside node_modules; local installs put
    # them in node_modules/.bin. Resolve the package link for pnpm layouts too.
    modules = shim.parent.parent if shim.parent.name == ".bin" else shim.parent / "node_modules"
    package = (modules / "@openai" / "codex").resolve()
    architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    triple = "aarch64-pc-windows-msvc" if architecture == "arm64" else "x86_64-pc-windows-msvc"
    platform_package = "codex-win32-" + architecture
    roots = (
        package / "node_modules" / "@openai" / platform_package,
        modules / "@openai" / platform_package,
        package,
    )
    for root in roots:
        # Current releases use bin/; earlier CLI releases used codex/.
        for directory in ("bin", "codex"):
            candidate = root / "vendor" / triple / directory / "codex.exe"
            if _is_executable(candidate):
                return str(candidate)
    return None


def _native_windows_binary(path):
    if not path:
        return None
    try:
        if _is_executable(path):
            return str(path)
        return _windows_npm_binary(path)
    except (OSError, ValueError, RuntimeError):
        return None


def _windows_path_binary(command):
    binary = _native_windows_binary(shutil.which(command))
    if binary:
        return binary
    # Older Python versions only try PATHEXT suffixes, which normally excludes
    # .ps1. Inspect the known filenames directly without invoking PowerShell.
    suffix = Path(command).suffix.lower()
    names = (command,) if suffix else tuple(command + extension for extension in (".exe", ".cmd", ".bat", ".ps1"))
    for directory in os.get_exec_path():
        for name in names:
            binary = _native_windows_binary(Path(directory) / name)
            if binary:
                return binary
    return None


def _recent_matches(directory, pattern):
    """Inspect known install layouts, tolerating inaccessible Store folders."""
    try:
        return sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    except (OSError, ValueError):
        return []


def _windows_codex_candidates():
    local = _xdg_directory("LOCALAPPDATA", "AppData/Local")
    # The desktop app keeps native CLI versions here, including Store installs.
    yield from _recent_matches(local / "OpenAI" / "Codex" / "bin", "*/codex.exe")
    for root in (local / "Programs" / "Codex", local / "OpenAI" / "Codex"):
        yield root / "resources" / "codex.exe"
        yield root / "app" / "resources" / "codex.exe"
    program_files = []
    for variable in ("ProgramW6432", "ProgramFiles"):
        value = os.environ.get(variable)
        if value and Path(value).is_absolute() and Path(value) not in program_files:
            program_files.append(Path(value))
    if not program_files:
        program_files.append(Path(os.environ.get("SystemDrive", "C:") + "\\Program Files"))
    for directory in program_files:
        for package in _recent_matches(directory / "WindowsApps", "OpenAI.Codex_*"):
            yield package / "app" / "resources" / "codex.exe"
            yield package / "resources" / "codex.exe"


def _configured_binary(value):
    if not value:
        return None
    try:
        if "/" in value or "\\" in value or value.startswith("~"):
            path = str(Path(value).expanduser())
            if sys.platform == "win32":
                return _native_windows_binary(path)
            return path if _is_executable(path) else None
        if sys.platform == "win32":
            return _windows_path_binary(value)
        return shutil.which(value)
    except (OSError, ValueError, RuntimeError):
        return None


def resolve_codex_binary() -> str:
    """Find Codex without reading credentials or falling back from bad overrides.

    CODEX_BIN takes precedence over the older CODEX_CLI_PATH alias. Each can
    name an executable path or a command found on PATH. Windows npm wrappers
    resolve to the bundled native executable, so callers never need shell=True.
    Errors deliberately omit the configured path and other environment values.
    """
    for variable in ("CODEX_BIN", "CODEX_CLI_PATH"):
        if variable in os.environ:
            binary = _configured_binary(os.environ[variable])
            if binary:
                return binary
            raise RuntimeError(
                f"{variable} 配置无效，请设为可执行的 Codex 路径或命令名。"
            )
    if sys.platform == "win32":
        binary = _windows_path_binary("codex")
        if binary:
            return binary
        for candidate in _windows_codex_candidates():
            if _is_executable(candidate):
                return str(candidate)
    else:
        binary = shutil.which("codex")
        if binary:
            return binary
    if sys.platform.startswith("linux"):
        for candidate in _LINUX_CODEX_PATHS:
            if _is_executable(candidate):
                return candidate
    raise RuntimeError(
        "未找到 Codex。请安装并登录 Codex，将 codex 加入 PATH，"
        "或用 CODEX_BIN 指定可执行文件。"
    )
