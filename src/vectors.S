/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * AArch64 exception vector table for the monitor. start.S installs it in
 * VBAR_EL1 or VBAR_EL2, whichever matches the entry exception level. Every
 * entry saves x0-x30 and calls exception_handle(frame, kind), which reports
 * and resumes the monitor. A fault caused by an unusable SP re-faults here
 * before any report can be printed.
 */
#define FRAME_SIZE 256 /* x0-x30 (248 bytes), rounded up to keep SP 16-byte aligned */

.macro vector kind
    .balign 0x80
    sub sp, sp, #FRAME_SIZE
    stp x0, x1, [sp, #0]
    mov x1, #\kind
    b exception_entry
.endm

.section .text.vectors, "ax"
.balign 0x800
.global exception_vectors
exception_vectors:
    /* kind = 4 * origin + type; type: 0 sync, 1 IRQ, 2 FIQ, 3 SError */
    vector 0
    vector 1
    vector 2
    vector 3
    vector 4
    vector 5
    vector 6
    vector 7
    vector 8
    vector 9
    vector 10
    vector 11
    vector 12
    vector 13
    vector 14
    vector 15

exception_entry:
    stp x2, x3, [sp, #16]
    stp x4, x5, [sp, #32]
    stp x6, x7, [sp, #48]
    stp x8, x9, [sp, #64]
    stp x10, x11, [sp, #80]
    stp x12, x13, [sp, #96]
    stp x14, x15, [sp, #112]
    stp x16, x17, [sp, #128]
    stp x18, x19, [sp, #144]
    stp x20, x21, [sp, #160]
    stp x22, x23, [sp, #176]
    stp x24, x25, [sp, #192]
    stp x26, x27, [sp, #208]
    stp x28, x29, [sp, #224]
    str x30, [sp, #240]
    mov x0, sp
    bl exception_handle
1:
    wfe
    b 1b

/*
 * exception_resume(el, fn, stack): continue at fn in EL<el>h with all
 * interrupts masked and a fresh stack. Only EL1 and EL2 are supported.
 */
.section .text
.global exception_resume
.type exception_resume, %function
exception_resume:
    mov sp, x2
    cmp x0, #2
    b.eq 2f
    msr elr_el1, x1
    mov x3, #0x3c5 /* EL1h, DAIF masked */
    msr spsr_el1, x3
    eret
2:
    msr elr_el2, x1
    mov x3, #0x3c9 /* EL2h, DAIF masked */
    msr spsr_el2, x3
    eret
.size exception_resume, . - exception_resume
