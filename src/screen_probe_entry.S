/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Entry for the M1 screen probe: a position-independent raw payload. It saves
 * the incoming x0-x3, SP, entry address, CurrentEL, and DAIF before touching
 * memory, masks interrupts, switches to a stack inside its own image, and calls
 * screen_probe_main. There is no BSS: every variable is file-backed data. Only
 * PC-relative addressing (ADR/ADRP) is used, so the image runs wherever the
 * firmware places it. It never returns.
 */
.section .text.boot, "ax"
.global _start
.type _start, %function
_start:
    mov x19, x0
    mov x20, x1
    mov x21, x2
    mov x22, x3
    mov x23, sp
    adr x24, _start
    mrs x25, CurrentEL
    mrs x26, DAIF
    msr daifset, #15
    adrp x0, __stack_top
    add x0, x0, :lo12:__stack_top
    mov sp, x0
    adrp x0, probe_entry
    add x0, x0, :lo12:probe_entry
    stp x19, x20, [x0, #0]
    stp x21, x22, [x0, #16]
    stp x23, x24, [x0, #32]
    stp x25, x26, [x0, #48]
    bl screen_probe_main
3:
    wfe
    b 3b
.size _start, . - _start

/* Stack inside the image, file-backed so the raw payload needs no extra memory. */
.section .probe_stack, "aw", %progbits
.balign 16
.space 0x4000
.global __stack_top
__stack_top:
