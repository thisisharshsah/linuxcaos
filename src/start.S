/* SPDX-License-Identifier: GPL-2.0-or-later */
.section .text.boot, "ax"
.global _start
.type _start, %function
_start:
    // Single-core entry; MMU off. Interrupts stay masked; only exception reporting exists.
    msr daifset, #15
    ldr x0, =__stack_top
    mov sp, x0
    ldr x0, =__bss_start
    ldr x1, =__bss_end
1:
    cmp x0, x1
    b.hs 2f
    str xzr, [x0], #8
    b 1b
2:
    // Install exception vectors for the entry level (EL1 or EL2 only).
    ldr x1, =exception_vectors
    mrs x0, CurrentEL
    lsr x0, x0, #2
    cmp x0, #2
    b.eq 4f
    cmp x0, #1
    b.ne 5f
    msr vbar_el1, x1
    b 5f
4:
    msr vbar_el2, x1
5:
    isb
    bl monitor_main
3:
    wfe
    b 3b
.size _start, . - _start
