# SPDX-License-Identifier: GPL-2.0-or-later
"""Host tests for the framebuffer image exporter; dumps here are synthetic."""

import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from tools.fb_export import decode_xrgb8888, encode_png, encode_ppm, export


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "fb_export.py"


def pixels(*rows, pad=0):
    """Build a dump from rows of 0x00RRGGBB values, with `pad` junk bytes per row."""
    return b"".join(struct.pack(f"<{len(r)}I", *r) + b"\xee" * pad for r in rows)


def decode_png(data):
    """Minimal PNG reader for 8-bit RGB, filter-0 images, validating each CRC."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + payload) & 0xFFFFFFFF, kind
        chunks[kind] = chunks.get(kind, b"") + payload
        pos += 12 + length
    width, height, depth, color, *_ = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, color) == (8, 2)
    raw = zlib.decompress(chunks[b"IDAT"])
    rows = [raw[y * (width * 3 + 1):(y + 1) * (width * 3 + 1)] for y in range(height)]
    assert all(r[0] == 0 for r in rows)
    return width, height, b"".join(r[1:] for r in rows)


class DecodeTests(unittest.TestCase):
    def test_channel_order_and_padding_ignored(self):
        dump = pixels([0x00112233, 0xFF445566], [0x00AABBCC, 0x00000000], pad=8)
        rgb = decode_xrgb8888(dump, 2, 2, 16)
        # The top byte (X) is ignored; padding bytes never appear.
        self.assertEqual(rgb, bytes.fromhex("112233 445566 aabbcc 000000".replace(" ", "")))

    def test_offset(self):
        dump = b"\x00" * 4 + pixels([0x00010203])
        self.assertEqual(decode_xrgb8888(dump, 1, 1, 4, offset=4), b"\x01\x02\x03")

    def test_last_row_padding_not_required(self):
        dump = pixels([0x1], pad=4) + pixels([0x2])
        self.assertEqual(len(decode_xrgb8888(dump, 1, 2, 8)), 6)

    def test_rejects_bad_geometry(self):
        dump = pixels([0, 0], [0, 0])
        for args in ((0, 2, 8), (2, 0, 8), (2, 2, 4), (2, 3, 8)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                decode_xrgb8888(dump, *args)
        with self.assertRaises(ValueError):
            decode_xrgb8888(dump, 2, 2, 8, offset=-1)


class EncodeTests(unittest.TestCase):
    def test_png_round_trip(self):
        dump = pixels([0x00FF0000, 0x0000FF00, 0x000000FF], [0x00FFFFFF, 0, 0x00808080], pad=4)
        width, height, rgb = decode_png(export(dump, 3, 2, 16, "png"))
        self.assertEqual((width, height), (3, 2))
        self.assertEqual(rgb, decode_xrgb8888(dump, 3, 2, 16))

    def test_ppm_header_and_body(self):
        data = encode_ppm(b"\x01\x02\x03", 1, 1)
        self.assertEqual(data, b"P6\n1 1\n255\n\x01\x02\x03")

    def test_size_mismatch_and_unknown_format(self):
        with self.assertRaises(ValueError):
            encode_png(b"\x00" * 5, 1, 2)
        with self.assertRaises(ValueError):
            encode_ppm(b"\x00" * 5, 1, 2)
        with self.assertRaises(ValueError):
            export(pixels([0]), 1, 1, 4, "bmp")


class CliTests(unittest.TestCase):
    def test_writes_png_from_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump, out = Path(tmp, "fb.bin"), Path(tmp, "fb.png")
            dump.write_bytes(pixels([0x00123456, 0x00654321]))
            result = subprocess.run([sys.executable, CLI, dump, out, "--width", "2", "--height", "1"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(decode_png(out.read_bytes())[2], bytes.fromhex("123456654321"))

    def test_short_dump_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump, out = Path(tmp, "fb.bin"), Path(tmp, "fb.ppm")
            dump.write_bytes(b"\x00" * 4)
            result = subprocess.run([sys.executable, CLI, dump, out, "--width", "2", "--height", "1"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("geometry needs 8", result.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
