# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the M1 screen probe in Unicorn with synthetic boot_args and framebuffers.

Every value here is invented test data, not an observation of any Mac. Unicorn
runs at EL1 with no MMU model, so this checks the probe's instructions,
position independence, memory discipline, and drawing; it cannot show how the
real firmware enters it.
"""
import ctypes
import struct
import sys
from pathlib import Path

from unicorn import (Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ,
                     UC_HOOK_MEM_WRITE)
from unicorn.arm64_const import (UC_ARM64_REG_PC, UC_ARM64_REG_PSTATE, UC_ARM64_REG_SP,
                                 UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
                                 UC_ARM64_REG_X3)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fbmodel import encode, model_cells, render_cells  # noqa: E402
from tests.test_inspect_bootargs import BootArgs, BootVideo  # noqa: E402
from tools.fb_export import export  # noqa: E402

IMAGE = (ROOT / "build/screen-probe.bin").read_bytes()
WFE = struct.pack("<I", 0xD503205F)
PARK = IMAGE.index(WFE)  # first WFE: the park loop in screen_probe_entry.S
DIRTY = 0x5A
BOOTARGS_SIZE = 0x2E0


def make_bootargs(fb_base, width, height, stride, depth, **overrides):
    args = BootArgs(Revision=2, Version=2, virtBase=0xFFFFFE0007004000,
                    physBase=0x800000000, memSize=0x1E0000000, topOfKernelData=0x812340000,
                    deviceTreeP=0xFFFFFE0010000000, deviceTreeLength=0x40000,
                    CommandLine=b"test-only args", bootFlags=0)
    args.Video = BootVideo(fb_base, 1, stride, width, height, depth)
    for name, value in overrides.items():
        setattr(args, name, value)
    return bytes(args)


def expected_text(state, args):
    b = BootArgs.from_buffer_copy(args)
    v = b.Video
    depth = v.v_depth & 0xFF
    fmt = {30: "x2r10g10b10", 32: "x8r8g8b8"}[depth]
    h = lambda value: f"0x{value:016x}"
    in_ram = v.v_baseAddr < b.physBase + b.memSize and \
        v.v_baseAddr + v.v_rowBytes * v.v_height > b.physBase
    lines = [
        "Independent M1 screen probe v1 (GPL-2.0-or-later)", "",
        f"entry pc     {h(state['pc'])}",
        f"CurrentEL    EL{(state['el'] >> 2) & 3}",
        f"DAIF         {h(state['daif'])}",
        f"incoming sp  {h(state['sp'])}",
    ] + [f"x{i}           {h(state['x'][i])}" for i in range(4)] + [
        "", f"boot_args    revision {b.Revision} version {b.Version}",
        f"virt_base    {h(b.virtBase)}", f"phys_base    {h(b.physBase)}",
        f"mem_size     {h(b.memSize)}", f"top_of_kdata {h(b.topOfKernelData)}",
        f"device_tree  {h(b.deviceTreeP)}", f"boot_flags   {h(b.bootFlags)}",
        f"video        {h(v.v_baseAddr)} {v.v_width}x{v.v_height} stride {v.v_rowBytes} "
        f"depth {depth} {fmt}" + (" (inside RAM range)" if in_ram else ""),
        "command line " + b.CommandLine.decode()[:120], "",
        "Bars above: red, green, blue, white if the pixel format is right.",
        "Parked. Photograph this screen, then hold the power button to turn off.", "",
    ]
    return "\n".join(lines).encode()


def run(base, args_at, args, fb_base, fb_size, x0=None, daif=0x3C0, png=None):
    """Load the probe at `base`, run to its park loop, return (cpu, accesses)."""
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(base, 0x100000)
    cpu.mem_write(base, IMAGE)
    cpu.mem_map(args_at & ~0xFFF, 0x1000)
    cpu.mem_write(args_at, args)
    cpu.mem_map(fb_base, fb_size)
    cpu.mem_write(fb_base, bytes([DIRTY]) * fb_size)
    x = [args_at if x0 is None else x0, 0x1111, 0x2222, 0x3333]
    for reg, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3), x):
        cpu.reg_write(reg, value)
    cpu.reg_write(UC_ARM64_REG_SP, 0xDEAD0000)  # unmapped: the probe must not use it
    cpu.reg_write(UC_ARM64_REG_PSTATE, (cpu.reg_read(UC_ARM64_REG_PSTATE) & ~0x3C0) | daif)
    accesses = []
    cpu.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, d: accesses.append(("r", addr, size)))
    cpu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, d: accesses.append(("w", addr, size)))
    cpu.hook_add(UC_HOOK_CODE, lambda uc, addr, size, d: uc.emu_stop(),
                 begin=base + PARK, end=base + PARK)
    cpu.emu_start(base, 0, count=200_000_000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == base + PARK, "probe did not reach its park loop"
    state = {"x": x, "sp": 0xDEAD0000, "pc": base, "el": 4, "daif": daif}
    return cpu, accesses, state


def check_accesses(accesses, base, args_at, fb_base, fb_size):
    image = (base, base + len(IMAGE))
    allowed_read = [image, (args_at, args_at + BOOTARGS_SIZE), (fb_base, fb_base + fb_size)]
    allowed_write = [image, (fb_base, fb_base + fb_size)]
    for kind, addr, size in accesses:
        ranges = allowed_read if kind == "r" else allowed_write
        assert any(lo <= addr and addr + size <= hi for lo, hi in ranges), \
            f"{kind} of {size} bytes at {addr:#x} outside the allowed regions"
        assert addr % size == 0, f"unaligned {kind} at {addr:#x} (Device memory would fault)"


def check_screen(mem, width, height, stride, depth, state, args, png=None):
    """Compare a framebuffer dump with the expected bars and report, pixel for pixel."""
    pixel = {30: "x2r10g10b10", 32: "x8r8g8b8"}[depth & 0xFF]
    scale = 2 if width >= 1600 else 1
    bar = height // 16
    colors = [0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF]
    for y in range(bar):
        row = struct.unpack_from(f"<{width}I", mem, y * stride)
        want = [encode(colors[(x * 4) // width], pixel) for x in range(width)]
        assert list(row) == want, f"colour bar row {y} differs"
    cols, rows = width // (8 * scale), (height - bar) // (16 * scale)
    cells = model_cells(expected_text(state, args), cols, rows)
    want = render_cells(cells, width, height - bar, scale, encode(0xFFFFFF, pixel), 0)
    for y in range(height - bar):
        row = struct.unpack_from(f"<{width}I", mem, (bar + y) * stride)
        assert list(row) == want[y], f"text row {y} differs; cells={cells}"
    for y in range(height):
        pad = mem[y * stride + width * 4:(y + 1) * stride]
        assert pad == bytes([DIRTY]) * len(pad), f"stride padding written in row {y}"
    if png:
        (ROOT / png).write_bytes(export(mem, width, height, stride, "png", pixel=pixel))


def case(base, width, height, stride, depth, png=None, daif=0x3C0):
    fb_base, args_at = 0x9E0000000, 0x812300040
    fb_size = (stride * height + 0xFFF) & ~0xFFF
    args = make_bootargs(fb_base, width, height, stride, depth)
    cpu, accesses, state = run(base, args_at, args, fb_base, fb_size, daif=daif)
    check_accesses(accesses, base, args_at, fb_base, fb_size)
    mem = bytes(cpu.mem_read(fb_base, stride * height))
    check_screen(mem, width, height, stride, depth, state, args, png)


def untouched(base, args, x0=None):
    fb_base, args_at, fb_size = 0x9E0000000, 0x812300040, 0x100000
    cpu, accesses, _ = run(base, args_at, args, fb_base, fb_size, x0=x0)
    check_accesses(accesses, base, args_at, fb_base, fb_size)
    assert bytes(cpu.mem_read(fb_base, fb_size)) == bytes([DIRTY]) * fb_size, "drew despite bad input"


def main():
    # The same bytes at three load addresses, including one that is only page aligned.
    case(0x40000000, 800, 480, 3264, 0x00020000 | 30, png="build/screen-probe-test.png")
    case(0x812344000, 640, 400, 2560, 32, daif=0)
    case(0x1000000000, 1600, 208, 6400 + 128, 30)

    # Bad input: no drawing at all, and still no stray memory accesses.
    good = make_bootargs(0x9E0000000, 320, 64, 1280, 30)
    untouched(0x40000000, good, x0=0)
    untouched(0x40000000, good, x0=0x812300044)  # misaligned x0
    untouched(0x40000000, make_bootargs(0x9E0000000, 320, 64, 1280, 30, Revision=3))
    untouched(0x40000000, make_bootargs(0x9E0000000, 320, 64, 1280, 24))
    untouched(0x40000000, make_bootargs(0x9E0000000, 320, 64, 1000, 30))  # stride < width * 4
    untouched(0x40000000, make_bootargs(0x9E0000002, 320, 64, 1280, 30))  # misaligned framebuffer
    untouched(0x40000000, make_bootargs(0x9E0000000, 320, 64, 1280, 30, memSize=0))

    print("PASS: screen probe at three load addresses, entry-state and boot_args report, "
          "colour bars, x8r8g8b8/x2r10g10b10, scale 1-2, bounded memory accesses, "
          "rejection of invalid boot_args")


if __name__ == "__main__":
    main()
