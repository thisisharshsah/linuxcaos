/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef MONITOR_H
#define MONITOR_H

#include <stdint.h>

/* Console output shared with other monitor modules (serial + framebuffer). */
void console_putc(char c);
void console_puts(const char *s);
void console_put_hex64(uint64_t val);

/* Re-enters the command loop with a fresh prompt; used after an exception. */
void monitor_resume(void) __attribute__((noreturn));

#endif /* MONITOR_H */
