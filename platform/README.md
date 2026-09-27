# Platforms

The monitor in `src/` is portable. Everything that touches a specific machine
lives in one directory here, selected at build time:

```sh
make PLATFORM=qemu-virt   # the default
```

| Platform | Console | Status |
| --- | --- | --- |
| `qemu-virt` | PL011 UART at `0x09000000` | Unicorn tests pass; QEMU not yet run. Development target only. |

`entry-probe.ld` is not a platform. It belongs to the separate, relocatable
[entry probe](../docs/ENTRY_PROBE.md).

## Adding a platform

1. Create `platform/<name>/platform.c` implementing the four functions in
   [src/platform.h](../src/platform.h): `platform_console_init`,
   `platform_console_putc`, `platform_console_getc`, and `platform_name`.
2. Create `platform/<name>/link.ld`. Define `__image_start` at the load address,
   and `__bss_start`, `__bss_end`, and `__stack_top` as the
   [qemu-virt script](qemu-virt/link.ld) does. The monitor uses these symbols to
   clear BSS and to stop `fb` from overwriting itself.
3. Start both files with `SPDX-License-Identifier: GPL-2.0-or-later`.
   `tests/test_repository.py` enforces this and checks that both files exist.
4. Build with `make PLATFORM=<name>`, then add a row to the table above and to
   the [blueprint](../docs/BLUEPRINT.md) that states exactly what was validated.

## Hardware safety rule

Every address, register offset, and bit in a platform file needs a cited source
or a recorded observation in [docs/RESEARCH.md](../docs/RESEARCH.md). Never guess
a device address and run the result on physical hardware. Until a platform has
been validated on its real machine, its row above must say so.
