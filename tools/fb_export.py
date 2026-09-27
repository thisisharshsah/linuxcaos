# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert a saved 32-bit framebuffer dump into a PNG or PPM image.

Reads only files. Each pixel is assumed to be a little-endian 0x00RRGGBB word,
the format written by src/framebuffer.c. That is a project convention, not an
observed Apple display format; a dump in another format will export incorrectly.
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path


def decode_xrgb8888(data: bytes, width: int, height: int, stride: int, offset: int = 0) -> bytes:
    """Return packed RGB888 rows, discarding row padding beyond width * 4 bytes."""
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
            b, g, r, _ = data[row + x * 4: row + x * 4 + 4]
            out[o:o + 3] = bytes((r, g, b))
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


def export(data: bytes, width: int, height: int, stride: int, fmt: str, offset: int = 0) -> bytes:
    rgb = decode_xrgb8888(data, width, height, stride, offset)
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
    args = parser.parse_args(argv)
    fmt = args.format or args.output.suffix.lstrip(".").lower()
    stride = args.stride if args.stride is not None else args.width * 4
    try:
        image = export(args.dump.read_bytes(), args.width, args.height, stride, fmt, args.offset)
    except (OSError, ValueError) as exc:
        print(f"fb_export: {exc}", file=sys.stderr)
        return 1
    args.output.write_bytes(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
