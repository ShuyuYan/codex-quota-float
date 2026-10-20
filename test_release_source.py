# SPDX-License-Identifier: GPL-3.0-only
"""Release archives include source only, regardless of local ignored files."""
from pathlib import Path
import hashlib
import tempfile
import unittest
import zipfile

import release_source


class ReleaseTests(unittest.TestCase):
    def test_release_matches_public_manifest_and_has_no_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = release_source.build_release(destination=temporary)
            with zipfile.ZipFile(archive) as zipped:
                names = [name.split("/", 1)[1] for name in zipped.namelist()]
                self.assertEqual(set(names), set(release_source.PUBLIC_FILES) | {"SHA256SUMS"})
                self.assertFalse({"settings.json", "app.log", "effect-preview.png", "codex-quota-float.desktop"} & set(names))
            original = archive.read_bytes()
            release_source.build_release(destination=temporary)
            self.assertEqual(original, archive.read_bytes())

    def test_generic_personal_paths_and_tokens_are_rejected(self):
        private_path = "/home/" + "private-owner/project"
        token = "ghp_" + "a" * 30
        windows_private_path = "C:\\Users\\" + "private-owner\\project"
        for content in (private_path, windows_private_path, token):
            with self.subTest(content=content), self.assertRaises(ValueError):
                release_source.validate_public_file("README.md", content.encode())

    def test_missing_public_files_stop_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                release_source.build_release(source=temporary, destination=Path(temporary) / "output")

    def test_linux_and_windows_checkouts_produce_identical_verified_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            windows_checkout = root / "windows-checkout"
            for name in release_source.PUBLIC_FILES:
                data = (release_source.PROJECT_ROOT / name).read_bytes()
                if not name.startswith("linux/") and not name.endswith((".png", ".ico")):
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                target = windows_checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            original = release_source.build_release(destination=root / "original")
            alternate = release_source.build_release(windows_checkout, root / "alternate", refresh_checksums=True)
            self.assertEqual(original.read_bytes(), alternate.read_bytes())
            self.assertEqual(release_source.verify_release(alternate), len(release_source.PUBLIC_FILES))
            self.assertNotIn(b"\r", alternate.with_suffix(".zip.sha256").read_bytes())
            with zipfile.ZipFile(alternate) as zipped:
                prefix = f"codex-quota-float-{release_source.APP_VERSION}/"
                self.assertEqual((windows_checkout / "SHA256SUMS").read_bytes(), zipped.read(prefix + "SHA256SUMS"))
                self.assertIn(b"\r\n", zipped.read(prefix + "windows/run.cmd"))
                self.assertNotIn(b"\r", zipped.read(prefix + "linux/run.sh"))
                self.assertEqual((zipped.getinfo(prefix + "linux/run.sh").external_attr >> 16) & 0o777, 0o755)

    def test_linux_program_matches_recorded_original_and_changes_stop_packaging(self):
        self.assertEqual(release_source.verify_linux_baseline(), len(release_source.LINUX_FILES))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in release_source.PUBLIC_FILES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((release_source.PROJECT_ROOT / name).read_bytes())
            linux_app = root / "linux/app.py"
            linux_app.write_bytes(linux_app.read_bytes() + b"\n# changed\n")
            with self.assertRaisesRegex(ValueError, "Linux 原版文件已改变"):
                release_source.build_release(root, root / "output")

    def test_modified_archive_fails_external_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = release_source.build_release(destination=temporary)
            archive.write_bytes(archive.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "ZIP.*校验失败"):
                release_source.verify_release(archive)

    def test_modified_file_fails_inner_checksum_even_with_matching_archive_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = release_source.build_release(destination=temporary)
            with zipfile.ZipFile(archive) as zipped:
                entries = [(entry, zipped.read(entry.filename)) for entry in zipped.infolist()]
            with zipfile.ZipFile(archive, "w") as zipped:
                for entry, data in entries:
                    if entry.filename.endswith("/README.md"):
                        data += b"\nchanged\n"
                    zipped.writestr(entry, data)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_suffix(".zip.sha256").write_bytes(f"{digest}  {archive.name}\n".encode())
            with self.assertRaisesRegex(ValueError, "包内文件校验失败"):
                release_source.verify_release(archive)


if __name__ == "__main__":
    unittest.main()
