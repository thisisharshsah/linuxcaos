# SPDX-License-Identifier: GPL-2.0-or-later
"""Host tests of src/bootargs.c (built by `make host`), cross-checked against the
independent Python decoder. All captures are synthetic."""

import ctypes
import unittest
from pathlib import Path

from tests.test_inspect_bootargs import BootArgs, BootVideo
from tools.inspect_bootargs import decode_bootargs

ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = ROOT / "build/host/libportable.so"
OK, ERR_REVISION, ERR_VERSION, ERR_MEMORY = range(4)
X8R8G8B8, X2R10G10B10 = 0, 1


class CBootArgs(ctypes.Structure):
    _fields_ = [("revision", ctypes.c_uint16), ("version", ctypes.c_uint16)] + [
        (n, ctypes.c_uint64) for n in ("virt_base", "phys_base", "mem_size", "top_of_kdata",
                                       "video_base", "video_display", "video_row_bytes",
                                       "video_width", "video_height", "video_depth")] + [
        ("machine_type", ctypes.c_uint32), ("device_tree", ctypes.c_uint64),
        ("device_tree_length", ctypes.c_uint32), ("boot_flags", ctypes.c_uint64),
        ("depth_bits", ctypes.c_uint32), ("pixel_format", ctypes.c_uint32),
        ("video_ok", ctypes.c_uint32), ("video_in_ram", ctypes.c_uint32)]


def capture(video=(0x9E0000000, 1, 2560 * 4, 2560, 1600, 30), **fields):
    args = BootArgs(Revision=2, Version=2, virtBase=0xFFFFFE0007004000, physBase=0x800000000,
                    memSize=0x1E0000000, topOfKernelData=0x812340000, machineType=7,
                    deviceTreeP=0xFFFFFE0010000000, deviceTreeLength=0x40000,
                    CommandLine=b"x", bootFlags=1, memSizeActual=0x200000000)
    args.Video = BootVideo(*video)
    for name, value in fields.items():
        setattr(args, name, value)
    return bytes(args)


class BootargsCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not LIB_PATH.exists():
            raise unittest.SkipTest("run `make host` first")
        cls.lib = ctypes.CDLL(str(LIB_PATH))
        cls.lib.bootargs_parse.argtypes = [ctypes.c_char_p, ctypes.POINTER(CBootArgs)]

    def parse(self, data):
        out = CBootArgs()
        return self.lib.bootargs_parse(data, ctypes.byref(out)), out

    def test_agrees_with_python_decoder(self):
        data = capture()
        status, c = self.parse(data)
        py = decode_bootargs(data)
        self.assertEqual(status, OK)
        self.assertEqual((c.revision, c.version), (py["revision"], py["version"]))
        for name in ("virt_base", "phys_base", "mem_size", "machine_type", "device_tree"):
            self.assertEqual(hex(getattr(c, name)), py[name], name)
        self.assertEqual(hex(c.top_of_kdata), py["top_of_kernel_data"])
        self.assertEqual(c.device_tree_length, py["device_tree_length"])
        self.assertEqual(hex(c.boot_flags), py["boot_flags"])
        v = py["video"]
        self.assertEqual(hex(c.video_base), v["base"])
        self.assertEqual((c.video_width, c.video_height, c.video_row_bytes, c.depth_bits),
                         (v["width"], v["height"], v["row_bytes"], v["depth_bits"]))
        self.assertEqual(bool(c.video_ok), v["matches_console_geometry"])

    def test_pixel_format_candidates(self):
        for depth, fmt in ((30, X2R10G10B10), (32, X8R8G8B8), (0x00020000 | 30, X2R10G10B10)):
            _, c = self.parse(capture(video=(0x9E0000000, 1, 10240, 2560, 1600, depth)))
            self.assertTrue(c.video_ok)
            self.assertEqual(c.pixel_format, fmt)

    def test_video_rejections_keep_parse_ok(self):
        bad = {
            "depth 24": (0x9E0000000, 1, 10240, 2560, 1600, 24),
            "misaligned base": (0x9E0000002, 1, 10240, 2560, 1600, 30),
            "null base": (0, 1, 10240, 2560, 1600, 30),
            "short stride": (0x9E0000000, 1, 10236, 2560, 1600, 30),
            "odd stride": (0x9E0000000, 1, 10242, 2560, 1600, 30),
            "zero width": (0x9E0000000, 1, 10240, 0, 1600, 30),
            "too tall": (0x9E0000000, 1, 10240, 2560, 8193, 30),
            "huge stride": (0x9E0000000, 1, 0x20000, 2560, 1600, 30),
            "wraps": (2**64 - 0x1000, 1, 10240, 2560, 1600, 30),
        }
        for name, video in bad.items():
            with self.subTest(name):
                status, c = self.parse(capture(video=video))
                self.assertEqual(status, OK)
                self.assertFalse(c.video_ok)

    def test_video_in_ram_is_reported_not_rejected(self):
        _, c = self.parse(capture(video=(0x900000000, 1, 10240, 2560, 1600, 30)))
        self.assertTrue(c.video_ok)
        self.assertTrue(c.video_in_ram)
        _, c = self.parse(capture())
        self.assertFalse(c.video_in_ram)

    def test_structure_errors(self):
        self.assertEqual(self.parse(capture(Revision=3))[0], ERR_REVISION)
        self.assertEqual(self.parse(capture(Version=0))[0], ERR_VERSION)
        self.assertEqual(self.parse(capture(memSize=0))[0], ERR_MEMORY)
        self.assertEqual(self.parse(capture(physBase=0))[0], ERR_MEMORY)
        self.assertEqual(self.parse(capture(physBase=2**64 - 0x1000, memSize=0x2000))[0], ERR_MEMORY)

    def test_revision_1_has_no_boot_flags(self):
        _, c = self.parse(capture(Revision=1))
        self.assertEqual(c.boot_flags, 0)


if __name__ == "__main__":
    unittest.main()
