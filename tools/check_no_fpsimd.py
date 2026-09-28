# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail if an AArch64 ELF image contains floating-point or SIMD instructions.

Early boot code runs before anyone enables FP/SIMD (CPACR_EL1.FPEN or CPTR_ELx),
so any such instruction traps. Real Apple cores trap them; Unicorn does not.
Only code regions are scanned, using the ELF mapping symbols ($x = code,
$d = data) so literal-pool words are not mistaken for instructions.
Encoding classes are from the Arm A64 top-level decode table.
"""

import argparse
import struct
import sys
from pathlib import Path


def is_fpsimd(word: int) -> bool:
    op0 = (word >> 25) & 0xF
    if op0 & 0b0111 == 0b0111:        # x111: scalar FP and Advanced SIMD data processing
        return True
    if op0 & 0b0101 == 0b0100 and (word >> 26) & 1:  # x1x0 loads/stores with V=1
        return True
    return False


def code_ranges(data: bytes):
    """Yield (file_offset, size, vaddr) for executable code, split by mapping symbols."""
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError("expected a little-endian ELF64 file")
    shoff = struct.unpack_from("<Q", data, 0x28)[0]
    shentsize, shnum, _ = struct.unpack_from("<HHH", data, 0x3A)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
    symtab = next((s for s in sections if s[1] == 2), None)  # SHT_SYMTAB
    if symtab is None:
        raise ValueError("no symbol table: mapping symbols are required")
    strtab = sections[symtab[6]]
    marks = {}
    for i in range(symtab[5] // 24):
        name_off, info, _, shndx, value, _ = struct.unpack_from("<IBBHQQ", data, symtab[4] + i * 24)
        start = strtab[4] + name_off
        name = data[start:data.index(b"\0", start)]
        if name in (b"$x", b"$d") or name.startswith((b"$x.", b"$d.")):
            marks.setdefault(shndx, []).append((value, name[:2] == b"$x"))
    for index, (_, kind, flags, addr, offset, size, *_rest) in enumerate(sections):
        if kind != 1 or not flags & 0x4:  # PROGBITS with SHF_EXECINSTR
            continue
        points = sorted(marks.get(index, [(addr, True)]))
        if points[0][0] > addr:
            points.insert(0, (addr, True))
        for (start, is_code), (end, _) in zip(points, points[1:] + [(addr + size, False)]):
            if is_code and end > start:
                yield offset + (start - addr), end - start, start


def scan(path: Path):
    data = path.read_bytes()
    hits = []
    for offset, size, vaddr in code_ranges(data):
        for i in range(0, size - size % 4, 4):
            (word,) = struct.unpack_from("<I", data, offset + i)
            if is_fpsimd(word):
                hits.append((vaddr + i, word))
    return hits


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("elf", type=Path, nargs="+")
    args = parser.parse_args(argv)
    status = 0
    for path in args.elf:
        try:
            hits = scan(path)
        except (OSError, ValueError) as exc:
            print(f"check_no_fpsimd: {path}: {exc}", file=sys.stderr)
            return 2
        for vaddr, word in hits[:10]:
            print(f"{path}: FP/SIMD instruction {word:#010x} at {vaddr:#x}", file=sys.stderr)
        if hits:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
