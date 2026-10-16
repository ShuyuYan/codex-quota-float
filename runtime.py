# SPDX-License-Identifier: GPL-3.0-only
"""Portable runtime paths and Codex discovery for the Linux desktop app.

Importing this module or asking for a path never creates files or directories.
"""

import os
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
APP_VERSION = "0.2.0"
_APP_DIRECTORY = "codex-quota-float"
_LINUX_CODEX_PATHS = (
    "/usr/lib/chatgpt/resources/codex",
    "/opt/chatgpt/resources/codex",
    "/usr/lib/codex/resources/codex",
)


def _xdg_directory(variable, default):
    value = os.environ.get(variable)
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / default


def settings_path() -> Path:
    """Return the user settings path without accessing or creating the file."""
    return _xdg_directory("XDG_CONFIG_HOME", ".config") / _APP_DIRECTORY / "settings.json"


def log_path() -> Path:
    """Return the background log path without accessing or creating the file."""
    return _xdg_directory("XDG_STATE_HOME", ".local/state") / _APP_DIRECTORY / "app.log"


def _is_executable(path):
    try:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    except (OSError, ValueError):
        return False


def _configured_binary(value):
    if not value:
        return None
    try:
        if os.sep in value or value.startswith("~"):
            path = str(Path(value).expanduser())
            return path if _is_executable(path) else None
        return shutil.which(value)
    except (OSError, ValueError, RuntimeError):
        return None


def resolve_codex_binary() -> str:
    """Find Codex without reading credentials or falling back from bad overrides.

    CODEX_BIN takes precedence over the older CODEX_CLI_PATH alias. Each can
    name an executable path or a command found on PATH. Errors deliberately
    omit the configured path and other environment values.
    """
    for variable in ("CODEX_BIN", "CODEX_CLI_PATH"):
        if variable in os.environ:
            binary = _configured_binary(os.environ[variable])
            if binary:
                return binary
            raise RuntimeError(
                f"{variable} 配置无效，请设为可执行的 Codex 路径或命令名。"
            )
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
