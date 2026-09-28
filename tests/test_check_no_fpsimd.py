# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the FP/SIMD instruction checker."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.check_no_fpsimd import is_fpsimd, scan

ROOT = Path(__file__).resolve().parents[1]


class EncodingTests(unittest.TestCase):
    def test_fp_and_simd_encodings(self):
        simd = {
            "fmov s0, w9": 0x1E270120, "mov v0.h[1], w8": 0x4E061D00,
            "xtn v0.8b, v0.8h": 0x0E212800, "ldr q0, [x0]": 0x3DC00000,
            "str q0, [x0]": 0x3D800000, "ldp q0, q1, [x0]": 0xAD400400,
            "fadd d0, d1, d2": 0x1E622820, "movi v0.2d, #0": 0x6F00E400,
        }
        for name, word in simd.items():
            with self.subTest(name):
                self.assertTrue(is_fpsimd(word))

    def test_integer_and_system_encodings(self):
        plain = {
            "add x0, x0, #1": 0x91000400, "str x0, [x1]": 0xF9000020,
            "ldrb w9, [x10]": 0x39400149, "stp x19, x20, [sp]": 0xA90053F3,
            "brk #0x4d31": 0xD429A620, "wfe": 0xD503205F, "mrs x2, CurrentEL": 0xD5384242,
            "b .": 0x14000000, "adrp x0, 0": 0x90000000, "mul x0, x1, x2": 0x9B027C20,
        }
        for name, word in plain.items():
            with self.subTest(name):
                self.assertFalse(is_fpsimd(word))


class ScanTests(unittest.TestCase):
    def test_built_images_are_clean(self):
        for name in ("monitor.elf", "entry-probe.elf", "screen-probe.elf"):
            path = ROOT / "build" / name
            if not path.exists():
                self.skipTest("run `make` first")
            self.assertEqual(scan(path), [], name)

    def test_detects_vectorized_code(self):
        # Positive control: the old flags let the compiler vectorize this loop.
        source = "void f(unsigned char *d, const unsigned char *s) { for (int i = 0; i < 64; i++) d[i] = s[i] + 1; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            c, elf = Path(tmp, "v.c"), Path(tmp, "v.elf")
            c.write_text(source)
            r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target",
                                "aarch64-freestanding-none", "-mcpu=cortex_a57", "-O2", "-nostdlib",
                                "-Wl,-e,f", "-Wl,--build-id=none", str(c), "-o", str(elf)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotEqual(scan(elf), [])


if __name__ == "__main__":
    unittest.main()
