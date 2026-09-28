/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "bootargs.h"
#include "framebuffer.h"

static uint64_t rd(const uint8_t *p, unsigned size) {
    uint64_t v = 0;
    for (unsigned i = size; i > 0; i--) v = (v << 8) | p[i - 1];
    return v;
}

/*
 * Video checks: a plausible, 4-byte aligned linear framebuffer in a pixel format
 * the console can draw. Depth 30 -> x2r10g10b10 and depth 32 -> x8r8g8b8 is a
 * documentation-derived guess (docs/RESEARCH.md), not a measurement.
 */
static int video_plausible(const struct bootargs *b, uint32_t *format) {
    if (b->depth_bits == 30) *format = FB_FORMAT_X2R10G10B10;
    else if (b->depth_bits == 32) *format = FB_FORMAT_X8R8G8B8;
    else return 0;
    if (!b->video_base || (b->video_base & 3)) return 0;
    if (!b->video_width || !b->video_height) return 0;
    if (b->video_width > BOOTARGS_MAX_DIMENSION || b->video_height > BOOTARGS_MAX_DIMENSION) return 0;
    if (b->video_row_bytes < b->video_width * 4 || (b->video_row_bytes & 3)) return 0;
    if (b->video_row_bytes > FB_MAX_STRIDE) return 0;
    uint64_t span = b->video_row_bytes * b->video_height;
    if (b->video_base > UINT64_MAX - span) return 0;
    return 1;
}

int bootargs_parse(const uint8_t *data, struct bootargs *out) {
    struct bootargs b = {0};
    b.revision = (uint16_t)rd(data + 0x000, 2);
    b.version = (uint16_t)rd(data + 0x002, 2);
    if (b.revision != 1 && b.revision != 2) return BOOTARGS_ERR_REVISION;
    if (b.version != 1 && b.version != 2) return BOOTARGS_ERR_VERSION;
    b.virt_base = rd(data + 0x008, 8);
    b.phys_base = rd(data + 0x010, 8);
    b.mem_size = rd(data + 0x018, 8);
    b.top_of_kdata = rd(data + 0x020, 8);
    b.video_base = rd(data + 0x028, 8);
    b.video_display = rd(data + 0x030, 8);
    b.video_row_bytes = rd(data + 0x038, 8);
    b.video_width = rd(data + 0x040, 8);
    b.video_height = rd(data + 0x048, 8);
    b.video_depth = rd(data + 0x050, 8);
    b.machine_type = (uint32_t)rd(data + 0x058, 4);
    b.device_tree = rd(data + 0x060, 8);
    b.device_tree_length = (uint32_t)rd(data + 0x068, 4);
    if (b.revision >= 2) b.boot_flags = rd(data + 0x2d0, 8);
    if (!b.phys_base || !b.mem_size || b.phys_base > UINT64_MAX - b.mem_size)
        return BOOTARGS_ERR_MEMORY;
    b.depth_bits = (uint32_t)(b.video_depth & 0xff);
    b.video_ok = (uint32_t)video_plausible(&b, &b.pixel_format);
    /* Reported, not rejected: the RAM range's exact meaning is still unverified. */
    uint64_t span = b.video_row_bytes * b.video_height;
    b.video_in_ram = b.video_ok && b.video_base < b.phys_base + b.mem_size &&
                     b.video_base + span > b.phys_base;
    *out = b;
    return BOOTARGS_OK;
}
