#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build a source-only archive from an explicit, privacy-checked file list."""
import argparse
import hashlib
from pathlib import Path
import re
import zipfile

from runtime import APP_VERSION, PROJECT_ROOT

PUBLIC_FILES = (
    ".gitattributes", ".gitignore", ".github/workflows/tests.yml",
    "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md",
    "requirements.txt", "app.py", "runtime.py", "quota_reader.py",
    "run.sh", "install_shortcut.py", "release_source.py",
    "test_app.py", "test_runtime.py", "test_quota_reader.py",
    "test_install_shortcut.py", "test_release_source.py",
    "quota-icon.svg", "preview-widget.png",
)
_HOME_PATH = re.compile(r"/(?:home|Users)/([^/\s\"'<>]+)(?:/|$)")
_EXAMPLE_USERS = {"alice", "bob", "example", "user", "tester"}
_TOKEN = re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})")


def validate_public_file(name, data):
    """Catch personal home paths and common credential formats in public text."""
    if name.endswith(".png"):
        return
    text = data.decode("utf-8")
    for match in _HOME_PATH.finditer(text):
        if match.group(1) not in _EXAMPLE_USERS:
            raise ValueError(f"发现不应公开的个人目录路径：{name}")
    if _TOKEN.search(text):
        raise ValueError(f"发现疑似凭据：{name}")
    if str(Path.home()) + "/" in text:
        raise ValueError(f"发现本机主目录路径：{name}")


def build_release(source=PROJECT_ROOT, destination=None):
    source = Path(source)
    destination = Path(destination) if destination is not None else source / "release"
    payload = {}
    for name in sorted(PUBLIC_FILES):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"公开文件缺失或不是普通文件：{name}")
        data = path.read_bytes()
        validate_public_file(name, data)
        payload[name] = data
    payload["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payload.items()
    ).encode()
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"codex-quota-float-{APP_VERSION}"
    archive = destination / f"{prefix}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, data in payload.items():
            info = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if name == "run.sh" else 0o100644) << 16
            zipped.writestr(info, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def main():
    parser = argparse.ArgumentParser(description="生成不包含本机数据的公开源码 ZIP。")
    parser.add_argument("--output", type=Path, help="输出目录，默认为项目 release/")
    options = parser.parse_args()
    archive = build_release(destination=options.output)
    print(f"已生成：{archive.name}（{len(PUBLIC_FILES)} 个公开文件，不含运行数据）")


if __name__ == "__main__":
    main()
