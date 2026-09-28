# SPDX-License-Identifier: GPL-2.0-or-later
"""Fill the real mainline MacBookPro17,1 DTB with src/fdt.c and let dtc judge it.

Needs `make upstream-dt` (network, once); skipped otherwise. The values filled
in are invented test data, not measurements from the Mac.
"""

import ctypes
import difflib
import subprocess
import unittest
from pathlib import Path

from tests.test_fdt_c import LIB_PATH, Fdt, LinuxParams
from tools.fdt import parse_dtb, string, u32, u64

ROOT = Path(__file__).resolve().parents[1]
DTB = ROOT / "build/upstream-dt/t8103-j293.dtb"
DTC = ROOT / "build/tools/dtc-1.8.1/dtc"


def decompile(blob: bytes) -> list[str]:
    r = subprocess.run([str(DTC), "-I", "dtb", "-O", "dts", "-"], input=blob, capture_output=True, check=True)
    assert not r.stderr, r.stderr.decode()  # dtc reports no warnings or errors
    return r.stdout.decode().splitlines()


class UpstreamDtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DTB.exists() and DTC.exists() and LIB_PATH.exists()):
            raise unittest.SkipTest("run `make upstream-dt host` first")
        lib = ctypes.CDLL(str(LIB_PATH))
        p = ctypes.POINTER(Fdt)
        lib.fdt_open.argtypes = [p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
        lib.fdt_total_size.argtypes = [p]
        lib.fdt_total_size.restype = ctypes.c_uint32
        lib.fdt_fill_linux.argtypes = [p, ctypes.POINTER(LinuxParams)]
        cls.lib = lib

    def fill(self, data: bytes, **values) -> bytes:
        capacity = len(data) + 4096
        mem = (ctypes.c_uint8 * capacity)()
        ctypes.memmove(mem, data, len(data))
        f = Fdt()
        self.assertEqual(self.lib.fdt_open(ctypes.byref(f), mem, capacity), 0)
        self.assertEqual(self.lib.fdt_fill_linux(ctypes.byref(f), ctypes.byref(LinuxParams(**values))), 0)
        return bytes(mem[:self.lib.fdt_total_size(ctypes.byref(f))])

    def test_parsers_agree_on_the_real_tree(self):
        root, _, _ = parse_dtb(DTB.read_bytes())
        self.assertEqual(root.props["compatible"], string("apple,j293") + string("apple,t8103")
                         + string("apple,arm-platform"))
        fb = root.child("chosen").child("framebuffer@0").props
        self.assertEqual(fb["status"], string("disabled"))
        self.assertEqual(root.child("memory@800000000").props["reg"], u32(8, 0, 2, 0))

    def test_fill_changes_only_the_loader_fields(self):
        original = DTB.read_bytes()
        filled = self.fill(original, mem_base=0x800000000, mem_size=0x1E0000000,
                           bootargs=b"earlycon console=tty0", initrd_start=0x810000000,
                           initrd_end=0x810800000, fb_base=0x9E0000000, fb_width=2560,
                           fb_height=1600, fb_stride=10240, fb_format=b"x2r10g10b10")
        diff = [line for line in difflib.unified_diff(decompile(original), decompile(filled), n=0, lineterm="")
                if line[:1] in "+-" and not line.startswith(("+++", "---"))]
        expected = {
            '+\t\tbootargs = "earlycon console=tty0";',
            "+\t\tlinux,initrd-start = <0x08 0x10000000>;",
            "+\t\tlinux,initrd-end = <0x08 0x10800000>;",
            "-\t\t\treg = <0x00 0x00 0x00 0x00>;",
            '-\t\t\tstatus = "disabled";',
            "+\t\t\treg = <0x09 0xe0000000 0x00 0xfa0000>;",
            '+\t\t\tstatus = "okay";',
            "+\t\t\twidth = <0xa00>;",
            "+\t\t\theight = <0x640>;",
            "+\t\t\tstride = <0x2800>;",
            '+\t\t\tformat = "x2r10g10b10";',
            "-\t\treg = <0x08 0x00 0x02 0x00>;",
            "+\t\treg = <0x08 0x00 0x01 0xe0000000>;",
        }
        self.assertEqual(set(diff), expected)
        self.assertEqual(len(diff), len(expected))
        chosen = parse_dtb(filled)[0].child("chosen")
        self.assertEqual(chosen.props["linux,initrd-end"], u64(0x810800000))


if __name__ == "__main__":
    unittest.main()
