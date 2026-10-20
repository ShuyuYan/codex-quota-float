#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build and offline-test a one-file Windows x64 application and release ZIP."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "windows"
sys.path.insert(0, str(ROOT))
from release_source import APP_VERSION, build_release, verify_release, verify_linux_baseline

NAME = f"CodexQuotaFloat-{APP_VERSION}-windows-x64"
PINNED = {"PyQt5": "5.15.11", "PyQt5-Qt5": "5.15.2", "PyQt5-sip": "12.20.0", "PyInstaller": "6.22.3"}


def write_checksum(path):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_bytes(f"{digest}  {path.name}\n".encode("utf-8"))


def verify_checksum(path):
    path = Path(path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name
    if path.with_suffix(path.suffix + ".sha256").read_text(encoding="utf-8").strip() != expected:
        raise ValueError(f"SHA-256 校验失败：{path.name}")


def pe_identity(path):
    """Read machine and subsystem without loading or executing the EXE."""
    with Path(path).open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("不是有效的 Windows EXE")
        stream.seek(0x3c)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError("缺失 PE 文件头")
        machine = struct.unpack("<H", stream.read(2))[0]
        stream.seek(offset + 24 + 68)
        subsystem = struct.unpack("<H", stream.read(2))[0]
    return machine, subsystem


def collect_notices(destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", destination / "Project-GPL-3.0.txt")
    shutil.copy2(ROOT / "LICENSE", destination / "PyQt5-GPL-3.0.txt")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("当前 Python 环境缺少 LICENSE.txt，拒绝生成不完整的发布包")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    for package, keyword, filename in (
        ("PyQt5-Qt5", "LICENSE", "Qt-LGPL-3.0.txt"),
        ("PyQt5-sip", "LICENSE", "PyQt5-sip-BSD-2-Clause.txt"),
        ("PyInstaller", "COPYING.txt", "PyInstaller-COPYING.txt"),
    ):
        distribution = metadata.distribution(package)
        files = [entry for entry in distribution.files or () if Path(str(entry)).name == keyword]
        if not files:
            raise ValueError(f"缺少依赖许可证：{package}")
        shutil.copy2(distribution.locate_file(files[0]), destination / filename)


def wait_for_process_exit(pid):
    """Wait for our smoke-test app and its one-file extraction bootloader."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # the process has already exited
            return
        raise OSError("无法检查 EXE 测试进程的退出状态")
    try:
        if kernel.WaitForSingleObject(handle, 15000) != 0:
            raise ValueError("EXE 测试进程未正常退出")
    finally:
        kernel.CloseHandle(handle)


def smoke_test(executable):
    """Launch the real bundled GUI offline, without Python paths or accounts."""
    with tempfile.TemporaryDirectory(prefix="quota-exe-") as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHON", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "CODEX_BIN", "CODEX_CLI_PATH"):
            environment.pop(key, None)
        environment.update({"PATH": str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"),
                            "APPDATA": str(directory / "Roaming"), "LOCALAPPDATA": str(directory / "Local"),
                            "USERPROFILE": str(directory), "QT_QPA_PLATFORM": "offscreen",
                            "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        def run(*arguments):
            subprocess.run([str(executable), *map(str, arguments)], env=environment, cwd=directory,
                           check=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        preview = directory / "preview.png"
        run("--render", preview)
        if not preview.is_file() or preview.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("EXE 离线预览渲染失败")
        status = directory / "status.json"
        run("--status", "--output", status)
        if json.loads(status.read_text()) != {"running": False}:
            raise ValueError("EXE 离线状态检查失败")
        run("--install-shortcut", "--dry-run")
        lifecycle = directory / "lifecycle.json"
        run("--smoke-test", lifecycle)
        expected = {"version": APP_VERSION, "frozen": True, "demo": True, "closed": True}
        if any(json.loads(lifecycle.read_text()).get(key) != value for key, value in expected.items()):
            raise ValueError("EXE 启动、事件循环或退出检查失败")
        background = directory / "background.json"
        run("--background", "--smoke-test", background)
        deadline = time.monotonic() + 60
        while not background.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not background.is_file():
            raise ValueError("EXE 独立后台进程检查失败")
        result = json.loads(background.read_text())
        if any(result.get(key) != value for key, value in expected.items()):
            raise ValueError("EXE 独立后台进程检查失败")
        wait_for_process_exit(result["pid"])
        wait_for_process_exit(result["parent_pid"])
        # Exercise frozen external-program IPC against a local fake server.
        # The EXE itself has already run above with no Python installation on PATH.
        (directory / "app-server").write_text('''import json, sys
json.loads(sys.stdin.readline())
print('{"id":1,"result":{}}', flush=True)
json.loads(sys.stdin.readline())
json.loads(sys.stdin.readline())
print('{"id":2,"result":{"rateLimits":{"primary":{"usedPercent":25,"windowDurationMins":300}}}}', flush=True)
''', encoding="utf-8")
        environment["CODEX_BIN"] = getattr(sys, "_base_executable", sys.executable)
        quota = directory / "fake-quota.json"
        run("--check", "--output", quota)
        if json.loads(quota.read_text())["five_hour"]["remaining"] != 75:
            raise ValueError("EXE 本地模拟额度通信失败")


def verify_artifacts(destination):
    destination = Path(destination).resolve()
    executable = destination / (NAME + ".exe")
    portable = destination / (NAME + ".zip")
    for path in (executable, portable):
        verify_checksum(path)
    if pe_identity(executable) != (0x8664, 2):
        raise ValueError("EXE 必须是 Windows x64 GUI 程序")
    source = destination / f"codex-quota-float-{APP_VERSION}.zip"
    verify_release(source)
    from PyInstaller.archive.readers import CArchiveReader
    bundle = CArchiveReader(str(executable))
    bundled_files = {name.replace("\\", "/"): name for name in bundle.toc}
    source_name = "source/" + source.name
    if source_name not in bundled_files or bundle.extract(bundled_files[source_name]) != source.read_bytes():
        raise ValueError("独立 EXE 未包含当前对应源码")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "DEPENDENCY_SOURCES.md", "licenses/Qt-LGPL-3.0.txt"):
        if name not in bundled_files:
            raise ValueError(f"独立 EXE 缺少许可文件：{name}")
    with zipfile.ZipFile(portable) as zipped:
        prefix = NAME + "/"
        if zipped.read(prefix + executable.name) != executable.read_bytes():
            raise ValueError("便携包内 EXE 与独立下载文件不一致")
        if zipped.read(prefix + "source/" + source.name) != source.read_bytes():
            raise ValueError("便携包未包含对应源码")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "DEPENDENCY_SOURCES.md", "BUILD_INFO.json", "licenses/Qt-LGPL-3.0.txt"):
            zipped.getinfo(prefix + name)
    smoke_test(executable)
    return executable


def build(destination):
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("请使用 Windows x64 的 Python 构建 EXE")
    for name, version in PINNED.items():
        if metadata.version(name) != version:
            raise ValueError(f"构建依赖不匹配：{name}，请安装 windows/requirements-build.txt")
    verify_linux_baseline()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "exe"
    work.mkdir(parents=True, exist_ok=True)
    notices = work / "licenses"
    collect_notices(notices)
    source = build_release(destination=destination, refresh_checksums=True)
    info = {"application": APP_VERSION, "architecture": "windows-x64", "python": platform.python_version(),
            "dependencies": {name: metadata.version(name) for name in PINNED},
            "python_source": f"https://www.python.org/ftp/python/{platform.python_version()}/Python-{platform.python_version()}.tgz"}
    (work / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    version = tuple(map(int, APP_VERSION.split("."))) + (0,)
    version_file = work / "version_info.txt"
    version_file.write_text(f"VSVersionInfo(ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName', 'Codex Quota Float Community'), StringStruct('FileDescription', 'Codex Quota Float'), StringStruct('FileVersion', '{APP_VERSION}'), StringStruct('ProductVersion', '{APP_VERSION}'), StringStruct('ProductName', 'Codex Quota Float')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])", encoding="utf-8")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--noupx",
               "--name", NAME, "--distpath", str(destination), "--workpath", str(work / "work"), "--specpath", str(work),
               "--icon", str(WINDOWS / "quota-icon.ico"), "--version-file", str(version_file),
               "--hidden-import", "PyQt5.QtSvg", "--hidden-import", "windows_shortcut"]
    for path, target in ((WINDOWS / "quota-icon.svg", "."), (WINDOWS / "quota-icon.ico", "."),
                         (ROOT / "LICENSE", "."), (ROOT / "THIRD_PARTY_NOTICES.md", "."),
                         (WINDOWS / "DEPENDENCY_SOURCES.md", "."), (work / "BUILD_INFO.json", "."),
                         (notices, "licenses"), (source, "source")):
        command.extend(["--add-data", str(path) + os.pathsep + target])
    command.append(str(WINDOWS / "app.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    executable = destination / (NAME + ".exe")
    write_checksum(executable)
    portable = destination / (NAME + ".zip")
    payload = {executable.name: executable.read_bytes(), "LICENSE": (ROOT / "LICENSE").read_bytes(),
               "THIRD_PARTY_NOTICES.md": (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes(),
               "DEPENDENCY_SOURCES.md": (WINDOWS / "DEPENDENCY_SOURCES.md").read_bytes(),
               "BUILD_INFO.json": (work / "BUILD_INFO.json").read_bytes(),
               "source/" + source.name: source.read_bytes(),
               "source/" + source.name + ".sha256": source.with_suffix(".zip.sha256").read_bytes(),
               "Windows使用说明.txt": ("安装并登录 Codex 后，双击 " + executable.name + " 即可。\n无需安装 Python 或运行命令。\n拖动调整位置；右键可刷新、创建桌面快捷方式或退出。\n源码与许可证见本目录的 source/、licenses/ 和 DEPENDENCY_SOURCES.md。\n").encode("utf-8-sig")}
    payload.update({"licenses/" + path.name: path.read_bytes() for path in notices.iterdir() if path.is_file()})
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, data in sorted(payload.items()):
            zipped.writestr(NAME + "/" + name, data)
    write_checksum(portable)
    shutil.copy2(WINDOWS / "DEPENDENCY_SOURCES.md", destination / "DEPENDENCY_SOURCES.md")
    return verify_artifacts(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description="构建无需 Python 的 Windows x64 单文件 EXE。")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--verify", action="store_true", help="只校验已有发布文件，并离线测试真实 EXE")
    options = parser.parse_args(argv)
    try:
        executable = verify_artifacts(options.output) if options.verify else build(options.output)
        print(f"Windows EXE 验证通过：{executable}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, metadata.PackageNotFoundError) as error:
        print(f"Windows EXE 处理失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
