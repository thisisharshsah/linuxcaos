/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef LINUX_BOOT_H
#define LINUX_BOOT_H

#include <stdint.h>

/*
 * ARM64 Linux Image header parsing and load-address planning, following the
 * kernel's Documentation/arch/arm64/booting.rst. Portable, freestanding C with
 * no memory access beyond the buffers passed in; also built for the host so
 * tests exercise this exact code. Nothing here has booted Linux yet.
 */

#define LINUX_IMAGE_HEADER_SIZE 64U
#define LINUX_IMAGE_MAGIC 0x644d5241U /* "ARM\x64", little endian */
#define LINUX_SZ_2M 0x200000ULL
#define LINUX_SZ_1G 0x40000000ULL
#define LINUX_DTB_MAX 0x200000ULL          /* booting.rst: DTB <= 2 MB */
#define LINUX_INITRD_WINDOW (32ULL << 30)  /* 1 GB-aligned window <= 32 GB */

struct linux_image_info {
    uint64_t text_offset;
    uint64_t image_size;   /* effective size including BSS */
    uint64_t flags;
    uint32_t page_size_kb; /* 0 when unspecified */
    uint32_t anywhere;     /* flags bit 3: placement anywhere in 48-bit space */
};

enum linux_image_status {
    LINUX_OK = 0,
    LINUX_ERR_SHORT,         /* fewer than 64 header bytes */
    LINUX_ERR_MAGIC,         /* not an ARM64 Image (compressed or wrong file?) */
    LINUX_ERR_LEGACY,        /* image_size == 0: pre-v3.17 header, unsupported */
    LINUX_ERR_BIG_ENDIAN,    /* flags bit 0 */
    LINUX_ERR_FLAGS,         /* reserved flag bits 4-63 set */
    LINUX_ERR_TEXT_OFFSET,   /* text_offset not below 2 MB or misaligned */
    LINUX_ERR_FILE_SIZE,     /* file larger than image_size */
};

enum linux_plan_status {
    LINUX_PLAN_OK = 0,
    LINUX_PLAN_ERR_RAM,      /* RAM region empty or wraps */
    LINUX_PLAN_ERR_DTB,      /* DTB empty or larger than 2 MB */
    LINUX_PLAN_ERR_NO_ROOM,  /* kernel, DTB, and initrd do not fit */
    LINUX_PLAN_ERR_WINDOW,   /* kernel + initrd exceed one 1 GB-aligned 32 GB window */
    LINUX_PLAN_ERR_48BIT,    /* image beyond 48-bit physical range */
};

struct linux_boot_plan {
    uint64_t image_base;  /* 2 MB aligned */
    uint64_t kernel;      /* image_base + text_offset: load and entry address */
    uint64_t kernel_end;  /* kernel + image_size */
    uint64_t dtb;         /* own 2 MB region after the kernel; x0 at entry */
    uint64_t initrd;      /* 0 when no initrd */
    uint64_t initrd_end;
};

/* Parses a little-endian Image header from `len` bytes; file_size may be 0 to skip that check. */
int linux_image_parse(const uint8_t *header, uint64_t len, uint64_t file_size,
                      struct linux_image_info *out);

/* Places kernel, DTB, and optional initrd (initrd_size 0 = none) inside one RAM region. */
int linux_boot_plan(const struct linux_image_info *image, uint64_t ram_base,
                    uint64_t ram_size, uint64_t dtb_size, uint64_t initrd_size,
                    struct linux_boot_plan *out);

#endif /* LINUX_BOOT_H */
