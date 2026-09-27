/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef EXCEPTION_H
#define EXCEPTION_H

#include <stdint.h>

/* Registers x0-x30 as saved by src/vectors.S. */
struct exception_frame {
    uint64_t x[31];
    uint64_t pad;
};

/* Reports an exception and resumes the monitor prompt. Called from vectors.S. */
void exception_handle(struct exception_frame *frame, uint64_t kind) __attribute__((noreturn));
/* Number of exceptions reported and recovered since startup. */
uint64_t exception_count(void);
/* VBAR of the current exception level, or 0 when not EL1/EL2. */
uint64_t exception_vbar(void);

#endif /* EXCEPTION_H */
