/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Original ARM64 entry-state experiment. No Apple MMIO or boot-argument reads.
 * Requires little-endian privileged AArch64 entry and a writable/executable map.
 * It has no physical output channel and is not yet validated for Apple boot.
 */
.section .text.boot, "ax"
.global _start
.type _start, %function
_start:
    b .Lcapture

/* Record starts at raw-image offset 16; see docs/ENTRY_PROBE.md. */
.balign 16
.global probe_record
probe_record:
    .ascii "M1PROBE\0"
    .word 1
    .word 96
    .quad 0                       // Status: pending
    .zero 72                      // Captured state plus reserved word

.Lcapture:
    // ADR, unlike an absolute address, follows the image when relocated.
    adr x9, probe_record
    stp x0, x1, [x9, #24]
    stp x2, x3, [x9, #40]
    mov x10, sp
    str x10, [x9, #56]
    adr x10, _start
    str x10, [x9, #64]
    mrs x10, CurrentEL
    str x10, [x9, #72]
    mrs x10, DAIF
    str x10, [x9, #80]

    // Save the original mask first; then park with interrupts masked.
    msr DAIFSet, #15
    dmb sy
    mov x10, #1
    str x10, [x9, #16]             // Publish completion last
    dsb sy
.global probe_park
probe_park:
    wfe
    b probe_park
.size _start, . - _start
