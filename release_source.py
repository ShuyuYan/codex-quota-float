#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build a source-only archive from an explicit, privacy-checked file list."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent
APP_VERSION = "1.1.1"
LINUX_SOURCE_COMMIT = "f8548e61435ad884d88f672a7999caacb06b21bb"
LINUX_FILES = (
    "app.py", "runtime.py", "quota_reader.py", "run.sh", "install_shortcut.py",
    "test_app.py", "test_runtime.py", "test_quota_reader.py", "test_install_shortcut.py",
    "quota-icon.svg", "preview-widget.png",
)
WINDOWS_FILES = (
    "app.py", "runtime.py", "quota_reader.py", "run.cmd", "run.ps1",
    "install_shortcut.py", "windows_shortcut.py", "quota-icon.svg", "quota-icon.ico", "preview-widget.png",
    "test_app.py", "test_runtime.py", "test_quota_reader.py", "test_windows_shortcut.py",
    "build_exe.py", "requirements-build.txt", "DEPENDENCY_SOURCES.md",
)
PUBLIC_FILES = (
    ".gitattributes", ".gitignore", ".github/workflows/tests.yml",
    "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md",
    "CHANGELOG.md", "RELEASE.md", "RELEASE_NOTES.md",
    "requirements.txt", "release_source.py", "test_release_source.py", "test_build_exe.py", "LINUX_BASELINE.json",
    *("linux/" + name for name in LINUX_FILES),
    *("windows/" + name for name in WINDOWS_FILES),
)
_HOME_PATH = re.compile(r"/(?:home|Users)/([^/\s\"'<>]+)(?:/|$)")
_WINDOWS_HOME_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'<>]+)(?:[\\/]|$)", re.IGNORECASE)
_EXAMPLE_USERS = {"alice", "bob", "example", "user", "tester"}
_TOKEN = re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})")


def validate_public_file(name, data):
    """Catch personal home paths and common credential formats in public text."""
    if name.endswith((".png", ".ico")):
        return
    text = data.decode("utf-8")
    for match in (*_HOME_PATH.finditer(text), *_WINDOWS_HOME_PATH.finditer(text)):
        if match.group(1).lower() not in _EXAMPLE_USERS:
            raise ValueError(f"发现不应公开的个人目录路径：{name}")
    if _TOKEN.search(text):
        raise ValueError(f"发现疑似凭据：{name}")
    if any(str(Path.home()).lower() + separator in text.lower() for separator in ("/", "\\")):
        raise ValueError(f"发现本机主目录路径：{name}")


def canonical_file_bytes(name, data):
    """Make release contents identical across Linux and Windows checkouts."""
    if name.endswith((".png", ".ico")):
        return data
    normalized = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if name.endswith((".cmd", ".ps1")):
        normalized = normalized.replace("\n", "\r\n")
    return normalized.encode("utf-8")


def _check_linux_payload(payload):
    baseline = json.loads(payload["LINUX_BASELINE.json"])
    if (not isinstance(baseline, dict) or baseline.get("commit") != LINUX_SOURCE_COMMIT
            or not isinstance(baseline.get("files"), dict)
            or set(baseline["files"]) != set(LINUX_FILES)):
        raise ValueError("Linux 原版文件清单无效。")
    for name, digest in baseline["files"].items():
        if hashlib.sha256(payload["linux/" + name]).hexdigest() != digest:
            raise ValueError(f"Linux 原版文件已改变：{name}")
    return len(LINUX_FILES)


def verify_linux_baseline(source=PROJECT_ROOT):
    source = Path(source)
    payload = {"LINUX_BASELINE.json": (source / "LINUX_BASELINE.json").read_bytes()}
    payload.update({"linux/" + name: (source / "linux" / name).read_bytes() for name in LINUX_FILES})
    return _check_linux_payload(payload)


def build_release(source=PROJECT_ROOT, destination=None, refresh_checksums=False):
    source = Path(source)
    destination = Path(destination) if destination is not None else source / "release"
    payload = {}
    for name in sorted(PUBLIC_FILES):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"公开文件缺失或不是普通文件：{name}")
        data = canonical_file_bytes(name, path.read_bytes())
        validate_public_file(name, data)
        payload[name] = data
    verify_linux_baseline(source)
    _check_linux_payload(payload)
    payload["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payload.items()
    ).encode()
    if refresh_checksums:
        (source / "SHA256SUMS").write_bytes(payload["SHA256SUMS"])
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"codex-quota-float-{APP_VERSION}"
    archive = destination / f"{prefix}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, data in payload.items():
            info = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if name == "linux/run.sh" else 0o100644) << 16
            zipped.writestr(info, data, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_bytes(f"{digest}  {archive.name}\n".encode("utf-8"))
    return archive


def verify_release(archive):
    """Verify archive and per-file hashes without extracting or running code."""
    archive = Path(archive)
    checksum = archive.with_suffix(".zip.sha256").read_text(encoding="utf-8").strip()
    digest, separator, filename = checksum.partition("  ")
    if (not separator or filename != archive.name or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or hashlib.sha256(archive.read_bytes()).hexdigest() != digest):
        raise ValueError("源码 ZIP 的 SHA-256 校验失败。")
    prefix = f"codex-quota-float-{APP_VERSION}/"
    expected = {prefix + name for name in PUBLIC_FILES} | {prefix + "SHA256SUMS"}
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("源码 ZIP 的版本或文件清单不匹配。")
        manifest = zipped.read(prefix + "SHA256SUMS").decode("utf-8")
        checked = set()
        for line in manifest.splitlines():
            digest, separator, name = line.partition("  ")
            if (not separator or name not in PUBLIC_FILES or name in checked
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError("包内 SHA256SUMS 清单无效。")
            data = zipped.read(prefix + name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"包内文件校验失败：{name}")
            if canonical_file_bytes(name, data) != data:
                raise ValueError(f"包内文件换行格式不正确：{name}")
            validate_public_file(name, data)
            checked.add(name)
        if checked != set(PUBLIC_FILES):
            raise ValueError("包内 SHA256SUMS 清单不完整。")
        _check_linux_payload({name: zipped.read(prefix + name) for name in PUBLIC_FILES})
    return len(checked)


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成不包含本机数据的公开源码 ZIP。")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--output", type=Path, help="输出目录，默认为项目 release/")
    action.add_argument("--verify", type=Path, help="校验已生成的 ZIP、外部及包内 SHA-256，不解压或运行代码")
    parser.add_argument("--refresh-checksums", action="store_true", help="生成源码包，同时更新项目根目录 SHA256SUMS")
    options = parser.parse_args(argv)
    if options.verify and options.refresh_checksums:
        parser.error("--verify 与 --refresh-checksums 不能同时使用")
    try:
        if options.verify:
            count = verify_release(options.verify)
            print(f"校验通过：{options.verify.name}（{count} 个公开文件）")
        else:
            archive = build_release(destination=options.output, refresh_checksums=options.refresh_checksums)
            print(f"已生成：{archive.name}（{len(PUBLIC_FILES)} 个公开文件，不含运行数据）")
        return 0
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile) as error:
        print(f"发布包处理失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
