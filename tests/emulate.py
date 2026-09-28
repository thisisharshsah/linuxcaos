# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual ARM64 binary with a small PL011 register model.

This verifies instructions and console behavior, not Apple or QEMU hardware.
"""
from collections import deque
from pathlib import Path
from unicorn import (Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ,
                     UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED, UC_MEM_WRITE_UNMAPPED,
                     UC_ERR_EXCEPTION, UC_ERR_READ_UNMAPPED, UC_ERR_WRITE_UNMAPPED)
from unicorn.arm64_const import (UC_ARM64_REG_CP_REG, UC_ARM64_REG_ELR_EL1,
                                 UC_ARM64_REG_ESR_EL1, UC_ARM64_REG_FAR_EL1,
                                 UC_ARM64_REG_PC, UC_ARM64_REG_PSTATE,
                                 UC_ARM64_REG_VBAR_EL1, UC_ARM64_REG_X0,
                                 UC_ARM64_REG_X29, UC_ARM64_REG_X30)

ROOT = Path(__file__).resolve().parents[1]
RAM = 0x40000000
ENTRY = 0x40080000
UART = 0x09000000


import struct
import sys

sys.path.insert(0, str(ROOT))
from tools.fb_export import export

FB = 0x40200000
FB_SIZE = 0x100000
SPSR_EL1 = (4, 0, 3, 0, 0)  # CRn, CRm, op0, op1, op2 for Unicorn's CP_REG access
EXCEPTIONS = []  # (esr, elr, far) for each exception taken in the latest run_case
FAULT_REGS = []  # x0-x30 at each exception, for checking the printed report


def take_exception(uc, esr, far):
    """Model AArch64 synchronous exception entry to EL1 using SP_EL1.

    Unicorn stops emulation instead of vectoring, so the harness performs the
    architectural steps: save PC/PSTATE, set ESR/FAR, mask DAIF, and branch to
    VBAR_EL1 + 0x200. This tests our handler code, not real exception entry.
    """
    pc = uc.reg_read(UC_ARM64_REG_PC)
    pstate = uc.reg_read(UC_ARM64_REG_PSTATE)
    assert (pstate >> 2) & 3 == 1, "harness only models exceptions taken at EL1"
    uc.reg_write(UC_ARM64_REG_ELR_EL1, pc)
    uc.reg_write(UC_ARM64_REG_CP_REG, (*SPSR_EL1, pstate & 0xFFFFFFFF))
    uc.reg_write(UC_ARM64_REG_ESR_EL1, esr)
    uc.reg_write(UC_ARM64_REG_FAR_EL1, far)
    uc.reg_write(UC_ARM64_REG_PSTATE, (pstate & ~0x3CF) | 0x3C5)
    EXCEPTIONS.append((esr, pc, far))
    regs = [uc.reg_read(UC_ARM64_REG_X0 + i) for i in range(29)]
    FAULT_REGS.append(regs + [uc.reg_read(UC_ARM64_REG_X29), uc.reg_read(UC_ARM64_REG_X30)])
    return uc.reg_read(UC_ARM64_REG_VBAR_EL1) + 0x200


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

    unmapped = []

    def on_unmapped(uc, access, address, size, value, data):
        unmapped.append((address, access == UC_MEM_WRITE_UNMAPPED))
        return False

    cpu.hook_add(UC_HOOK_MEM_READ, read, begin=UART, end=UART + 0xfff)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write, begin=UART, end=UART + 0xfff)
    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    EXCEPTIONS.clear()
    FAULT_REGS.clear()
    pc = ENTRY
    while True:
        try:
            cpu.emu_start(pc, ENTRY + 0x100000, count=count)
            break
        except UcError as exc:
            assert len(EXCEPTIONS) < 8, "exception loop"
            fault_pc = cpu.reg_read(UC_ARM64_REG_PC)
            if exc.errno in (UC_ERR_READ_UNMAPPED, UC_ERR_WRITE_UNMAPPED):
                address, is_write = unmapped.pop()
                # EC 0x25 data abort (same EL), IL=1, WnR, DFSC 0x10 external abort.
                esr = (0x25 << 26) | (1 << 25) | (int(is_write) << 6) | 0x10
                pc = take_exception(cpu, esr, address)
            elif exc.errno == UC_ERR_EXCEPTION:
                insn = int.from_bytes(cpu.mem_read(fault_pc, 4), "little")
                assert insn & 0xFFE0001F == 0xD4200000, f"unexpected exception at {fault_pc:#x}"
                # EC 0x3c BRK, IL=1, ISS = the BRK immediate.
                pc = take_exception(cpu, (0x3C << 26) | (1 << 25) | ((insn >> 5) & 0xFFFF), 0)
            else:
                raise
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
from tests.fbmodel import encode, model_cells, render_cells  # noqa: E402

FG_RGB, BG_RGB = 0x00E0E0E0, 0x00102040


def expected_pixels(cells, width, height, scale, pixel="x8r8g8b8"):
    """Words per pixel row, plus the dirty fill value for untouched memory."""
    return render_cells(cells, width, height, scale, encode(FG_RGB, pixel),
                        encode(BG_RGB, pixel)), 0x5A5A5A5A


def fb_case(width, height, stride, scale, commands, expect_lines, png=None, pixel="x8r8g8b8"):
    attach = f"fb 0x{FB:x} {width} {height} {stride}" + (f" {scale}" if scale != 1 else "")
    if pixel != "x8r8g8b8":
        attach += f" {pixel}"
    cols, rows = width // (8 * scale), height // (16 * scale)

    def inspect(cpu, raw):
        marker = (attach + "\r\n").encode("ascii")
        # Output after the attach command's own echo is mirrored to the framebuffer.
        stream = raw[raw.index(marker) + len(marker):]
        cells = model_cells(stream, cols, rows)
        for line in expect_lines:
            assert any(line in c for c in cells), (line, cells)
        mem = bytes(cpu.mem_read(FB, stride * height + 64))
        want, dirty = expected_pixels(cells, width, height, scale, pixel)
        for y in range(height):
            got = struct.unpack_from(f"<{width}I", mem, y * stride)
            assert list(got) == want[y], f"pixel row {y} differs; cells={cells}"
            pad = mem[y * stride + width * 4:(y + 1) * stride]
            assert pad == b"\x5a" * len(pad), f"stride padding written in row {y}"
        assert mem[stride * height:] == b"\x5a" * 64, "write past framebuffer end"
        if png:
            (ROOT / png).write_bytes(export(mem, width, height, stride, "png", pixel=pixel))

    run_case(attach + "\n" + commands, [f"fb: attached {cols}x{rows} cells"],
             count=40_000_000, inspect=inspect)


# 40x4 cells with 64 bytes of row padding: prompt, typed commands, wrap, and scroll.
fb_case(320, 64, 1344, 1, "echo Hello M1\nhelx\bp\nfb\n",
        # The 62-character status line wraps at column 40.
        ["> fb", "fb: 0x0000000040200000 320x64 stride 134", "4 scale 1 x8r8g8b8 (40x4 cell"],
        png="build/fb-test.png")
# Backspace stays visible on a taller screen: "helx<BS>p" must read "help".
fb_case(320, 160, 1280, 1, "echo 1\nhelx\bp\n", ["> help", "help  info  status"])
# Scale 2 with a height that leaves a partial row, forcing repeated scrolls.
fb_case(320, 80, 1280, 2, "echo abcdefghijklmnopqrstuvwxyz0123456789\n",
        ["uvwxyz0123456789", ">"])
# 10-bit-per-channel format, as Apple Silicon documentation suggests (unverified here).
fb_case(320, 64, 1280, 1, "echo ten bit\n", ["ten bit"], pixel="x2r10g10b10",
        png="build/fb-test-x2r10g10b10.png")
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
    (f"fb 0x{FB:x} 320 64 1280 2 rgb565", "Usage: fb"),
    (f"fb 0x{FB:x} 320 64 1280 x2r10g10b10 2", "Usage: fb"),
]:
    run_case(command + "\nfb\n", [message, "fb: off"])

# --- Linux Image header inspection (synthetic header, not a real kernel). ---
kernel_header = struct.pack("<IIQQQQQQII", 0x91005A4D, 0x14000000, 0, 0x1A00000, 0b1100,
                            0, 0, 0, 0x644D5241, 0x40)
run_case("kimage 0x40100000\n", [
    "ARM64 Linux Image @ 0x0000000040100000", "text_offset: 0x0000000000000000",
    "image_size:  0x0000000001a00000", "page size:   16 KB", "placement:   anywhere (48-bit)",
], pre_write={0x40100000: kernel_header})
run_case("kimage 0x40100000\n", ["Not a usable Linux Image: bad magic"],
         pre_write={0x40100000: b"\x1f\x8b\x08\x00" + bytes(60)})
run_case("kimage 0x40100000\n", ["image_size is 0"],
         pre_write={0x40100000: kernel_header[:16] + bytes(8) + kernel_header[24:]})
run_case("kimage 0x40100004\nkimage\n", ["8-byte aligned", "Usage: kimage"])

# --- Exception vectors: report, recover, and keep working. ---
t = run_case("regs\n", ["VBAR:      0x"])
vbar = int(t.split("VBAR:      0x")[1][:16], 16)
assert vbar and vbar % 0x800 == 0 and ENTRY <= vbar < ENTRY + 0x100000, hex(vbar)

t = run_case("trap\nstatus\nhelp\n", [
    "*** EXCEPTION: synchronous from current EL with SP_ELx, taken to EL1 ***",
    "EC 0x3c (BRK (AArch64))", "FAR:  not valid for this class",
    "Recovered; monitor restarted with a fresh stack.",
    "Exceptions recovered: 1", "help  info  status",
])
(esr, elr, _), = EXCEPTIONS
assert esr & 0xFFFF == 0x4D31, hex(esr)
assert f"ESR:  0x{esr:016x}" in t and f"ELR:  0x{elr:016x}" in t, t
for i, value in enumerate(FAULT_REGS[0]):
    assert f"x{i:02d} 0x{value:016x}" in t, (i, hex(value), t)
spsr = int(t.split("SPSR: 0x")[1][:16], 16)
assert spsr & 0x3CF == 0x3C5, hex(spsr)  # interrupted state: EL1h, DAIF masked
# Stack reset: repeated recoveries leave SP unchanged (no growth per exception).
t = run_case("trap\nregs\ntrap\ntrap\nregs\n", [])
sps = [line for line in t.splitlines() if line.startswith("SP:        ")]
assert len(sps) == 2 and sps[0] == sps[1], sps

# A read of unmapped memory becomes a data abort with the faulting address.
t = run_case("peek 0x50000000\ntrap\nstatus\n", [
    "EC 0x25 (data abort, same EL)", "FAR:  0x0000000050000000",
    "Exceptions recovered: 2",
])
assert len(EXCEPTIONS) == 2 and EXCEPTIONS[0][2] == 0x50000000, EXCEPTIONS
# A write fault sets ESR.WnR (bit 6).
run_case("poke 0x50000000 0x1\n", ["EC 0x25 (data abort, same EL)"])
assert EXCEPTIONS[0][0] & (1 << 6), hex(EXCEPTIONS[0][0])

# Reports are mirrored to an attached framebuffer.
def fb_shows_report(cpu, raw):
    assert bytes(cpu.mem_read(FB, 4)) != b"\x5a" * 4, "framebuffer untouched"
run_case(f"fb 0x{FB:x} 320 64 1280\ntrap\n", ["Recovered;"], count=40_000_000,
         inspect=fb_shows_report)

print("PASS: ARM64 startup, dirty BSS, commands, CRLF, backspace, overflow recovery, UI features "
      "(echo, clear, peek, poke, dump, regs, probe), framebuffer console (pixels, stride, scale, "
      "wrap, scroll, clear, validation), kimage header checks, exception report and recovery (BRK, data abort)")

