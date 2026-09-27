/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "exception.h"
#include "monitor.h"

extern char __stack_top[];
void exception_resume(uint64_t el, void (*fn)(void), uint64_t stack) __attribute__((noreturn));

static volatile int in_exception;
static uint64_t recovered;

#define READ_SYSREG(name) ({ uint64_t v_; __asm__ volatile("mrs %0, " #name : "=r"(v_)); v_; })

static uint64_t current_el(void) {
    return (READ_SYSREG(CurrentEL) >> 2) & 3;
}

uint64_t exception_count(void) {
    return recovered;
}

uint64_t exception_vbar(void) {
    uint64_t el = current_el();
    if (el == 1) return READ_SYSREG(vbar_el1);
    if (el == 2) return READ_SYSREG(vbar_el2);
    return 0;
}

/* Exception classes from the Arm ARM ESR_ELx.EC field (common subset). */
static const char *ec_name(uint64_t ec) {
    switch (ec) {
    case 0x00: return "unknown reason";
    case 0x01: return "WFI/WFE trapped";
    case 0x0e: return "illegal execution state";
    case 0x15: return "SVC (AArch64)";
    case 0x16: return "HVC (AArch64)";
    case 0x17: return "SMC (AArch64)";
    case 0x18: return "system register access trapped";
    case 0x20: return "instruction abort, lower EL";
    case 0x21: return "instruction abort, same EL";
    case 0x22: return "PC alignment fault";
    case 0x24: return "data abort, lower EL";
    case 0x25: return "data abort, same EL";
    case 0x26: return "SP alignment fault";
    case 0x2f: return "SError";
    case 0x3c: return "BRK (AArch64)";
    default: return "other (see Arm ARM ESR_ELx.EC)";
    }
}

static int far_valid(uint64_t ec) {
    return ec == 0x20 || ec == 0x21 || ec == 0x22 || ec == 0x24 || ec == 0x25;
}

static void put_reg(const char *name, uint64_t value) {
    console_puts(name);
    console_puts("0x");
    console_put_hex64(value);
}

static void put_xreg(unsigned n, uint64_t value) {
    console_puts("  x");
    console_putc((char)('0' + n / 10));
    console_putc((char)('0' + n % 10));
    put_reg(" ", value);
}

void exception_handle(struct exception_frame *frame, uint64_t kind) {
    /* A fault while reporting (for example, a broken console) must not recurse. */
    if (in_exception) {
        for (;;) __asm__ volatile("wfe");
    }
    in_exception = 1;

    static const char *const type[4] = {"synchronous", "IRQ", "FIQ", "SError"};
    static const char *const origin[4] = {
        "current EL with SP_EL0", "current EL with SP_ELx",
        "lower EL (AArch64)", "lower EL (AArch32)",
    };
    uint64_t el = current_el();
    uint64_t esr, elr, far, spsr;
    if (el == 2) {
        esr = READ_SYSREG(esr_el2);
        elr = READ_SYSREG(elr_el2);
        far = READ_SYSREG(far_el2);
        spsr = READ_SYSREG(spsr_el2);
    } else {
        esr = READ_SYSREG(esr_el1);
        elr = READ_SYSREG(elr_el1);
        far = READ_SYSREG(far_el1);
        spsr = READ_SYSREG(spsr_el1);
    }
    uint64_t ec = (esr >> 26) & 0x3f;

    console_puts("\n*** EXCEPTION: ");
    console_puts(type[kind & 3]);
    console_puts(" from ");
    console_puts(origin[(kind >> 2) & 3]);
    console_puts(", taken to EL");
    console_putc((char)('0' + el));
    console_puts(" ***\n");
    put_reg("  ESR:  ", esr);
    console_puts("  EC 0x");
    console_putc("0123456789abcdef"[ec >> 4]);
    console_putc("0123456789abcdef"[ec & 15]);
    console_puts(" (");
    console_puts(ec_name(ec));
    console_puts(")\n");
    put_reg("  ELR:  ", elr);
    console_puts("\n");
    if (far_valid(ec)) put_reg("  FAR:  ", far);
    else console_puts("  FAR:  not valid for this class");
    console_puts("\n");
    put_reg("  SPSR: ", spsr);
    put_reg("\n  SP:   ", (uint64_t)(uintptr_t)frame + sizeof(*frame));
    console_puts("\n");
    for (unsigned i = 0; i < 31; i++) {
        put_xreg(i, frame->x[i]);
        console_puts((i % 2 == 1 || i == 30) ? "\n" : "");
    }

    if (el != 1 && el != 2) {
        console_puts("Unsupported exception level; halted.\n");
        for (;;) __asm__ volatile("wfe");
    }
    recovered++;
    console_puts("Recovered; monitor restarted with a fresh stack.\n");
    in_exception = 0;
    exception_resume(el, monitor_resume, (uint64_t)(uintptr_t)__stack_top);
}
