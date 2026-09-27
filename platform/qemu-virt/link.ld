/* SPDX-License-Identifier: GPL-2.0-or-later */
ENTRY(_start)
SECTIONS
{
    . = 0x40080000;
    __image_start = .;
    .text : { KEEP(*(.text.boot)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss (NOLOAD) : ALIGN(16) {
        __bss_start = .;
        *(.bss .bss.*) *(COMMON)
        . = ALIGN(16);
        __bss_end = .;
    }
    .stack (NOLOAD) : ALIGN(16) {
        . += 0x4000;
        __stack_top = .;
    }
    ASSERT(__stack_top < 0x40180000, "Monitor exceeds reserved 1 MiB")
}
