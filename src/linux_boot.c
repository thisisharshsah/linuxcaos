/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "linux_boot.h"

static uint64_t le64(const uint8_t *p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; i--) v = (v << 8) | p[i];
    return v;
}

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

int linux_image_parse(const uint8_t *header, uint64_t len, uint64_t file_size,
                      struct linux_image_info *out) {
    static const uint32_t page_kb[4] = {0, 4, 16, 64};
    if (len < LINUX_IMAGE_HEADER_SIZE) return LINUX_ERR_SHORT;
    if (le32(header + 56) != LINUX_IMAGE_MAGIC) return LINUX_ERR_MAGIC;
    uint64_t text_offset = le64(header + 8);
    uint64_t image_size = le64(header + 16);
    uint64_t flags = le64(header + 24);
    if (image_size == 0) return LINUX_ERR_LEGACY;
    if (flags & 1) return LINUX_ERR_BIG_ENDIAN;
    if (flags >> 4) return LINUX_ERR_FLAGS;
    /* Project policy, stricter than booting.rst: keep the Image inside the first
     * 2 MB block above its aligned base, on a 4 KB boundary. */
    if (text_offset >= LINUX_SZ_2M || (text_offset & 0xfff)) return LINUX_ERR_TEXT_OFFSET;
    if (file_size > image_size) return LINUX_ERR_FILE_SIZE;
    out->text_offset = text_offset;
    out->image_size = image_size;
    out->flags = flags;
    out->page_size_kb = page_kb[(flags >> 1) & 3];
    out->anywhere = (uint32_t)((flags >> 3) & 1);
    return LINUX_OK;
}

/* Rounds up to a power-of-two alignment; returns 0 on overflow. */
static int align_up(uint64_t v, uint64_t align, uint64_t *out) {
    if (v > UINT64_MAX - (align - 1)) return 0;
    *out = (v + align - 1) & ~(align - 1);
    return 1;
}

static int add(uint64_t a, uint64_t b, uint64_t *out) {
    if (a > UINT64_MAX - b) return 0;
    *out = a + b;
    return 1;
}

int linux_boot_plan(const struct linux_image_info *image, uint64_t ram_base,
                    uint64_t ram_size, uint64_t dtb_size, uint64_t initrd_size,
                    struct linux_boot_plan *out) {
    uint64_t ram_end;
    if (ram_size == 0 || !add(ram_base, ram_size, &ram_end)) return LINUX_PLAN_ERR_RAM;
    if (dtb_size == 0 || dtb_size > LINUX_DTB_MAX) return LINUX_PLAN_ERR_DTB;

    struct linux_boot_plan p = {0};
    /* Lowest 2 MB aligned base: booting.rst asks for placement near DRAM start. */
    if (!align_up(ram_base, LINUX_SZ_2M, &p.image_base) ||
        !add(p.image_base, image->text_offset, &p.kernel) ||
        !add(p.kernel, image->image_size, &p.kernel_end))
        return LINUX_PLAN_ERR_NO_ROOM;
    /* The DTB is mapped with 2 MB blocks; give it a 2 MB region of its own. */
    uint64_t end;
    if (!align_up(p.kernel_end, LINUX_SZ_2M, &p.dtb) || !add(p.dtb, dtb_size, &end))
        return LINUX_PLAN_ERR_NO_ROOM;
    if (initrd_size) {
        if (!align_up(end, LINUX_SZ_2M, &p.initrd) || !add(p.initrd, initrd_size, &p.initrd_end))
            return LINUX_PLAN_ERR_NO_ROOM;
        end = p.initrd_end;
    }
    if (end > ram_end) return LINUX_PLAN_ERR_NO_ROOM;
    if (image->anywhere && p.kernel_end > (1ULL << 48)) return LINUX_PLAN_ERR_48BIT;
    if (initrd_size) {
        /* One 1 GB aligned window of at most 32 GB must cover kernel and initrd. */
        uint64_t window_start = p.kernel & ~(LINUX_SZ_1G - 1);
        uint64_t window_end;
        if (!align_up(p.initrd_end, LINUX_SZ_1G, &window_end) ||
            window_end - window_start > LINUX_INITRD_WINDOW)
            return LINUX_PLAN_ERR_WINDOW;
    }
    *out = p;
    return LINUX_PLAN_OK;
}
