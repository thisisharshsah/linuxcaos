# M1 screen probe

The first experiment designed for a single Mac with no second computer or
debug cable. It supports milestone M1 of the [living blueprint](BLUEPRINT.md):
a repeatable, externally visible marker from our own code on the physical M1.
**It has not been run on the M1.** Everything below the "Evidence" heading
comes from host and Unicorn tests with invented inputs.

## What it does

1. Saves the incoming `x0`–`x3`, stack pointer, its own entry address,
   `CurrentEL`, and `DAIF` before touching memory, then masks interrupts.
2. Switches to a 16 KB stack inside its own image. The image is fully
   file-backed (no BSS), so loading the raw bytes is all it needs.
3. Treats `x0` as the `boot_args` pointer (documented by Asahi, see
   [RESEARCH.md](RESEARCH.md)): if `x0` is non-zero and 8-byte aligned, it copies
   736 bytes with byte loads and validates them with [bootargs.c](../src/bootargs.c).
   It never follows any pointer inside `boot_args`.
4. If the framebuffer description is plausible (depth 30 or 32, aligned, sane
   size and stride), it draws red, green, blue, and white bars across the top,
   then a text report of the entry state and `boot_args` fields.
5. Parks forever in a `wfe` loop. It never returns to the firmware.

If any check fails it draws nothing and parks, so a black screen means "input
rejected or crashed". The colour bars show whether the pixel-format guess is
right: `x2r10g10b10` for depth 30 is inferred from documentation, not measured.

## Safety properties

- **Memory:** reads only its own image, the 736 `boot_args` bytes, and the
  framebuffer; writes only its own image and the framebuffer. No device
  registers, NVRAM, or flash are accessed. Writing RAM or the framebuffer
  cannot persist across a power cycle.
- **Alignment:** built with `-mstrict-align`; with the MMU off all memory is
  Device memory, where unaligned accesses fault.
- **Position independence:** the firmware chooses the load address (it is
  shifted by kASLR). The build links the probe at two bases and requires
  byte-identical output, and it is compiled without jump tables. The emulator
  test runs the same bytes at three addresses, one only page aligned.
- **Reset vector:** Asahi reports that iBoot locks the boot CPU's reset vector
  to the top of the entry page. The probe never returns, so it does not rely on
  or disturb that page afterwards.

## Evidence

`make test` runs [emulate_screen_probe.py](../tests/emulate_screen_probe.py):

- Three load addresses, two pixel formats, scales 1 and 2. Colour bars and every
  text pixel are compared with an independent Python model, and stride padding
  must stay untouched.
- Every memory access is recorded; any read or write outside the allowed
  regions, or any unaligned access, fails the test. The incoming SP points at
  unmapped memory, so any use of the firmware stack fails.
- Seven invalid inputs (null or misaligned `x0`, unknown revision, depth 24,
  short stride, misaligned framebuffer, zero memory size) must leave the
  framebuffer untouched.
- [test_bootargs_c.py](../tests/test_bootargs_c.py) runs the same C parser on
  the host and cross-checks it against the independent Python decoder.
- Mutation checks (clean builds): a pointer table, swapped bar colours, a read
  past `boot_args`, swapped EL/DAIF record, use of the firmware stack, and an
  accepted misaligned framebuffer were each caught.

`make hvf-test` also runs the same image on this Mac's real CPU cores at EL1 with
the MMU off, inside a Hypervisor.framework VM, at three load addresses; every
framebuffer pixel must match. This exercises real instruction behaviour,
including traps for FP/SIMD and Device-memory alignment.

Limits: neither harness runs at EL2 or under iBoot, and the inputs are invented.
They cannot show what the real firmware passes or how it maps memory.

## Hardware procedure

The owner-facing checklist is [FIRST_HARDWARE_RUN.md](FIRST_HARDWARE_RUN.md), and
`make hw-kit` assembles the payload, its SHA-256, provenance, and a report
template. The virtual address given to `kmutil` for both the lowest address and
the entry point is `0xfffffe0007004000`, XNU's `ARM64_LINK_ADDR`; this is a
reasoned choice, not a tested one. Only a separate ProbeOS installation is set
to Permissive Security (`bputil -n -v <UUID>`); the everyday macOS keeps Full
Security.

A black screen is also a result: record it. It means `x0` was not a valid
`boot_args`, the framebuffer description failed validation, or the probe
faulted before drawing.
