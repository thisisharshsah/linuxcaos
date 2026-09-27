# SPDX-License-Identifier: GPL-2.0-or-later
"""Extract a bounded, little-endian ARM64 ELF executable's raw load image.

The caller supplies the load base; this does not relocate an ELF. File-backed
segments and gaps are emitted, while trailing BSS remains the payload's duty.
This is development-image extraction, not Apple boot-payload packaging.
"""
import argparse
import struct
from pathlib import Path

BASE = 0x40080000
LIMIT = 0x100000


def convert(data, *, base=BASE, limit=LIMIT):
    """Return raw load bytes after validating the complete memory layout."""
    if (not isinstance(base, int) or not isinstance(limit, int)
            or base < 0 or limit <= 0 or base + limit > 1 << 64):
        raise ValueError("Base and positive limit must define an unsigned 64-bit range")
    if base % 4:
        raise ValueError("ARM64 entry base must be 4-byte aligned")
    if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError("Expected a little-endian ELF64 image")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    kind, machine, version, entry, phoff = header[:5]
    ehsize, phsize, phnum = header[7:10]
    if (kind, machine, version) != (2, 183, 1):
        raise ValueError("Expected an ARM64 ELF executable (ET_EXEC)")
    if entry != base:
        raise ValueError("ELF entry must equal the requested image base")
    if ehsize != 64 or phsize != 56:
        raise ValueError("Unsupported ELF or program header size")
    if not phnum or phnum == 0xffff:
        raise ValueError("Missing or unsupported extended program header count")
    if phoff < ehsize:
        raise ValueError("Program header table overlaps the ELF header")
    if phoff + phnum * phsize > len(data):
        raise ValueError("Truncated program header table")
    segments = []
    entry_found = False
    for i in range(phnum):
        typ, flags, offset, virt, phys, filesz, memsz, align = struct.unpack_from(
            "<IIQQQQQQ", data, phoff + i * phsize)
        if typ in (2, 3):
            raise ValueError("Dynamic or interpreter program headers are unsupported")
        if typ != 1:
            continue
        if virt != phys:
            raise ValueError("Load segment virtual and physical addresses must match")
        if filesz > memsz:
            raise ValueError("Load segment file size exceeds memory size")
        if offset + filesz > len(data):
            raise ValueError("Truncated load segment")
        if phys < base or phys + memsz > base + limit:
            raise ValueError("Load segment outside reserved image memory")
        if align not in (0, 1):
            if align & (align - 1) or virt % align != offset % align:
                raise ValueError("Invalid load segment alignment")
        if flags & 1 and phys <= entry and entry + 4 <= phys + filesz:
            entry_found = True
        if memsz:
            segments.append((phys - base, memsz, offset, filesz))
    segments.sort()
    previous_end = 0
    image_size = 0
    for address, memsz, offset, filesz in segments:
        if address < previous_end:
            raise ValueError("Overlapping load segments")
        previous_end = address + memsz
        if filesz:
            image_size = max(image_size, address + filesz)
    if not entry_found:
        raise ValueError("Missing executable file-backed ARM64 entry instruction")
    # Only allocate after all segments and their full memory ranges are checked.
    output = bytearray(image_size)
    for address, memsz, offset, filesz in segments:
        if filesz:
            output[address:address + filesz] = data[offset:offset + filesz]
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--base", type=lambda value: int(value, 0), default=BASE,
                        help="required entry/load base (default: 0x40080000)")
    parser.add_argument("--limit", type=lambda value: int(value, 0), default=LIMIT,
                        help="reserved memory size (default: 0x100000)")
    args = parser.parse_args()
    try:
        output = convert(args.source.read_bytes(), base=args.base, limit=args.limit)
        args.destination.write_bytes(output)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
