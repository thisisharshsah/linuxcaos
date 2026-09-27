# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert a saved 32-bit framebuffer dump into a PNG or PPM image.

Reads only files. Each pixel is a little-endian 32-bit word in one of the
formats src/framebuffer.c writes (Linux simple-framebuffer names): x8r8g8b8
(default) or x2r10g10b10. Neither is an observed Apple display format; a dump in
another format will export incorrectly.
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path


PIXEL_FORMATS = ("x8r8g8b8", "x2r10g10b10")


def _rgb(word: int, pixel: str) -> bytes:
    if pixel == "x2r10g10b10":
        # Keep the top 8 of each 10-bit channel.
        return bytes(((word >> 22) & 0xFF, (word >> 12) & 0xFF, (word >> 2) & 0xFF))
    return bytes(((word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF))


def decode_xrgb8888(data: bytes, width: int, height: int, stride: int, offset: int = 0,
                    pixel: str = "x8r8g8b8") -> bytes:
    """Return packed RGB888 rows, discarding row padding beyond width * 4 bytes."""
    if pixel not in PIXEL_FORMATS:
        raise ValueError(f"unsupported pixel format: {pixel}")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if stride < width * 4:
        raise ValueError(f"stride {stride} is shorter than a {width}-pixel row")
    if offset < 0:
        raise ValueError("offset must not be negative")
    needed = offset + stride * (height - 1) + width * 4
    if len(data) < needed:
        raise ValueError(f"dump has {len(data)} bytes; geometry needs {needed}")
    out = bytearray(width * height * 3)
    o = 0
    for y in range(height):
        row = offset + y * stride
        for x in range(width):
            word = int.from_bytes(data[row + x * 4: row + x * 4 + 4], "little")
            out[o:o + 3] = _rgb(word, pixel)
            o += 3
    return bytes(out)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def encode_png(rgb: bytes, width: int, height: int) -> bytes:
    if len(rgb) != width * height * 3:
        raise ValueError("RGB data size does not match geometry")
    rows = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(rows, 9)) + _png_chunk(b"IEND", b""))


def encode_ppm(rgb: bytes, width: int, height: int) -> bytes:
    if len(rgb) != width * height * 3:
        raise ValueError("RGB data size does not match geometry")
    return f"P6\n{width} {height}\n255\n".encode("ascii") + rgb


def export(data: bytes, width: int, height: int, stride: int, fmt: str, offset: int = 0,
           pixel: str = "x8r8g8b8") -> bytes:
    rgb = decode_xrgb8888(data, width, height, stride, offset, pixel)
    if fmt == "png":
        return encode_png(rgb, width, height)
    if fmt == "ppm":
        return encode_ppm(rgb, width, height)
    raise ValueError(f"unsupported format: {fmt}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dump", type=Path, help="raw framebuffer bytes")
    parser.add_argument("output", type=Path, help="output image (.png or .ppm)")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--stride", type=int, help="bytes per row (default: width * 4)")
    parser.add_argument("--offset", type=int, default=0, help="byte offset of the first pixel")
    parser.add_argument("--format", choices=("png", "ppm"), help="default: from output suffix")
    parser.add_argument("--pixel", choices=PIXEL_FORMATS, default="x8r8g8b8",
                        help="pixel format of the dump (default: x8r8g8b8)")
    args = parser.parse_args(argv)
    fmt = args.format or args.output.suffix.lstrip(".").lower()
    stride = args.stride if args.stride is not None else args.width * 4
    try:
        image = export(args.dump.read_bytes(), args.width, args.height, stride, fmt, args.offset,
                       args.pixel)
    except (OSError, ValueError) as exc:
        print(f"fb_export: {exc}", file=sys.stderr)
        return 1
    args.output.write_bytes(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
