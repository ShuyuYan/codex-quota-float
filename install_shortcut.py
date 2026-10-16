#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Install per-user Linux launchers without a shell or fixed-path template.

Desktop Entry strings and Exec arguments have separate escaping layers. See
local desktop-file-validate(1), xdg-desktop-icon(1), File::DesktopEntry(3pm).
Installation never starts the application.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent
LAUNCHER_NAME = "codex-quota-float.desktop"
APP_NAME = "Codex 额度悬浮球"
_ESCAPES = {"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_UNESCAPES = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t", "s": " "}


class InstallError(RuntimeError):
    """A launcher could not be installed safely."""


def desktop_string(value):
    """Escape a Desktop Entry string value, including boundary whitespace."""
    value = str(value)
    if "\x00" in value:
        raise InstallError("路径或配置中不能包含 NUL 字符。")
    escaped = "".join(_ESCAPES.get(char, char) for char in value)
    leading = len(escaped) - len(escaped.lstrip(" "))
    trailing = len(escaped) - len(escaped.rstrip(" "))
    if leading == len(escaped):
        return "\\s" * leading
    end = len(escaped) - trailing if trailing else len(escaped)
    return "\\s" * leading + escaped[leading:end] + "\\s" * trailing


def exec_argument(value):
    """Quote an argv item, then apply Desktop Entry string escaping."""
    value = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InstallError("启动路径或配置中不能包含控制字符。")
    quoted = "".join("\\" + char if char in '\\"`$' else char for char in value)
    return desktop_string('"' + quoted.replace("%", "%%") + '"')


def system_tool(name):
    """Prefer OS tools over similarly named virtual-environment programs."""
    system = Path("/usr/bin") / name
    if system.is_file() and os.access(system, os.X_OK):
        return str(system)
    return shutil.which(name)


def launcher_content(project_root=None, python_executable=None):
    root = Path(project_root if project_root is not None else PROJECT_ROOT).absolute()
    python = str(python_executable if python_executable is not None else sys.executable)
    if not Path(python).is_absolute():
        raise InstallError("请使用绝对路径的 Python 解释器安装快捷方式。")
    arguments = [python, str(root / "app.py"), "--background"]
    overrides = [f"{key}={os.environ[key]}" for key in ("CODEX_BIN", "CODEX_CLI_PATH") if key in os.environ]
    if overrides:
        env_tool = system_tool("env")
        if not env_tool:
            raise InstallError("未找到 env，无法保留 CODEX_BIN / CODEX_CLI_PATH；请先安装系统 env 工具。")
        arguments = [env_tool, *overrides, *arguments]
    return "\n".join([
        "[Desktop Entry]", "Version=1.0", "Type=Application",
        f"Name={desktop_string(APP_NAME)}", "GenericName=额度监视器",
        "Comment=显示 5 小时与 Week 额度余量",
        "Exec=" + " ".join(exec_argument(argument) for argument in arguments),
        f"Path={desktop_string(root)}", f"Icon={desktop_string(root / 'quota-icon.svg')}",
        "X-CodexQuotaFloat=true",
        "Terminal=false", "StartupNotify=false", "Categories=Utility;",
        "Keywords=Codex;quota;额度;悬浮球;", "",
    ])


def applications_directory():
    configured = os.environ.get("XDG_DATA_HOME", "")
    base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".local/share"
    return base / "applications"


def desktop_directory():
    """Use an existing configured desktop; never create one."""
    xdg = system_tool("xdg-user-dir")
    if not xdg:
        return None, "未找到 xdg-user-dir；只安装应用菜单快捷方式。"
    try:
        result = subprocess.run([xdg, "DESKTOP"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, "无法读取桌面目录；只安装应用菜单快捷方式。"
    value = result.stdout.rstrip("\r\n")
    desktop = Path(value) if value else None
    if result.returncode or desktop is None or not desktop.is_absolute() or not desktop.is_dir():
        return None, "桌面目录不存在或未配置；只安装应用菜单快捷方式。"
    if desktop == Path.home():
        return None, "桌面目录指向主目录，视为未启用桌面；只安装应用菜单快捷方式。"
    return desktop, None


def _unescape_string(value):
    output, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 1
            if index == len(value) or value[index] not in _UNESCAPES:
                raise ValueError("Invalid Desktop Entry escape")
            char = _UNESCAPES[value[index]]
        output.append(char)
        index += 1
    return "".join(output)


def _exec_arguments(value):
    """Read limited argv syntax for safe ownership identification, not execution."""
    arguments, index = [], 0
    while index < len(value):
        if value[index].isspace():
            index += 1
            continue
        quoted = value[index] == '"'
        index += int(quoted)
        argument = []
        while index < len(value):
            char = value[index]
            if quoted and char == '"':
                index += 1
                break
            if not quoted and char.isspace():
                break
            if quoted and char == "\\":
                index += 1
                if index == len(value) or value[index] not in '\\"`$':
                    raise ValueError("Invalid Exec escape")
                char = value[index]
            elif not quoted and char in '\\"\'`$':
                raise ValueError("Unexpected unquoted character")
            argument.append(char)
            index += 1
        else:
            if quoted:
                raise ValueError("Unterminated argument")
        if index < len(value) and not value[index].isspace():
            raise ValueError("Unexpected argument suffix")
        arguments.append("".join(argument).replace("%%", "%"))
    return arguments


def is_project_launcher(content):
    """Require both the known name and a real project launcher argv item."""
    try:
        fields, active = {}, False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("["):
                active = line == "[Desktop Entry]"
            elif active and line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                if key in fields:
                    return False
                fields[key] = _unescape_string(value.strip())
        if fields.get("Type") != "Application" or fields.get("Name") != APP_NAME:
            return False
        arguments = _exec_arguments(fields.get("Exec", ""))
        # Newly generated launchers remain recognizable when a release ZIP or
        # the user gives the checkout a different directory name.
        root = Path(fields.get("Path", ""))
        if (fields.get("X-CodexQuotaFloat") == "true" and root.is_absolute()
                and str(root / "app.py") in arguments):
            return True
        # The original prototype had no identity marker or quoted argv.
        return any(Path(argument).parts[-2:] in (
            ("codex-quota-float", "app.py"), ("codex-quota-float", "run.sh"),
        ) for argument in arguments)
    except (ValueError, TypeError):
        return False


def _preflight(target, content, force):
    if target.is_symlink():
        raise InstallError(f"拒绝覆盖符号链接：{target}")
    if not target.exists():
        return
    if not target.is_file():
        raise InstallError(f"目标不是普通文件，已保留：{target}")
    previous = target.read_text(encoding="utf-8")
    if previous == content or (force and is_project_launcher(previous)):
        return
    message = "已存在不同内容的快捷方式，已保留"
    if not is_project_launcher(previous):
        message = "目标属于其他应用或无法识别，--force 也不会覆盖"
    raise InstallError(f"{message}：{target}")


def _write_launcher(target, content, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    _preflight(target, content, force)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        target.chmod(0o755)
        print(f"快捷方式已是最新：{target}")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".quota-launcher-", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.chmod(0o755)
        _preflight(target, content, force)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"已创建：{target}")


def _optional_command(arguments):
    try:
        return subprocess.run(arguments, capture_output=True, text=True, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装 Codex 额度悬浮球的 Linux 桌面及应用菜单快捷方式。")
    parser.add_argument("--dry-run", action="store_true", help="仅显示目标路径和内容，不写文件或设置桌面信任")
    parser.add_argument("--menu-only", action="store_true", help="只安装应用菜单快捷方式")
    parser.add_argument("--force", action="store_true", help="允许替换本项目旧快捷方式；不会覆盖其他应用")
    options = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        print("快捷方式安装目前只支持 Linux。", file=sys.stderr)
        return 1
    try:
        content = launcher_content()
        applications = applications_directory()
        desktop, note = (None, None) if options.menu_only else desktop_directory()
        if note:
            print(note)
        targets = list(dict.fromkeys([applications / LAUNCHER_NAME] + ([desktop / LAUNCHER_NAME] if desktop else [])))
        if options.dry_run:
            for target in targets:
                print(f"将生成：{target}")
            print(content, end="")
            return 0
        for target in targets:
            _preflight(target, content, options.force)
        for target in targets:
            _write_launcher(target, content, options.force)
        if desktop:
            gio = system_tool("gio")
            if not gio or not _optional_command([gio, "set", str(desktop / LAUNCHER_NAME), "metadata::trusted", "true"]):
                print("桌面信任标记不可用；首次使用时可能需要右键选择‘允许启动’。应用菜单快捷方式仍可使用。")
        updater = system_tool("update-desktop-database")
        if updater and not _optional_command([updater, str(applications)]):
            print("应用菜单缓存刷新失败；快捷方式已安装，菜单可能稍后显示。")
        print("可在应用菜单中搜索‘Codex 额度悬浮球’。移动项目或 Python 环境后请重新运行安装命令并加 --force。")
        return 0
    except (InstallError, OSError, UnicodeError) as error:
        print(f"安装失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
