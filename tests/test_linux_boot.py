# SPDX-License-Identifier: GPL-2.0-or-later
"""Host tests of src/linux_boot.c, built by `make host`. Headers are synthetic."""

import ctypes
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = ROOT / "build/host/libportable.so"
MAGIC = 0x644D5241
MB2, GB = 0x200000, 0x40000000

# Status codes, in the order declared in src/linux_boot.h.
(OK, ERR_SHORT, ERR_MAGIC, ERR_LEGACY, ERR_BIG_ENDIAN, ERR_FLAGS,
 ERR_TEXT_OFFSET, ERR_FILE_SIZE) = range(8)
(PLAN_OK, PLAN_ERR_RAM, PLAN_ERR_DTB, PLAN_ERR_NO_ROOM, PLAN_ERR_WINDOW,
 PLAN_ERR_48BIT) = range(6)


class ImageInfo(ctypes.Structure):
    _fields_ = [("text_offset", ctypes.c_uint64), ("image_size", ctypes.c_uint64),
                ("flags", ctypes.c_uint64), ("page_size_kb", ctypes.c_uint32),
                ("anywhere", ctypes.c_uint32)]


class BootPlan(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in
                ("image_base", "kernel", "kernel_end", "dtb", "initrd", "initrd_end")]


def load_library():
    if not LIB_PATH.exists():
        raise unittest.SkipTest("run `make host` first")
    lib = ctypes.CDLL(str(LIB_PATH))
    lib.linux_image_parse.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64,
                                      ctypes.POINTER(ImageInfo)]
    lib.linux_boot_plan.argtypes = [ctypes.POINTER(ImageInfo)] + [ctypes.c_uint64] * 4 + [
        ctypes.POINTER(BootPlan)]
    return lib


def header(text_offset=0, image_size=0x1A00000, flags=0b1010, magic=MAGIC):
    """Layout from booting.rst: code0, code1, text_offset, image_size, flags,
    res2-res4, magic, res5 (PE offset)."""
    return struct.pack("<IIQQQQQQII", 0x91005A4D, 0x14000000, text_offset, image_size,
                       flags, 0, 0, 0, magic, 0x40)


class ParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_library()

    def parse(self, data, file_size=0):
        info = ImageInfo()
        return self.lib.linux_image_parse(data, len(data), file_size, ctypes.byref(info)), info

    def test_header_is_64_bytes(self):
        self.assertEqual(len(header()), 64)

    def test_decodes_fields_and_flags(self):
        # flags 0b1100: bits 1-2 = 2 (16K pages), bit 3 = 1 (placement anywhere).
        status, info = self.parse(header(text_offset=0x80000, flags=0b1100))
        self.assertEqual(status, OK)
        self.assertEqual((info.text_offset, info.image_size), (0x80000, 0x1A00000))
        self.assertEqual(info.page_size_kb, 16)
        self.assertEqual(info.anywhere, 1)
        for bits, kb in ((0, 0), (1, 4), (2, 16), (3, 64)):
            self.assertEqual(self.parse(header(flags=bits << 1))[1].page_size_kb, kb)

    def test_rejections(self):
        cases = {
            ERR_SHORT: header()[:63],
            ERR_MAGIC: header(magic=0x08088B1F),  # e.g. a gzip-compressed Image.gz
            ERR_LEGACY: header(image_size=0),
            ERR_BIG_ENDIAN: header(flags=1),
            ERR_FLAGS: header(flags=1 << 4),
            ERR_TEXT_OFFSET: header(text_offset=MB2),
        }
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(self.parse(data)[0], expected)
        self.assertEqual(self.parse(header(text_offset=0x80001))[0], ERR_TEXT_OFFSET)

    def test_file_larger_than_image_size(self):
        self.assertEqual(self.parse(header(image_size=0x1000), file_size=0x1001)[0], ERR_FILE_SIZE)
        self.assertEqual(self.parse(header(image_size=0x1000), file_size=0x1000)[0], OK)


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_library()

    def plan(self, ram_base, ram_size, dtb=0x10000, initrd=0, **image):
        info = ImageInfo()
        assert self.lib.linux_image_parse(header(**image), 64, 0, ctypes.byref(info)) == OK
        out = BootPlan()
        status = self.lib.linux_boot_plan(ctypes.byref(info), ram_base, ram_size, dtb, initrd,
                                          ctypes.byref(out))
        return status, out

    def test_documented_constraints_hold(self):
        status, p = self.plan(0x40000000 + 0x1234, 0x40000000, initrd=0x800000,
                              text_offset=0x80000, image_size=0x1A00000, flags=0)
        self.assertEqual(status, PLAN_OK)
        self.assertEqual(p.image_base % MB2, 0)
        self.assertEqual(p.image_base, 0x40200000)  # lowest 2 MB base at or above RAM start
        self.assertEqual(p.kernel, p.image_base + 0x80000)
        self.assertEqual(p.kernel_end, p.kernel + 0x1A00000)
        self.assertEqual(p.dtb % 8, 0)
        self.assertGreaterEqual(p.dtb, p.kernel_end)
        self.assertEqual(p.dtb // MB2, (p.dtb + 0x10000 - 1) // MB2)  # DTB in its own 2 MB block
        self.assertGreaterEqual(p.initrd, p.dtb + 0x10000)
        self.assertEqual(p.initrd_end - p.initrd, 0x800000)
        self.assertLessEqual(p.initrd_end, 0x40000000 + 0x1234 + 0x40000000)

    def test_no_initrd(self):
        status, p = self.plan(0x80000000, 0x10000000)
        self.assertEqual(status, PLAN_OK)
        self.assertEqual((p.initrd, p.initrd_end), (0, 0))

    def test_errors(self):
        self.assertEqual(self.plan(0x80000000, 0)[0], PLAN_ERR_RAM)
        self.assertEqual(self.plan(2**64 - MB2, 2 * MB2)[0], PLAN_ERR_RAM)
        self.assertEqual(self.plan(0x80000000, GB, dtb=0)[0], PLAN_ERR_DTB)
        self.assertEqual(self.plan(0x80000000, GB, dtb=MB2 + 1)[0], PLAN_ERR_DTB)
        self.assertEqual(self.plan(0x80000000, GB, dtb=MB2)[0], PLAN_OK)
        self.assertEqual(self.plan(0x80000000, 0x1000000)[0], PLAN_ERR_NO_ROOM)
        self.assertEqual(self.plan(0x80000000, GB, initrd=GB)[0], PLAN_ERR_NO_ROOM)
        self.assertEqual(self.plan(2**64 - 4 * MB2, 4 * MB2 - 1)[0], PLAN_ERR_NO_ROOM)

    def test_initrd_window_limit(self):
        # Kernel at 31.875 GB: its 1 GB window starts at 31 GB. The initrd follows ~26 MB later.
        base = 32 * GB - 64 * MB2
        self.assertEqual(self.plan(base, 64 * GB, initrd=31 * GB)[0], PLAN_OK)  # ends in 63 GB: exactly 32 GB
        self.assertEqual(self.plan(base, 64 * GB, initrd=32 * GB)[0], PLAN_ERR_WINDOW)  # 33 GB

    def test_48bit_limit_for_anywhere_images(self):
        top = 1 << 48
        self.assertEqual(self.plan(top - 4 * MB2, 64 * MB2, flags=0b1000)[0], PLAN_ERR_48BIT)
        self.assertEqual(self.plan(top - 4 * MB2, 64 * MB2, flags=0)[0], PLAN_OK)


if __name__ == "__main__":
    unittest.main()
