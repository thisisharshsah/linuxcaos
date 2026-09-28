/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * M1 screen probe: linked at zero, position-independent, and fully file-backed
 * (data and stack included) so that loading the raw bytes is enough; nothing
 * depends on a loader allocating extra memory. The Makefile links it a second
 * time at another base and requires identical bytes.
 */
ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.boot)) *(.text .text.*) }
    .rodata : ALIGN(8) { *(.rodata .rodata.*) }
    /* Every byte is file-backed: TYPE forces PROGBITS and makes the link fail
     * if a NOBITS (.bss) input appears. The probe is compiled with
     * -fno-zero-initialized-in-bss and reserves its stack in .probe_stack. */
    .data (TYPE = SHT_PROGBITS) : ALIGN(16) {
        *(.data .data.*)
        . = ALIGN(16);
        *(.probe_stack)
    }
    /DISCARD/ : { *(.eh_frame*) *(.comment) *(.note*) }
    ASSERT(__stack_top - ADDR(.text) < 0x100000, "Screen probe exceeds 1 MiB")
    ASSERT(__stack_top == ADDR(.data) + SIZEOF(.data), "Stack must end the image")
}
