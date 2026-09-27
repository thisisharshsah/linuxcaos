# SPDX-License-Identifier: GPL-2.0-or-later
"""Build and inspect flattened device tree (DTB) files.

Implements the binary format of the Devicetree Specification v0.4, section 5
(https://www.devicetree.org/specifications/): big-endian header, memory
reservation block, structure block, and strings block. `minimal_linux_tree`
describes only memory and /chosen; a real M1 tree also needs CPUs, interrupt
controller, timer, and devices, none of which are known or generated here.
"""

import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path


MAGIC = 0xD00DFEED
VERSION = 17
LAST_COMPATIBLE_VERSION = 16
HEADER = struct.Struct(">10I")
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9
LINUX_DTB_LIMIT = 2 * 1024 * 1024  # arm64 booting.rst: DTB must not exceed 2 MB


@dataclass
class Node:
    name: str = ""
    props: dict = field(default_factory=dict)  # name -> bytes, in insertion order
    children: list = field(default_factory=list)

    def child(self, name):
        return next(c for c in self.children if c.name == name)


def u32(*values) -> bytes:
    return struct.pack(f">{len(values)}I", *values)


def u64(*values) -> bytes:
    return struct.pack(f">{len(values)}Q", *values)


def string(value: str) -> bytes:
    return value.encode("ascii") + b"\0"


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def build_dtb(root: Node, reserve=(), boot_cpuid: int = 0) -> bytes:
    strings, offsets = bytearray(), {}
    struct_block = bytearray()

    def name_offset(name):
        if name not in offsets:
            offsets[name] = len(strings)
            strings.extend(string(name))
        return offsets[name]

    def emit(node):
        if "/" in node.name or "\0" in node.name:
            raise ValueError(f"invalid node name: {node.name!r}")
        struct_block.extend(u32(BEGIN_NODE) + _pad4(string(node.name)))
        for name, value in node.props.items():
            struct_block.extend(u32(PROP, len(value), name_offset(name)) + _pad4(value))
        for child in node.children:
            emit(child)
        struct_block.extend(u32(END_NODE))

    if root.name:
        raise ValueError("root node name must be empty")
    emit(root)
    struct_block.extend(u32(END))
    rsvmap = b"".join(u64(a, s) for a, s in reserve) + u64(0, 0)

    off_rsvmap = HEADER.size + (-HEADER.size % 8)  # 8-byte aligned
    off_struct = off_rsvmap + len(rsvmap)          # 4-byte aligned
    off_strings = off_struct + len(struct_block)
    total = off_strings + len(strings)
    header = HEADER.pack(MAGIC, total, off_struct, off_strings, off_rsvmap, VERSION,
                         LAST_COMPATIBLE_VERSION, boot_cpuid, len(strings), len(struct_block))
    blob = header + b"\0" * (off_rsvmap - HEADER.size) + rsvmap + bytes(struct_block) + bytes(strings)
    assert len(blob) == total
    return blob


def parse_dtb(data: bytes):
    """Return (root, reserve list, boot_cpuid); raises ValueError on malformed input."""
    if len(data) < HEADER.size:
        raise ValueError("truncated header")
    (magic, total, off_struct, off_strings, off_rsvmap, version, last_comp,
     boot_cpuid, size_strings, size_struct) = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic:#x}")
    if last_comp > VERSION or version < LAST_COMPATIBLE_VERSION:
        raise ValueError(f"unsupported version {version} (last compatible {last_comp})")
    if total > len(data):
        raise ValueError(f"totalsize {total} exceeds {len(data)} available bytes")
    if off_rsvmap % 8 or off_struct % 4:
        raise ValueError("misaligned block offset")
    for off, size in ((off_struct, size_struct), (off_strings, size_strings)):
        if off < HEADER.size or off + size > total:
            raise ValueError("block outside totalsize")

    reserve, pos = [], off_rsvmap
    while True:
        if pos + 16 > total:
            raise ValueError("unterminated memory reservation block")
        address, size = struct.unpack_from(">QQ", data, pos)
        pos += 16
        if address == 0 and size == 0:
            break
        reserve.append((address, size))

    strings = data[off_strings:off_strings + size_strings]
    end_struct = off_struct + size_struct
    pos, stack, root = off_struct, [], None

    def word():
        nonlocal pos
        if pos + 4 > end_struct:
            raise ValueError("structure block truncated")
        (value,) = struct.unpack_from(">I", data, pos)
        pos += 4
        return value

    def cstring(buf, start, limit):
        end = buf.find(b"\0", start, limit)
        if end < 0:
            raise ValueError("unterminated string")
        return buf[start:end].decode("ascii"), end

    while True:
        token = word()
        if token == BEGIN_NODE:
            name, end = cstring(data, pos, end_struct)
            pos = end + 1 + (-(end + 1 - off_struct) % 4)
            node = Node(name)
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("multiple root nodes")
            stack.append(node)
        elif token == END_NODE:
            if not stack:
                raise ValueError("unbalanced END_NODE")
            stack.pop()
        elif token == PROP:
            if not stack:
                raise ValueError("property outside a node")
            length, name_off = word(), word()
            if name_off >= len(strings) or pos + length > end_struct:
                raise ValueError("property out of range")
            name, _ = cstring(strings, name_off, len(strings))
            stack[-1].props[name] = data[pos:pos + length]
            pos += length + (-length % 4)
        elif token == NOP:
            continue
        elif token == END:
            if stack or root is None:
                raise ValueError("END before all nodes closed")
            return root, reserve, boot_cpuid
        else:
            raise ValueError(f"unknown token {token:#x}")


def minimal_linux_tree(memory_base, memory_size, bootargs="", initrd=None,
                       model="unvalidated minimal tree", stdout_path=None) -> Node:
    """Root with 64-bit cells, one memory node, and /chosen for Linux."""
    root = Node("", {"#address-cells": u32(2), "#size-cells": u32(2), "model": string(model)})
    root.children.append(Node(f"memory@{memory_base:x}", {
        "device_type": string("memory"), "reg": u64(memory_base, memory_size)}))
    chosen = Node("chosen", {})
    if bootargs:
        chosen.props["bootargs"] = string(bootargs)
    if stdout_path:
        chosen.props["stdout-path"] = string(stdout_path)
    if initrd:
        start, end = initrd
        chosen.props["linux,initrd-start"] = u64(start)
        chosen.props["linux,initrd-end"] = u64(end)
    root.children.append(chosen)
    return root


def format_value(value: bytes) -> str:
    if value and value[-1:] == b"\0" and all(32 <= b < 127 for b in value[:-1].replace(b"\0", b"")):
        parts = value[:-1].split(b"\0")
        if all(parts):
            return ", ".join(f'"{p.decode()}"' for p in parts)
    if value and len(value) % 4 == 0:
        return "<" + " ".join(f"{v:#x}" for v in struct.unpack(f">{len(value) // 4}I", value)) + ">"
    return "[" + " ".join(f"{b:02x}" for b in value) + "]"


def format_tree(node: Node, indent: int = 0) -> str:
    pad = "\t" * indent
    lines = [f"{pad}{node.name or '/'} {{"]
    for name, value in node.props.items():
        lines.append(f"{pad}\t{name}" + (f" = {format_value(value)};" if value else ";"))
    for child in node.children:
        lines.append(format_tree(child, indent + 1))
    lines.append(f"{pad}}};")
    return "\n".join(lines)


def _range(text: str):
    start, _, size = text.partition(":")
    return int(start, 0), int(size, 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write a minimal memory + /chosen tree")
    build.add_argument("output", type=Path)
    build.add_argument("--memory", type=_range, required=True, help="BASE:SIZE")
    build.add_argument("--bootargs", default="")
    build.add_argument("--stdout-path")
    build.add_argument("--initrd", type=_range, help="START:SIZE")
    dump = sub.add_parser("dump", help="print a DTB as source-like text")
    dump.add_argument("dtb", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            initrd = None
            if args.initrd:
                initrd = (args.initrd[0], args.initrd[0] + args.initrd[1])
            blob = build_dtb(minimal_linux_tree(*args.memory, args.bootargs, initrd,
                                                stdout_path=args.stdout_path))
            if len(blob) > LINUX_DTB_LIMIT:
                raise ValueError("DTB exceeds the 2 MB arm64 limit")
            args.output.write_bytes(blob)
        else:
            root, reserve, cpu = parse_dtb(args.dtb.read_bytes())
            for address, size in reserve:
                print(f"/memreserve/ {address:#x} {size:#x};")
            print(format_tree(root))
    except (OSError, ValueError) as exc:
        print(f"fdt: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
