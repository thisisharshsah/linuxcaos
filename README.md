# Independent Apple Silicon Linux research

Start with the **[living blueprint](docs/BLUEPRINT.md)** for the overall goal,
architecture, current implementation, and update history side by side.

Goal: independently implement the boot and platform-support work needed to run
Linux on an Apple M1 MacBook Pro (MacBookPro17,1). No Asahi, m1n1, or U-Boot code
is included. Project-authored source starts here from scratch.

**Current state: an ARM64 serial monitor and an experimental entry-state probe.**
It is not an Apple bootloader, Linux distribution, or usable Mac OS yet.
QEMU virt is a different machine from an M1; emulator success proves no M1
hardware compatibility.

Open source under **GPL-2.0-or-later** ([LICENSE](LICENSE)). Contributions are
welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Build and test

Requires Python 3.12+, make, a POSIX shell (macOS or Linux; WSL on Windows), and
network access for initial dependency setup:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make
make test
```

Alternatively use `uv venv --python 3.12 .venv` and
`uv pip install --python .venv/bin/python -r requirements-dev.txt`.

The pinned Zig package supplies an ARM64 compiler and ELF linker. A small local
ELF converter extracts loadable bytes into a raw binary, checking the target
architecture, addresses, file bounds, segment overlap, and entry address.
Unicorn executes the generated instructions with a test PL011 register model.
The test dirties RAM before entry to check BSS clearing, and checks console
commands, CRLF handling, editing, and overlong-input recovery. Framebuffer tests
map test RAM, attach the text console to it, and compare every pixel with an
independent Python rendering; `build/fb-test.png` is the resulting snapshot.

`make probe` builds a separate, relocatable entry-state probe. It records incoming
registers into its own memory and parks; it has no physical output channel yet.
`make test` also runs the host tool tests and synthetic probe execution checks.
See [the probe design](docs/ENTRY_PROBE.md) and
[primary-source Apple boot research](docs/APPLE_BOOT.md).

With QEMU installed separately, `make run` launches the actual virt device model.
Alternatively, `make console` launches the interactive serial monitor directly in your terminal using Unicorn without requiring QEMU.
Commands include `help`, `info`, `status`, `echo`, `dump`, `peek`, `poke`, `regs`, `probe`, `kimage`, `fb`, `trap`, or `clear`; press `Ctrl-]` to exit the console runner.

## Independence boundary

We author boot code, hardware research tooling, and future platform drivers.
Compilers and emulators remain third-party development tools. Linux itself is
an existing kernel: using it makes this a Linux port. Replacing that too would
mean building a different operating system. No Linux source is included yet.
Existing Apple firmware is also outside this project's implementation scope.

This is independently authored code, not a claim of legally audited clean-room
development. At the project owner's request, Asahi Linux's public
documentation (not its code) has been consulted; sources are pinned in
[docs/RESEARCH.md](docs/RESEARCH.md). Mainline Linux already includes device
trees and drivers for this Mac, which this project intends to reuse rather than
rewrite. Record each specification, observation, and source explicitly.

## Files

- `src/start.S`: interrupt masking, stack setup, BSS clearing, vector install, C entry.
- `src/vectors.S`, `src/exception.c`: exception vectors; crash report, then return to the prompt.
- `src/monitor.c`: portable polling monitor; no runtime or standard library.
- `src/platform.h`: board-support interface; each board lives in `platform/<name>/`
  and is chosen with `make PLATFORM=<name>` ([how to add one](platform/README.md)).
- `platform/qemu-virt/`: PL011 console and memory layout for the development target.
- `src/framebuffer.c`: platform-neutral 32-bpp text console (glyphs, wrap, scroll).
- `tools/font8x16.txt`, `tools/generate_font.py`: editable font source and `src/font.h` generator (`make font`).
- `tools/fb_export.py`: converts a saved framebuffer dump to PNG/PPM.
- `src/entry_probe.S`: stack-free, PC-relative entry-state capture experiment.
- `tools/inspect_probe.py`: offline saved-record decoder; JSON output.
- `tools/inspect_bootargs.py`: offline decoder for a saved candidate Apple `boot_args` capture.
- `src/linux_boot.c`: portable Linux Image header check and kernel/DTB/initrd placement
  per the kernel's arm64 boot rules; `make host` builds it for host tests.
- `tools/fdt.py`: build or dump flattened device tree (DTB) files.
- `tests/emulate_probe.py`: synthetic relocation and register-capture tests.
- `tests/emulate.py`: ARM64 instruction execution and serial integration tests.
- `docs/BLUEPRINT.md`: living architecture, progress, evidence, and update history.
- `docs/ROADMAP.md`: hardware milestones and completion criteria.

The monitor binary expects one CPU, MMU off, and accessible QEMU virt RAM/UART. Interrupts
stay masked. CPU exceptions print a register report and return to the prompt
(`trap` triggers one deliberately). There is no interrupt handling, allocator, device-tree parser,
Linux loader, persistent storage, or Apple hardware driver.

`fb <hex_addr> <width> <height> <stride_bytes> [scale]` mirrors console output to
memory the caller describes, in little-endian `0x00RRGGBB` pixels; `fb off`
detaches it. The monitor checks alignment, geometry, and overlap with itself,
but it cannot know whether the address is really a display. Only use it with
test RAM until a real framebuffer description has been established.

The separate probe assumes privileged little-endian execution and writable
payload memory. Its real-M1 entry state, mapping, and record retrieval path are
unverified; neither binary is an installable Apple boot solution.

## License

Project code is licensed under the GNU General Public License, version 2 or
(at your option) any later version. Each source file carries an
`SPDX-License-Identifier: GPL-2.0-or-later` line. Copyright belongs to the
project contributors. Compilers, emulators, Apple firmware, and the Linux kernel
keep their own licenses.

## Technical references

- QEMU virt platform: https://www.qemu.org/docs/master/system/arm/virt.html
- QEMU PL011 model: https://gitlab.com/qemu-project/qemu/-/blob/master/hw/char/pl011.c
- Linux ARM64 entry contract: https://cdn.kernel.org/doc/html/latest/arch/arm64/booting.html

The UART map is specific to this emulator target. Never substitute an assumed
Apple MMIO address and run this on hardware.
