/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Link at zero for inspection; ADR makes this small payload relocatable.
 * RWX describes our test contract, not a guarantee about iBoot mappings.
 */
ENTRY(_start)
PHDRS { image PT_LOAD FLAGS(7); }
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.boot)) } :image
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
    ASSERT(probe_record == 16, "Probe record offset changed")
    ASSERT(SIZEOF(.text) <= 0x1000, "Probe exceeds test page")
}
