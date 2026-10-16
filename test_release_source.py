# SPDX-License-Identifier: GPL-3.0-only
"""Release archives include source only, regardless of local ignored files."""
from pathlib import Path
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
        for content in (private_path, token):
            with self.subTest(content=content), self.assertRaises(ValueError):
                release_source.validate_public_file("README.md", content.encode())

    def test_missing_public_files_stop_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                release_source.build_release(source=temporary, destination=Path(temporary) / "output")


if __name__ == "__main__":
    unittest.main()
