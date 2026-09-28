/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * linux_jump(dtb, entry): enter an ARM64 Linux Image as required by the
 * kernel's Documentation/arch/arm64/booting.rst: x0 = DTB physical address,
 * x1-x3 = 0, all interrupts masked, MMU off. The instruction cache is
 * invalidated first because the kernel was just copied into place.
 * Does not return.
 */
.section .text
.global linux_jump
.type linux_jump, %function
linux_jump:
    msr daifset, #15
    mov x9, x1
    dsb sy
    ic iallu
    dsb sy
    isb
    mov x1, xzr
    mov x2, xzr
    mov x3, xzr
    br x9
.size linux_jump, . - linux_jump
