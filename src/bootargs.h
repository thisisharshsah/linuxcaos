/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef BOOTARGS_H
#define BOOTARGS_H

#include <stdint.h>

/*
 * Candidate Apple ARM64 boot_args layout, from the pinned XNU header recorded in
 * docs/APPLE_BOOT.md. Parsing uses byte loads only (safe with the MMU off and
 * strict alignment). A structure that passes these checks is still unverified:
 * the layout is historical and the values come from firmware we do not control.
 */

#define BOOTARGS_SIZE 0x2e0U
#define BOOTARGS_CMDLINE_OFFSET 0x6cU
#define BOOTARGS_CMDLINE_LEN 608U
#define BOOTARGS_MAX_DIMENSION 8192U

struct bootargs {
    uint16_t revision, version;
    uint64_t virt_base, phys_base, mem_size, top_of_kdata;
    uint64_t video_base, video_display, video_row_bytes;
    uint64_t video_width, video_height, video_depth;
    uint32_t machine_type;
    uint64_t device_tree;
    uint32_t device_tree_length;
    uint64_t boot_flags;      /* 0 for revision 1 */
    uint32_t depth_bits;      /* video_depth & 0xff */
    uint32_t pixel_format;    /* enum fb_format candidate; valid when video_ok */
    uint32_t video_ok;        /* framebuffer description passed every check */
    uint32_t video_in_ram;    /* framebuffer overlaps [phys_base, phys_base + mem_size) */
};

enum bootargs_status {
    BOOTARGS_OK = 0,
    BOOTARGS_ERR_REVISION,    /* revision not 1 or 2 */
    BOOTARGS_ERR_VERSION,     /* version not 1 or 2 */
    BOOTARGS_ERR_MEMORY,      /* phys_base or mem_size zero, or wraps */
};

/* Parses BOOTARGS_SIZE bytes. Video problems do not fail the parse; they clear video_ok. */
int bootargs_parse(const uint8_t *data, struct bootargs *out);

#endif /* BOOTARGS_H */
