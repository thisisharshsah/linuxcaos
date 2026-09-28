/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FDT_H
#define FDT_H

#include <stdint.h>

/*
 * Flattened device tree (DTB) reading and in-place editing, written from the
 * Devicetree Specification v0.4, section 5. Portable and freestanding: byte
 * accesses only, no libc. The blob must be laid out as header, memory
 * reservation block, structure block, strings block (the usual order); edits
 * grow or shrink it within the caller's buffer and fail without changing
 * anything when the buffer is too small. Also built for the host for tests.
 */

struct fdt {
    uint8_t *buf;
    uint32_t capacity; /* bytes available in buf */
};

enum fdt_status {
    FDT_OK = 0,
    FDT_ERR_HEADER = -1,   /* bad magic, version, sizes, or block order */
    FDT_ERR_STRUCT = -2,   /* malformed structure block */
    FDT_ERR_NOTFOUND = -3, /* node or property does not exist */
    FDT_ERR_NOSPACE = -4,  /* the edit does not fit in the buffer */
    FDT_ERR_BADNAME = -5,  /* empty name, or a '/' in a node name */
    FDT_ERR_EXISTS = -6,   /* subnode already present */
    FDT_ERR_CELLS = -7,    /* #address-cells/#size-cells not 1 or 2 */
};

/* Validates the header and block layout. */
int fdt_open(struct fdt *f, uint8_t *buf, uint32_t capacity);
uint32_t fdt_total_size(const struct fdt *f);

/* Node offsets are >= 0; errors are negative. The root is "/". A path
 * component without '@' also matches "name@unit" (first match wins). */
int fdt_find(const struct fdt *f, const char *path);
int fdt_get_prop(const struct fdt *f, int node, const char *name,
                 const uint8_t **value, uint32_t *len);
int fdt_set_prop(struct fdt *f, int node, const char *name, const void *value, uint32_t len);
int fdt_del_prop(struct fdt *f, int node, const char *name);
/* Adds an empty child node; returns its offset. */
int fdt_add_subnode(struct fdt *f, int parent, const char *name);

/* Values bootloaders supply to a Linux device tree (0 / NULL = leave unset). */
struct fdt_linux_params {
    uint64_t mem_base, mem_size;
    const char *bootargs;
    uint64_t initrd_start, initrd_end;
    uint64_t fb_base;
    uint32_t fb_width, fb_height, fb_stride;
    const char *fb_format; /* simple-framebuffer name, e.g. "x2r10g10b10" */
};

/*
 * Fills /memory reg, /chosen bootargs and linux,initrd-start/-end, and, when
 * fb_base is set, enables /chosen/framebuffer (reg, width, height, stride,
 * format, status = "okay"). /chosen is created if missing; /memory and the
 * framebuffer node must already exist, as in the mainline Apple device trees.
 * Not atomic across steps: on error, earlier steps may already be applied, so
 * callers should fill a scratch copy and use it only when this returns FDT_OK.
 */
int fdt_fill_linux(struct fdt *f, const struct fdt_linux_params *p);

#endif /* FDT_H */
