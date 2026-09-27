# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic tests only: no capture here came from Apple firmware."""

import ctypes
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.inspect_bootargs import SIZE, decode_bootargs


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "inspect_bootargs.py"


class BootVideo(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in
                ("v_baseAddr", "v_display", "v_rowBytes", "v_width", "v_height", "v_depth")]


class BootArgs(ctypes.Structure):
    """Independent restatement of the pinned XNU struct with natural LP64 alignment."""
    _fields_ = [
        ("Revision", ctypes.c_uint16), ("Version", ctypes.c_uint16),
        ("virtBase", ctypes.c_uint64), ("physBase", ctypes.c_uint64),
        ("memSize", ctypes.c_uint64), ("topOfKernelData", ctypes.c_uint64),
        ("Video", BootVideo), ("machineType", ctypes.c_uint32),
        ("deviceTreeP", ctypes.c_uint64), ("deviceTreeLength", ctypes.c_uint32),
        ("CommandLine", ctypes.c_char * 608),
        ("bootFlags", ctypes.c_uint64), ("memSizeActual", ctypes.c_uint64),
    ]


def capture(**fields):
    """Arbitrary test values; none are observations of any Mac."""
    args = BootArgs(Revision=2, Version=2, virtBase=0xFFFFFE0007004000, physBase=0x800000000,
                    memSize=0x200000000, topOfKernelData=0x812340000, machineType=0,
                    deviceTreeP=0xFFFFFE0010000000, deviceTreeLength=0x40000,
                    CommandLine=b"serial=3 debug=0x8", bootFlags=0, memSizeActual=0x200000000)
    args.Video = BootVideo(0x900000000, 1, 2560 * 4 + 64, 2560, 1600, 0x00020118)
    for name, value in fields.items():
        target = args.Video if name.startswith("v_") else args
        setattr(target, name, value)
    return bytes(args)


class LayoutTests(unittest.TestCase):
    def test_offsets_match_research_table(self):
        # Values from docs/APPLE_BOOT.md, derived from the pinned header.
        expected = {"Video": 0x28, "machineType": 0x58, "deviceTreeP": 0x60,
                    "deviceTreeLength": 0x68, "CommandLine": 0x6C,
                    "bootFlags": 0x2D0, "memSizeActual": 0x2D8}
        for name, offset in expected.items():
            self.assertEqual(getattr(BootArgs, name).offset, offset, name)
        self.assertEqual(ctypes.sizeof(BootArgs), SIZE)


class DecodeTests(unittest.TestCase):
    def test_decodes_all_fields(self):
        r = decode_bootargs(capture())
        self.assertEqual((r["revision"], r["version"]), (2, 2))
        self.assertEqual(r["phys_base"], "0x800000000")
        self.assertEqual(r["mem_size"], "0x200000000")
        self.assertEqual(r["device_tree"], "0xfffffe0010000000")
        self.assertEqual(r["device_tree_length"], 0x40000)
        self.assertEqual(r["command_line"], "serial=3 debug=0x8")
        self.assertEqual(r["boot_flags"], "0x0")
        self.assertIs(r["dark_boot"], False)
        self.assertEqual(r["warnings"], [])
        self.assertIn("Untrusted evidence", r["evidence_note"])

    def test_video_depth_fields(self):
        v = decode_bootargs(capture())["video"]
        self.assertEqual((v["width"], v["height"], v["row_bytes"]), (2560, 1600, 10304))
        self.assertEqual((v["depth_bits"], v["rotate"], v["scale"]), (24, 1, 2))
        # A 24-bit depth is not a console format.
        self.assertFalse(v["matches_console_geometry"])
        self.assertIsNone(v["console_format_candidate"])
        for depth, name in ((32, "x8r8g8b8"), (30, "x2r10g10b10")):
            v = decode_bootargs(capture(v_depth=depth))["video"]
            self.assertTrue(v["matches_console_geometry"])
            self.assertEqual(v["console_format_candidate"], name)

    def test_dark_boot_flag(self):
        self.assertTrue(decode_bootargs(capture(bootFlags=1))["dark_boot"])

    def test_revision_1_skips_trailing_fields(self):
        r = decode_bootargs(capture(Revision=1, bootFlags=0xFFFF))
        self.assertIsNone(r["boot_flags"])
        self.assertIsNone(r["mem_size_actual"])
        self.assertTrue(any("Revision 1" in w for w in r["warnings"]))

    def test_consistency_warnings(self):
        r = decode_bootargs(capture(v_rowBytes=100, deviceTreeLength=0))
        self.assertEqual(len(r["warnings"]), 2, r["warnings"])

    def test_unterminated_command_line(self):
        data = bytearray(capture())
        data[0x6C:0x6C + 608] = b"A" * 608
        r = decode_bootargs(bytes(data))
        self.assertEqual(len(r["command_line"]), 608)
        self.assertTrue(any("NUL" in w for w in r["warnings"]))

    def test_non_ascii_command_line_is_escaped(self):
        data = bytearray(capture())
        data[0x6C:0x6F] = b"\xff\x00\x00"
        self.assertEqual(decode_bootargs(bytes(data))["command_line"], "\\xff")

    def test_rejects_wrong_size_and_unknown_layouts(self):
        for data in (capture()[:-1], capture() + b"\0"):
            with self.assertRaises(ValueError):
                decode_bootargs(data)
        for fields in ({"Revision": 3}, {"Revision": 0}, {"Version": 7}):
            with self.subTest(fields), self.assertRaises(ValueError):
                decode_bootargs(capture(**fields))


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, CLI, *map(str, args)], capture_output=True, text=True)

    def test_offset_into_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "dump.bin")
            path.write_bytes(b"\xee" * 0x40 + capture() + b"\xee" * 16)
            result = self.run_cli(path, "--offset", "0x40")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["video"]["width"], 2560)

    def test_truncated_file_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "short.bin")
            path.write_bytes(capture()[:100])
            result = self.run_cli(path)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Expected exactly 736 bytes", result.stderr)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
