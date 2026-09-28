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

Limits: Unicorn runs at EL1 without an MMU or cache model, and the inputs are
invented. It cannot show what the real firmware passes or how it maps memory.

## Hardware procedure (owner decision; not yet validated)

This changes boot security settings for a separate macOS installation. It is
written down for review, not as a tested recipe. Back up the Mac first.

1. **Separate boot target.** Custom boot policy is per macOS installation. Use a
   second macOS installation in its own APFS container, so the everyday macOS
   keeps Full Security. Creating one needs free disk space and a macOS
   installer; the exact steps are still to be written and reviewed.
2. **Build and copy.** `make screen-probe`, then copy `build/screen-probe.bin`
   and its SHA-256 to a location readable from recoveryOS (for example, the
   separate installation's volume).
3. **Install from 1TR.** Shut down, hold the power button until "Loading startup
   options…", choose Options, and open Terminal. Local `kmutil` help (macOS 27.0)
   documents:

   ```sh
   kmutil configure-boot -c /Volumes/<Target>/screen-probe.bin --raw \
       --lowest-virtual-address <VA> --entry-point <VA> -v /Volumes/<Target>
   ```

   The entry point is the first byte of the image, so both addresses are equal.
   **Open question:** which virtual address to choose. Asahi describes it as
   "mostly meaningless" for raw images; confirm before running. `kmutil` may ask
   to lower that installation's security policy; that is expected for a custom
   kernel and requires the owner's credentials.
4. **Run.** Select the target installation in the boot picker. Photograph the
   screen, including the colour bars. Record the Mac model, macOS and firmware
   versions, the image SHA-256, and the photo in [RESEARCH.md](RESEARCH.md).
5. **Return.** Hold the power button to turn off, then hold it again to open the
   boot picker and choose the everyday macOS. Its security policy is unchanged.

A black screen is also a result: record it. It means `x0` was not a valid
`boot_args`, the framebuffer description failed validation, or the probe
faulted before drawing.
