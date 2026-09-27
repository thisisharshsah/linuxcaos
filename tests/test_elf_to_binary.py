# SPDX-License-Identifier: GPL-2.0-or-later
"""Host unit tests for raw ELF extraction, independent of CPU/hardware tests."""
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from elf_to_binary import BASE, LIMIT, convert


def elf(segments=None, *, base=BASE, **header_changes):
    """Build tiny original fixtures; no external ELF fixtures or generators."""
    if segments is None:
        segments = [{"payload": b"CODE"}]
    fields = dict(kind=2, machine=183, version=1, entry=base, phoff=64,
                  shoff=0, flags=0, ehsize=64, phsize=56, phnum=len(segments),
                  shsize=0, shnum=0, shstr=0)
    fields.update(header_changes)
    data = bytearray(0x200 + 0x100 * len(segments))
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, *fields.values())
    for i, segment in enumerate(segments):
        payload = segment.get("payload", b"")
        offset = segment.get("offset", 0x200 + 0x100 * i)
        address = segment.get("address", base)
        struct.pack_into("<IIQQQQQQ", data, 64 + 56 * i,
                         segment.get("type", 1), segment.get("flags", 5),
                         offset, address, segment.get("physical", address),
                         len(payload), segment.get("memsz", len(payload)),
                         segment.get("align", 1))
        data[offset:offset + len(payload)] = payload
    return data


def ph_change(data, index, field_offset, value, *, size="Q"):
    struct.pack_into("<" + size, data, 64 + 56 * index + field_offset, value)
    return data


class ConversionTests(unittest.TestCase):
    def test_default_monitor_base(self):
        self.assertEqual(convert(elf()), b"CODE")

    def test_zero_and_relocated_bases(self):
        for base in (0, 0x10000, 0xffff000000000000):
            with self.subTest(base=base):
                self.assertEqual(convert(elf(base=base), base=base), b"CODE")

    def test_reordered_segments_gaps_and_trailing_bss(self):
        image = elf([
            {"address": BASE + 16, "payload": b"DATA", "flags": 6, "memsz": 32},
            {"payload": b"CODE", "memsz": 12},
        ])
        self.assertEqual(convert(image), b"CODE" + bytes(12) + b"DATA")

    def test_zero_only_tail_is_not_stored(self):
        self.assertEqual(convert(elf([
            {"payload": b"CODE"},
            {"address": BASE + 4, "memsz": 64, "flags": 6},
        ])), b"CODE")

    def test_exact_memory_limit_is_accepted(self):
        self.assertEqual(convert(elf([{"payload": b"CODE", "memsz": 16}]),
                                 limit=16), b"CODE")

    def test_metadata_headers_are_not_memory_segments(self):
        self.assertEqual(convert(elf([
            {"payload": b"CODE"},
            {"type": 0x6474e551, "address": 0, "memsz": 0x1000000},
        ])), b"CODE")

    def test_empty_segment_is_ignored(self):
        self.assertEqual(convert(elf([
            {"payload": b"CODE"}, {"address": BASE + 1},
        ])), b"CODE")

    def test_valid_alignments(self):
        for align in (0, 1, 4, 0x100):
            with self.subTest(align=align):
                self.assertEqual(convert(elf([{"payload": b"CODE", "align": align}])),
                                 b"CODE")

    def test_malformed_identification(self):
        for data in (b"", b"\x7fELF", elf()[:63]):
            with self.subTest(length=len(data)):
                with self.assertRaisesRegex(ValueError, "little-endian ELF64"):
                    convert(data)
        for offset, value in ((0, 0), (4, 1), (5, 2), (6, 0)):
            with self.subTest(offset=offset):
                image = elf()
                image[offset] = value
                with self.assertRaisesRegex(ValueError, "little-endian ELF64"):
                    convert(image)

    def test_wrong_target_and_header_lengths(self):
        for changes in ({"kind": 3}, {"machine": 62}, {"version": 0},
                        {"ehsize": 63}, {"phsize": 55}, {"phnum": 0},
                        {"phnum": 0xffff}, {"phoff": 16}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    convert(elf(**changes))

    def test_wrong_entry(self):
        with self.assertRaisesRegex(ValueError, "entry must equal"):
            convert(elf(entry=BASE + 4))

    def test_truncated_program_table(self):
        for data in (elf()[:119], elf(phoff=(1 << 64) - 56)):
            with self.assertRaisesRegex(ValueError, "Truncated program header"):
                convert(data)

    def test_truncated_load_segment(self):
        with self.assertRaisesRegex(ValueError, "Truncated load segment"):
            convert(elf()[:0x202])
        with self.assertRaisesRegex(ValueError, "Truncated load segment"):
            convert(ph_change(elf(), 0, 8, (1 << 64) - 1))

    def test_file_size_exceeds_memory(self):
        with self.assertRaisesRegex(ValueError, "file size exceeds memory"):
            convert(elf([{"payload": b"CODE", "memsz": 3}]))

    def test_virtual_and_physical_must_match(self):
        with self.assertRaisesRegex(ValueError, "addresses must match"):
            convert(elf([{"payload": b"CODE", "physical": BASE + 4}]))

    def test_segment_outside_range(self):
        for segment in ({"address": BASE - 4, "payload": b"CODE"},
                        {"payload": b"CODE", "memsz": LIMIT + 1},
                        {"address": BASE + LIMIT, "payload": b"CODE"},
                        {"address": (1 << 64) - 4, "payload": b"CODE", "memsz": 8}):
            with self.subTest(segment=segment):
                with self.assertRaisesRegex(ValueError, "outside reserved"):
                    convert(elf([segment]))

    def test_invalid_alignment(self):
        for align in (3, 0x1000):
            with self.subTest(align=align):
                with self.assertRaisesRegex(ValueError, "alignment"):
                    convert(elf([{"payload": b"CODE", "align": align}]))

    def test_file_overlap(self):
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            convert(elf([{"payload": b"CODECODE"},
                         {"address": BASE + 4, "payload": b"DATA"}]))

    def test_bss_overlap(self):
        for second in ({"address": BASE + 8, "payload": b"DATA"},
                       {"address": BASE + 8, "memsz": 16}):
            with self.subTest(second=second):
                with self.assertRaisesRegex(ValueError, "Overlapping"):
                    convert(elf([{"payload": b"CODE", "memsz": 16}, second]))

    def test_entry_must_be_executable_and_file_backed(self):
        for segments in ([{"payload": b"CODE", "flags": 4}],
                         [{"payload": b"ABC"}],
                         [{"memsz": 16}],
                         [{"address": BASE + 4, "payload": b"CODE"}],
                         [{"type": 0, "payload": b"CODE"}]):
            with self.subTest(segments=segments):
                with self.assertRaisesRegex(ValueError, "executable file-backed"):
                    convert(elf(segments))

    def test_dynamic_and_interpreter_are_rejected(self):
        for kind in (2, 3):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "Dynamic or interpreter"):
                    convert(elf([{"payload": b"CODE"}, {"type": kind}]))

    def test_invalid_requested_ranges(self):
        for kwargs in ({"base": -4}, {"base": 1}, {"base": 1 << 64},
                       {"limit": 0}, {"limit": -1}, {"limit": 1 << 64},
                       {"base": "0"}, {"limit": 1.5}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    convert(elf(), **kwargs)


class CommandLineTests(unittest.TestCase):
    def test_custom_base_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.elf"
            destination = Path(directory) / "output.bin"
            source.write_bytes(elf(base=0))
            result = subprocess.run([
                sys.executable, str(ROOT / "tools/elf_to_binary.py"),
                str(source), str(destination), "--base", "0", "--limit", "0x1000",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), b"CODE")

    def test_invalid_input_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.elf"
            destination = Path(directory) / "output.bin"
            source.write_bytes(b"invalid")
            destination.write_bytes(b"KEEP")
            result = subprocess.run([
                sys.executable, str(ROOT / "tools/elf_to_binary.py"),
                str(source), str(destination),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Expected a little-endian ELF64", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(destination.read_bytes(), b"KEEP")


if __name__ == "__main__":
    unittest.main()
