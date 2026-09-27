# SPDX-License-Identifier: GPL-2.0-or-later
"""Decode a saved candidate Apple ARM64 boot_args capture into JSON.

The layout follows Apple's public XNU header pexpert/pexpert/arm64/boot.h at
xnu-7195.81.3 (see docs/APPLE_BOOT.md), with ordinary LP64 alignment. This tool
only reads files: it never dereferences the pointers a capture contains. A
decodable capture is not proof that the firmware passed boot_args to our payload,
that this historical layout matches current firmware, or that any address in
it (including the framebuffer) is valid or safe to access.
"""

import argparse
import json
import struct
import sys
from pathlib import Path


SIZE = 0x2E0
COMMAND_LINE_OFFSET = 0x6C
COMMAND_LINE_LENGTH = 608
REVISION_WITH_BOOT_FLAGS = 2
SUPPORTED_REVISIONS = (1, 2)
SUPPORTED_VERSIONS = (1, 2)
DEPTH_MASK = 0xFF
DEPTH_ROTATE_SHIFT = 8
DEPTH_SCALE_SHIFT = 16
BOOT_FLAG_DARK_BOOT = 1 << 0
EVIDENCE_NOTE = (
    "Untrusted evidence: layout derived from historical XNU source, not from a "
    "firmware specification. Pointers and the framebuffer address are unverified; "
    "never access them without separate evidence."
)

_HEAD = struct.Struct("<HH4xQQQQ6QI4xQI")          # 0x000-0x06b
_TAIL = struct.Struct("<QQ")                        # 0x2d0-0x2df


def _hex(value: int) -> str:
    return hex(value)


def decode_bootargs(data: bytes) -> dict:
    """Validate and decode exactly one little-endian boot_args capture."""
    if len(data) != SIZE:
        raise ValueError(f"Expected exactly {SIZE} bytes ({SIZE:#x}); got {len(data)}")
    (revision, version, virt_base, phys_base, mem_size, top_of_kernel,
     v_base, v_display, v_row_bytes, v_width, v_height, v_depth,
     machine_type, device_tree, device_tree_length) = _HEAD.unpack_from(data, 0)
    if revision not in SUPPORTED_REVISIONS:
        raise ValueError(f"Unsupported boot_args revision {revision}; layout known only for {SUPPORTED_REVISIONS}")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported boot_args version {version}; expected one of {SUPPORTED_VERSIONS}")

    warnings = []
    raw_cmdline = data[COMMAND_LINE_OFFSET:COMMAND_LINE_OFFSET + COMMAND_LINE_LENGTH]
    terminator = raw_cmdline.find(b"\0")
    if terminator < 0:
        warnings.append("CommandLine has no NUL terminator; shown truncated at field end")
        terminator = COMMAND_LINE_LENGTH
    command_line = raw_cmdline[:terminator].decode("ascii", errors="backslashreplace")

    boot_flags, mem_size_actual = _TAIL.unpack_from(data, 0x2D0)
    if revision < REVISION_WITH_BOOT_FLAGS:
        # The header marks bootFlags as added in revision 2; older trailing bytes are undefined.
        boot_flags = mem_size_actual = None
        warnings.append("Revision 1 predates bootFlags; trailing fields not decoded")

    depth_bits = v_depth & DEPTH_MASK
    rotate = (v_depth >> DEPTH_ROTATE_SHIFT) & 0xFF
    scale = (v_depth >> DEPTH_SCALE_SHIFT) & 0xFF
    if v_base and depth_bits and v_row_bytes * 8 < v_width * depth_bits:
        warnings.append("Video rowBytes is smaller than width * depth")
    if phys_base and mem_size and phys_base + mem_size > 1 << 64:
        warnings.append("physBase + memSize wraps the address space")
    if device_tree and not device_tree_length:
        warnings.append("deviceTreeP is set but deviceTreeLength is zero")

    return {
        "size": SIZE,
        "revision": revision,
        "version": version,
        "virt_base": _hex(virt_base),
        "phys_base": _hex(phys_base),
        "mem_size": _hex(mem_size),
        "top_of_kernel_data": _hex(top_of_kernel),
        "video": {
            "base": _hex(v_base),
            "display": _hex(v_display),
            "row_bytes": v_row_bytes,
            "width": v_width,
            "height": v_height,
            "depth_raw": _hex(v_depth),
            "depth_bits": depth_bits,
            "rotate": rotate,
            "scale": scale,
            # Documentation-derived guess (see docs/RESEARCH.md), never a measurement:
            # depth 30 -> x2r10g10b10, depth 32 -> x8r8g8b8, both in 32-bit words.
            "console_format_candidate": {30: "x2r10g10b10", 32: "x8r8g8b8"}.get(depth_bits),
            "matches_console_geometry": bool(
                v_base and depth_bits in (30, 32) and v_width and v_height
                and v_row_bytes >= v_width * 4 and v_row_bytes % 4 == 0 and v_base % 4 == 0),
        },
        "machine_type": _hex(machine_type),
        "device_tree": _hex(device_tree),
        "device_tree_length": device_tree_length,
        "command_line": command_line,
        "boot_flags": None if boot_flags is None else _hex(boot_flags),
        "dark_boot": None if boot_flags is None else bool(boot_flags & BOOT_FLAG_DARK_BOOT),
        "mem_size_actual": None if mem_size_actual is None else _hex(mem_size_actual),
        "warnings": warnings,
        "evidence_note": EVIDENCE_NOTE,
    }


def nonnegative_offset(value: str) -> int:
    try:
        offset = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("offset must be an integer (e.g. 64 or 0x40)") from exc
    if offset < 0:
        raise argparse.ArgumentTypeError("offset must be nonnegative")
    return offset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="saved boot_args capture or memory dump")
    parser.add_argument("--offset", type=nonnegative_offset, default=0,
                        help="byte offset of the structure inside the file (default: 0)")
    args = parser.parse_args(argv)
    try:
        with args.path.open("rb") as f:
            f.seek(args.offset)
            data = f.read(SIZE)
        result = decode_bootargs(data)
    except (OSError, ValueError) as exc:
        print(f"inspect_bootargs: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
