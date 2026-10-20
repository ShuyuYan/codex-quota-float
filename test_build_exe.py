# SPDX-License-Identifier: GPL-3.0-only
"""Build artifact validation without requiring Windows or PyInstaller."""
from pathlib import Path
import struct
import tempfile
import unittest

from windows import build_exe


class ExecutableReleaseTests(unittest.TestCase):
    def test_changed_executable_fails_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.exe"
            path.write_bytes(b"example executable")
            build_exe.write_checksum(path)
            build_exe.verify_checksum(path)
            path.write_bytes(b"changed executable")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                build_exe.verify_checksum(path)

    def test_pe_header_reports_windows_x64_gui_subsystem(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = bytearray(256)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 0x3c, 128)
            data[128:132] = b"PE\0\0"
            struct.pack_into("<H", data, 132, 0x8664)
            struct.pack_into("<H", data, 128 + 24 + 68, 2)
            path = Path(temporary) / "app.exe"
            path.write_bytes(data)
            self.assertEqual(build_exe.pe_identity(path), (0x8664, 2))


if __name__ == "__main__":
    unittest.main()
