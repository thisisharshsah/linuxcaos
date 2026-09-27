# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual ARM64 binary with a small PL011 register model.

This verifies instructions and console behavior, not Apple or QEMU hardware.
"""
from collections import deque
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

ROOT = Path(__file__).resolve().parents[1]
RAM = 0x40000000
ENTRY = 0x40080000
UART = 0x09000000


import struct
import sys

sys.path.insert(0, str(ROOT))
from tools.fb_export import export
from tools.generate_font import parse_font

FB = 0x40200000
FB_SIZE = 0x100000


def run_case(commands, expected, pre_write=None, count=200000, inspect=None):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(RAM, 0x200000)
    # Dirty RAM makes missing BSS initialization observable.
    cpu.mem_write(RAM, b"\xa5" * 0x200000)
    # Test-only framebuffer RAM; dirty so that unwritten pixels are detectable.
    cpu.mem_map(FB, FB_SIZE)
    cpu.mem_write(FB, b"\x5a" * FB_SIZE)
    cpu.mem_write(ENTRY, (ROOT / "build/monitor.bin").read_bytes())
    if pre_write:
        for addr, data in pre_write.items():
            cpu.mem_write(addr, data)
    cpu.mem_map(UART, 0x1000)
    incoming = deque(commands.encode("ascii"))
    outgoing = bytearray()

    def read(uc, access, address, size, value, data):
        if address == UART + 0x18:
            uc.mem_write(address, (0 if incoming else 0x10).to_bytes(4, "little"))
            if not incoming and outgoing.endswith(b"> "):
                uc.emu_stop()
        elif address == UART:
            uc.mem_write(address, incoming.popleft().to_bytes(4, "little"))

    def write(uc, access, address, size, value, data):
        if address == UART:
            outgoing.append(value & 0xff)

    cpu.hook_add(UC_HOOK_MEM_READ, read, begin=UART, end=UART + 0xfff)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write, begin=UART, end=UART + 0xfff)
    cpu.emu_start(ENTRY, ENTRY + 0x100000, count=count)
    transcript = outgoing.decode("ascii").replace("\r\n", "\n")
    assert not incoming, "Instruction budget exhausted before consuming input"
    assert "BSS cleared; serial ready." in transcript, transcript
    assert "FAIL:" not in transcript, transcript
    for item in expected:
        assert item in transcript, (item, transcript)
    assert transcript.endswith("> "), transcript
    if inspect:
        inspect(cpu, bytes(outgoing))
    return transcript


transcript = run_case("help\r\ninfo\nstatus\nnope\n", [
    "help  info  status", "ARM64 / QEMU virt", "Apple boot: unimplemented.",
    "Unknown command. Type help.",
])
assert transcript.count("> ") == 5, transcript
run_case("helx\bp\n", ["help  info  status"])
run_case("x" * 100 + "\nhelp\n", ["Line too long; command discarded.", "help  info  status"])
run_case("echo hello UI test\n", ["hello UI test"])
run_case("clear\n", ["\x1b[2J\x1b[H"])
run_case("poke 0x40100000 0x12345678\npeek 0x40100000\n", [
    "[0x0000000040100000] <= 0x12345678",
    "[0x0000000040100000] = 0x12345678",
])
run_case("peek 0x40100001\n", ["Error: address must be 4-byte aligned"])
run_case("peek\n", ["Usage: peek <hex_addr>"])
run_case("dump 0x40080000 0x10\n", ["0000000040080000: "])
run_case("regs\n", ["CurrentEL: EL", "DAIF:", "SP:"])
run_case("probe 0x40100001\n", ["Error: address must be 8-byte aligned"])
run_case("probe 0x40100000\n", ["Error: invalid probe magic"])

probe_record = struct.pack(
    "<8sII10Q",
    b"M1PROBE\x00", 1, 96, 1,
    0x10, 0x20, 0x30, 0x40,
    0x40104000, 0x40080000, 4, 0x3c0, 0,
)
run_case(
    "probe 0x40100000\n",
    [
        "M1PROBE record @ 0x0000000040100000",
        "captured (1)",
        "Entry PC:  0x0000000040080000",
        "Exception: EL1",
        "DAIF:      0x00000000000003c0",
    ],
    pre_write={0x40100000: probe_record},
)
(ROOT / "build/serial-test.log").write_text(transcript)

# --- Framebuffer console: compare emulator memory with an independent model. ---
GLYPHS = parse_font((ROOT / "tools/font8x16.txt").read_text(encoding="ascii"))
FG, BG = 0x00E0E0E0, 0x00102040


def model_cells(stream, cols, rows):
    """Reference console: the character grid the byte stream should leave."""
    # `clear` sends this sequence to serial only and erases the framebuffer.
    stream = stream.rsplit(b"\x1b[2J\x1b[H", 1)[-1]
    grid = [[" "] * cols for _ in range(rows)]
    col = row = 0

    def newline():
        nonlocal col, row
        col = 0
        if row + 1 < rows:
            row += 1
        else:
            grid.pop(0)
            grid.append([" "] * cols)

    for ch in stream.decode("ascii"):
        if ch == "\n":
            newline()
        elif ch == "\r":
            col = 0
        elif ch == "\b":
            col = max(col - 1, 0)
        elif " " <= ch <= "~":
            if col == cols:
                newline()
            grid[row][col] = ch
            col += 1
    return ["".join(r) for r in grid]


def expected_pixels(cells, width, height, scale):
    """Words per pixel row; the region below the last full text row stays dirty."""
    dirty = 0x5A5A5A5A
    out = []
    for y in range(height):
        text_row, gy = divmod(y // scale, 16)
        if text_row >= len(cells):
            out.append([BG] * width)  # cleared on attach, never drawn or scrolled
            continue
        row = []
        for x in range(width):
            cell, gx = divmod(x // scale, 8)
            if cell >= len(cells[text_row]):
                row.append(BG)
            else:
                bits = GLYPHS[ord(cells[text_row][cell])][gy]
                row.append(FG if bits & (0x80 >> gx) else BG)
        out.append(row)
    return out, dirty


def fb_case(width, height, stride, scale, commands, expect_lines, png=None):
    attach = f"fb 0x{FB:x} {width} {height} {stride}" + (f" {scale}" if scale != 1 else "")
    cols, rows = width // (8 * scale), height // (16 * scale)

    def inspect(cpu, raw):
        marker = (attach + "\r\n").encode("ascii")
        # Output after the attach command's own echo is mirrored to the framebuffer.
        stream = raw[raw.index(marker) + len(marker):]
        cells = model_cells(stream, cols, rows)
        for line in expect_lines:
            assert any(line in c for c in cells), (line, cells)
        mem = bytes(cpu.mem_read(FB, stride * height + 64))
        want, dirty = expected_pixels(cells, width, height, scale)
        for y in range(height):
            got = struct.unpack_from(f"<{width}I", mem, y * stride)
            assert list(got) == want[y], f"pixel row {y} differs; cells={cells}"
            pad = mem[y * stride + width * 4:(y + 1) * stride]
            assert pad == b"\x5a" * len(pad), f"stride padding written in row {y}"
        assert mem[stride * height:] == b"\x5a" * 64, "write past framebuffer end"
        if png:
            (ROOT / png).write_bytes(export(mem, width, height, stride, "png"))

    run_case(attach + "\n" + commands, [f"fb: attached {cols}x{rows} cells"],
             count=40_000_000, inspect=inspect)


# 40x4 cells with 64 bytes of row padding: prompt, typed commands, wrap, and scroll.
fb_case(320, 64, 1344, 1, "echo Hello M1\nhelx\bp\nfb\n",
        # The 62-character status line wraps at column 40.
        ["> fb", "fb: 0x0000000040200000 320x64 stride 134", "4 scale 1 (40x4 cells)"],
        png="build/fb-test.png")
# Scale 2 with a height that leaves a partial row, forcing repeated scrolls.
fb_case(320, 80, 1280, 2, "echo abcdefghijklmnopqrstuvwxyz0123456789\n",
        ["uvwxyz0123456789", ">"])
# `clear` erases the framebuffer rather than drawing the escape sequence.
fb_case(160, 32, 640, 1, "echo gone\nclear\n", [">"])
run_case(f"fb 0x{FB:x} 160 32 640\nfb off\nfb\necho serial only\n",
         ["fb: detached", "fb: off", "serial only"], count=10_000_000)

for command, message in [
    (f"fb 0x{FB + 2:x} 320 64 1280", "4-byte aligned"),
    (f"fb 0x{FB:x} 320 64 1000", "stride must be >= width*4"),
    (f"fb 0x{FB:x} 320 64 1280 9", "scale must be 1-8"),
    (f"fb 0x{FB:x} 4 64 1280", "geometry out of range"),
    (f"fb 0x{FB:x} 320 99999 1280", "geometry out of range"),
    ("fb 0x40000000 320 2000 1280", "overlaps the monitor"),
    ("fb 0x40070000 320 64 1280", "overlaps the monitor"),  # ends inside the image
    ("fb 0x40081000 320 64 1280", "overlaps the monitor"),  # starts inside the image
    (f"fb 0x{FB:x} 320", "Usage: fb"),
    (f"fb 0x{FB:x} 320 64 1280 2 7", "Usage: fb"),
    (f"fb 0x{FB:x} 32O 64 1280", "Usage: fb"),
]:
    run_case(command + "\nfb\n", [message, "fb: off"])

print("PASS: ARM64 startup, dirty BSS, commands, CRLF, backspace, overflow recovery, UI features "
      "(echo, clear, peek, poke, dump, regs, probe), framebuffer console (pixels, stride, scale, "
      "wrap, scroll, clear, validation)")

