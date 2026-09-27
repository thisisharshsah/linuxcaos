/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PLATFORM_H
#define PLATFORM_H

/*
 * Board-support interface used by the portable monitor. Each directory under
 * platform/ implements it once (platform.c) with its own linker script
 * (link.ld); `make PLATFORM=<name>` selects one. See platform/README.md.
 */

/* Prepares the console device. Called once, before any other function. */
void platform_console_init(void);
/* Writes one byte, waiting while the device cannot accept it. */
void platform_console_putc(char c);
/* Returns one received byte, waiting until one is available. */
char platform_console_getc(void);
/* Short human-readable name, e.g. "QEMU virt". */
const char *platform_name(void);

#endif /* PLATFORM_H */
