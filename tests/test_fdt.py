# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the flattened device tree writer/reader."""

import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.fdt import (Node, build_dtb, format_tree, minimal_linux_tree, parse_dtb,
                       string, u32, u64)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "fdt.py"


class GoldenTests(unittest.TestCase):
    def test_smallest_tree_matches_hand_assembled_bytes(self):
        # Root node with one property "a" = <1>; laid out by hand from spec section 5.
        blob = build_dtb(Node("", {"a": u32(1)}))
        struct_block = (u32(1) + b"\0\0\0\0"          # BEGIN_NODE, "" padded
                        + u32(3, 4, 0) + u32(1)        # PROP len=4 nameoff=0 value
                        + u32(2) + u32(9))             # END_NODE, END
        strings = b"a\0"
        rsvmap = bytes(16)
        header = struct.pack(">10I", 0xD00DFEED, 40 + 16 + len(struct_block) + 2,
                             56, 56 + len(struct_block), 40, 17, 16, 0, 2, len(struct_block))
        self.assertEqual(blob, header + rsvmap + struct_block + strings)


class RoundTripTests(unittest.TestCase):
    def test_tree_reserve_and_cpuid(self):
        root = Node("", {"#address-cells": u32(2), "empty": b""}, [
            Node("a@1", {"x": string("hi"), "#address-cells": u32(1)}, [Node("deep", {"odd": b"\x01\x02\x03"})]),
            Node("b", {}),
        ])
        blob = build_dtb(root, reserve=[(0x1000, 0x2000)], boot_cpuid=3)
        parsed, reserve, cpu = parse_dtb(blob)
        self.assertEqual(parsed, root)
        self.assertEqual((reserve, cpu), ([(0x1000, 0x2000)], 3))
        # Repeated property names share one string.
        self.assertEqual(blob.count(b"#address-cells\0"), 1)

    def test_minimal_linux_tree(self):
        tree = minimal_linux_tree(0x40000000, 0x8000000, "console=ttyAMA0",
                                  initrd=(0x48000000, 0x48800000), stdout_path="/pl011@9000000")
        root, _, _ = parse_dtb(build_dtb(tree))
        memory = root.child("memory@40000000")
        self.assertEqual(memory.props["device_type"], b"memory\0")
        self.assertEqual(memory.props["reg"], u64(0x40000000, 0x8000000))
        chosen = root.child("chosen")
        self.assertEqual(chosen.props["bootargs"], b"console=ttyAMA0\0")
        self.assertEqual(chosen.props["linux,initrd-start"], u64(0x48000000))
        self.assertEqual(chosen.props["linux,initrd-end"], u64(0x48800000))
        text = format_tree(root)
        self.assertIn('bootargs = "console=ttyAMA0";', text)
        self.assertIn("reg = <0x0 0x40000000 0x0 0x8000000>;", text)


class RejectionTests(unittest.TestCase):
    def setUp(self):
        self.blob = bytearray(build_dtb(minimal_linux_tree(0x40000000, 0x1000000)))

    def patch_header(self, index, value):
        data = bytearray(self.blob)
        struct.pack_into(">I", data, index * 4, value)
        return bytes(data)

    def test_header_errors(self):
        cases = {
            "magic": self.patch_header(0, 0x12345678),
            "totalsize": self.patch_header(1, len(self.blob) + 4),
            "misaligned rsvmap": self.patch_header(4, 44),
            "version": self.patch_header(6, 18),
            "strings range": self.patch_header(8, 0xFFFF),
            "truncated": bytes(self.blob[:20]),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_dtb(data)

    def test_structure_errors(self):
        off_struct = struct.unpack_from(">I", self.blob, 8)[0]
        bad_token = bytearray(self.blob)
        struct.pack_into(">I", bad_token, off_struct, 7)
        with self.assertRaises(ValueError):
            parse_dtb(bytes(bad_token))
        size_struct = struct.unpack_from(">I", self.blob, 36)[0]
        no_end = bytearray(self.blob)
        struct.pack_into(">I", no_end, off_struct + size_struct - 4, 4)  # END -> NOP
        with self.assertRaises(ValueError):
            parse_dtb(bytes(no_end))

    def test_builder_rejects_bad_names(self):
        with self.assertRaises(ValueError):
            build_dtb(Node("", {}, [Node("a/b")]))
        with self.assertRaises(ValueError):
            build_dtb(Node("root"))


class CliTests(unittest.TestCase):
    def test_build_then_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "t.dtb")
            r = subprocess.run([sys.executable, CLI, "build", out, "--memory", "0x40000000:0x8000000",
                                "--bootargs", "quiet", "--initrd", "0x44000000:0x100000"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([sys.executable, CLI, "dump", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('bootargs = "quiet";', r.stdout)
            self.assertIn("linux,initrd-end = <0x0 0x44100000>;", r.stdout)

    def test_dump_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "bad.dtb")
            bad.write_bytes(b"\0" * 64)
            r = subprocess.run([sys.executable, CLI, "dump", bad], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("bad magic", r.stderr)


if __name__ == "__main__":
    unittest.main()
