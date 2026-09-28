# SPDX-License-Identifier: GPL-2.0-or-later
"""Pack a minimal Linux initramfs (cpio "newc" format) around one init binary.

Contents: /init, /proc, and /dev with console (5,1) and kmsg (1,11) device
nodes, so init can log through /dev/kmsg before any filesystem is mounted.
Format per the kernel's Documentation/driver-api/early-userspace/buffer-format.rst.
"""

import argparse
from pathlib import Path

S_IFDIR, S_IFREG, S_IFCHR = 0o040000, 0o100000, 0o020000


def entry(ino: int, name: str, mode: int, data: bytes = b"", rdev=(0, 0)) -> bytes:
    name_bytes = name.encode() + b"\0"
    nlink = 2 if mode & S_IFDIR else 1
    fields = [ino, mode, 0, 0, nlink, 0, len(data), 0, 0, rdev[0], rdev[1], len(name_bytes), 0]
    header = b"070701" + b"".join(f"{v:08x}".encode() for v in fields)
    out = header + name_bytes
    out += b"\0" * (-len(out) % 4)
    out += data + b"\0" * (-len(data) % 4)
    return out


def build(init: bytes) -> bytes:
    parts = [
        entry(1, "dev", S_IFDIR | 0o755),
        entry(2, "dev/console", S_IFCHR | 0o600, rdev=(5, 1)),
        entry(3, "dev/kmsg", S_IFCHR | 0o644, rdev=(1, 11)),
        entry(4, "proc", S_IFDIR | 0o755),
        entry(5, "init", S_IFREG | 0o755, init),
        entry(0, "TRAILER!!!", 0),
    ]
    blob = b"".join(parts)
    return blob + b"\0" * (-len(blob) % 512)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("init", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    args.output.write_bytes(build(args.init.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
