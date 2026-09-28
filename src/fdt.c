/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "fdt.h"

#define FDT_MAGIC 0xd00dfeedU
#define TAG_BEGIN_NODE 1U
#define TAG_END_NODE 2U
#define TAG_PROP 3U
#define TAG_NOP 4U
#define TAG_END 9U

/* Header field offsets (all big-endian 32-bit). */
#define H_TOTALSIZE 4
#define H_OFF_STRUCT 8
#define H_OFF_STRINGS 12
#define H_OFF_RSVMAP 16
#define H_VERSION 20
#define H_LAST_COMP 24
#define H_SIZE_STRINGS 32
#define H_SIZE_STRUCT 36
#define HEADER_SIZE 40U

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static void wr32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static uint32_t hdr(const struct fdt *f, unsigned off) { return rd32(f->buf + off); }
static void set_hdr(struct fdt *f, unsigned off, uint32_t v) { wr32(f->buf + off, v); }
static uint32_t align4(uint32_t v) { return (v + 3U) & ~3U; }

static uint32_t str_len(const char *s) {
    uint32_t n = 0;
    while (s[n]) n++;
    return n;
}

/* Overlap-safe byte move. Volatile keeps the compiler from turning the loops
 * into memmove/memcpy calls, which do not exist in freestanding builds. */
static void move_bytes(uint8_t *dst, const uint8_t *src, uint32_t n) {
    volatile uint8_t *d = dst;
    const volatile uint8_t *s = src;
    if (d < s) {
        for (uint32_t i = 0; i < n; i++) d[i] = s[i];
    } else {
        for (uint32_t i = n; i > 0; i--) d[i - 1] = s[i - 1];
    }
}

static void zero_bytes(uint8_t *dst, uint32_t n) {
    volatile uint8_t *d = dst;
    for (uint32_t i = 0; i < n; i++) d[i] = 0;
}

static uint32_t data_end(const struct fdt *f) {
    return hdr(f, H_OFF_STRINGS) + hdr(f, H_SIZE_STRINGS);
}

int fdt_open(struct fdt *f, uint8_t *buf, uint32_t capacity) {
    f->buf = buf;
    f->capacity = capacity;
    if (capacity < HEADER_SIZE || rd32(buf) != FDT_MAGIC) return FDT_ERR_HEADER;
    uint32_t total = hdr(f, H_TOTALSIZE), off_struct = hdr(f, H_OFF_STRUCT);
    uint32_t off_strings = hdr(f, H_OFF_STRINGS), off_rsv = hdr(f, H_OFF_RSVMAP);
    uint32_t size_struct = hdr(f, H_SIZE_STRUCT), size_strings = hdr(f, H_SIZE_STRINGS);
    if (hdr(f, H_VERSION) < 17 || hdr(f, H_LAST_COMP) > 17) return FDT_ERR_HEADER;
    if (total > capacity || total < HEADER_SIZE) return FDT_ERR_HEADER;
    if ((off_rsv & 7) || (off_struct & 3) || (size_struct & 3)) return FDT_ERR_HEADER;
    /* Required order: header < rsvmap < struct < strings, all inside totalsize. */
    if (off_rsv < HEADER_SIZE || off_struct < off_rsv + 16) return FDT_ERR_HEADER;
    if (size_struct > total || off_struct > total - size_struct) return FDT_ERR_HEADER;
    if (off_strings < off_struct + size_struct) return FDT_ERR_HEADER;
    if (size_strings > total || off_strings > total - size_strings) return FDT_ERR_HEADER;
    if (size_struct < 8 || rd32(buf + off_struct) != TAG_BEGIN_NODE) return FDT_ERR_STRUCT;
    return FDT_OK;
}

uint32_t fdt_total_size(const struct fdt *f) { return hdr(f, H_TOTALSIZE); }

/* Reads the tag at struct offset `off`; stores the next tag's offset. */
static int next_tag(const struct fdt *f, uint32_t off, uint32_t *next) {
    uint32_t size = hdr(f, H_SIZE_STRUCT);
    const uint8_t *base = f->buf + hdr(f, H_OFF_STRUCT);
    if (off > size || size - off < 4) return -1;
    uint32_t tag = rd32(base + off);
    if (tag == TAG_BEGIN_NODE) {
        uint32_t i = off + 4;
        while (i < size && base[i]) i++;
        if (i >= size) return -1;
        *next = align4(i + 1);
    } else if (tag == TAG_PROP) {
        if (size - off < 12) return -1;
        uint32_t len = rd32(base + off + 4);
        if (len > size - off - 12) return -1;
        *next = align4(off + 12 + len);
    } else if (tag == TAG_END_NODE || tag == TAG_NOP || tag == TAG_END) {
        *next = off + 4;
    } else {
        return -1;
    }
    if (*next > size) return -1;
    return (int)tag;
}

static const char *node_name(const struct fdt *f, uint32_t node) {
    return (const char *)(f->buf + hdr(f, H_OFF_STRUCT) + node + 4);
}

/* Offset just after a node's BEGIN_NODE tag and name, or negative. */
static int node_body(const struct fdt *f, int node) {
    uint32_t next;
    if (node < 0 || next_tag(f, (uint32_t)node, &next) != (int)TAG_BEGIN_NODE) return FDT_ERR_STRUCT;
    return (int)next;
}

/* "name" matches "name" and "name@unit"; "name@unit" matches only itself
 * (a node name has at most one '@', so no further check is needed). */
static int name_matches(const char *node, const char *comp, uint32_t len) {
    uint32_t i = 0;
    while (i < len && node[i] && node[i] == comp[i]) i++;
    if (i != len) return 0;
    return node[i] == 0 || node[i] == '@';
}

static int find_child(const struct fdt *f, int parent, const char *comp, uint32_t len) {
    int off = node_body(f, parent);
    if (off < 0) return off;
    int depth = 0;
    for (;;) {
        uint32_t next;
        int tag = next_tag(f, (uint32_t)off, &next);
        if (tag < 0 || tag == (int)TAG_END) return FDT_ERR_STRUCT;
        if (tag == (int)TAG_BEGIN_NODE) {
            if (depth == 0 && name_matches(node_name(f, (uint32_t)off), comp, len)) return off;
            depth++;
        } else if (tag == (int)TAG_END_NODE) {
            if (depth == 0) return FDT_ERR_NOTFOUND;
            depth--;
        }
        off = (int)next;
    }
}

int fdt_find(const struct fdt *f, const char *path) {
    if (path[0] != '/') return FDT_ERR_BADNAME;
    int node = 0;
    const char *p = path + 1;
    while (*p) {
        uint32_t len = 0;
        while (p[len] && p[len] != '/') len++;
        if (len) {
            node = find_child(f, node, p, len);
            if (node < 0) return node;
        }
        p += len;
        if (*p == '/') p++;
    }
    return node;
}

static int str_eq(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

/* Finds a property of `node`; returns its struct offset or FDT_ERR_NOTFOUND.
 * *after_props receives the offset where a new property may be inserted. */
static int find_prop(const struct fdt *f, int node, const char *name, uint32_t *after_props) {
    int off = node_body(f, node);
    if (off < 0) return off;
    const uint8_t *base = f->buf + hdr(f, H_OFF_STRUCT);
    const char *strings = (const char *)(f->buf + hdr(f, H_OFF_STRINGS));
    uint32_t size_strings = hdr(f, H_SIZE_STRINGS);
    for (;;) {
        uint32_t next;
        int tag = next_tag(f, (uint32_t)off, &next);
        if (tag < 0) return FDT_ERR_STRUCT;
        if (tag != (int)TAG_PROP && tag != (int)TAG_NOP) {
            if (after_props) *after_props = (uint32_t)off;
            return FDT_ERR_NOTFOUND;
        }
        if (tag == (int)TAG_PROP) {
            uint32_t nameoff = rd32(base + off + 8);
            if (nameoff >= size_strings) return FDT_ERR_STRUCT;
            if (str_eq(strings + nameoff, name)) return off;
        }
        off = (int)next;
    }
}

int fdt_get_prop(const struct fdt *f, int node, const char *name,
                 const uint8_t **value, uint32_t *len) {
    int off = find_prop(f, node, name, 0);
    if (off < 0) return off;
    const uint8_t *base = f->buf + hdr(f, H_OFF_STRUCT);
    *len = rd32(base + off + 4);
    *value = base + off + 12;
    return FDT_OK;
}

/* Offset of `name` in the strings block, or -1. */
static int find_string(const struct fdt *f, const char *name) {
    const char *s = (const char *)(f->buf + hdr(f, H_OFF_STRINGS));
    uint32_t size = hdr(f, H_SIZE_STRINGS), i = 0;
    while (i < size) {
        uint32_t start = i;
        while (i < size && s[i]) i++;
        if (i >= size) return -1;
        if (str_eq(s + start, name)) return (int)start;
        i++;
    }
    return -1;
}

/*
 * Opens (delta > 0) or closes (delta < 0) a gap at struct offset `at`, moving
 * the rest of the structure block and the strings block. Caller checks space.
 */
static void shift_struct(struct fdt *f, uint32_t at, int32_t delta) {
    uint32_t abs_at = hdr(f, H_OFF_STRUCT) + at;
    uint32_t end = data_end(f);
    if (delta > 0) {
        move_bytes(f->buf + abs_at + (uint32_t)delta, f->buf + abs_at, end - abs_at);
        zero_bytes(f->buf + abs_at, (uint32_t)delta);
    } else if (delta < 0) {
        uint32_t d = (uint32_t)(-delta);
        move_bytes(f->buf + abs_at, f->buf + abs_at + d, end - abs_at - d);
    }
    set_hdr(f, H_SIZE_STRUCT, hdr(f, H_SIZE_STRUCT) + (uint32_t)delta);
    set_hdr(f, H_OFF_STRINGS, hdr(f, H_OFF_STRINGS) + (uint32_t)delta);
    set_hdr(f, H_TOTALSIZE, data_end(f));
}

int fdt_set_prop(struct fdt *f, int node, const char *name, const void *value, uint32_t len) {
    if (!name[0]) return FDT_ERR_BADNAME;
    uint32_t insert_at = 0;
    int off = find_prop(f, node, name, &insert_at);
    if (off < 0 && off != FDT_ERR_NOTFOUND) return off;
    int nameoff = find_string(f, name);
    uint32_t name_bytes = nameoff < 0 ? str_len(name) + 1 : 0;
    uint32_t old_bytes = 0;
    if (off >= 0) old_bytes = align4(rd32(f->buf + hdr(f, H_OFF_STRUCT) + off + 4));
    uint32_t new_bytes = align4(len) + (off >= 0 ? 0 : 12);
    uint64_t need = (uint64_t)data_end(f) + new_bytes - old_bytes + name_bytes;
    if (len > f->capacity || need > f->capacity) return FDT_ERR_NOSPACE;

    if (nameoff < 0) { /* append the name to the strings block (it is last) */
        uint32_t end = data_end(f);
        move_bytes(f->buf + end, (const uint8_t *)name, name_bytes);
        nameoff = (int)hdr(f, H_SIZE_STRINGS);
        set_hdr(f, H_SIZE_STRINGS, hdr(f, H_SIZE_STRINGS) + name_bytes);
        set_hdr(f, H_TOTALSIZE, data_end(f));
    }
    uint32_t at;
    if (off >= 0) {
        at = (uint32_t)off;
        shift_struct(f, at + 12, (int32_t)align4(len) - (int32_t)old_bytes);
    } else {
        at = insert_at;
        shift_struct(f, at, (int32_t)(align4(len) + 12));
    }
    uint8_t *p = f->buf + hdr(f, H_OFF_STRUCT) + at;
    wr32(p, TAG_PROP);
    wr32(p + 4, len);
    wr32(p + 8, (uint32_t)nameoff);
    move_bytes(p + 12, (const uint8_t *)value, len);
    zero_bytes(p + 12 + len, align4(len) - len);
    return FDT_OK;
}

int fdt_del_prop(struct fdt *f, int node, const char *name) {
    int off = find_prop(f, node, name, 0);
    if (off < 0) return off;
    uint32_t bytes = 12 + align4(rd32(f->buf + hdr(f, H_OFF_STRUCT) + off + 4));
    shift_struct(f, (uint32_t)off, -(int32_t)bytes);
    return FDT_OK;
}

int fdt_add_subnode(struct fdt *f, int parent, const char *name) {
    uint32_t len = str_len(name);
    if (!len) return FDT_ERR_BADNAME;
    for (uint32_t i = 0; i < len; i++)
        if (name[i] == '/') return FDT_ERR_BADNAME;
    int existing = find_child(f, parent, name, len);
    if (existing >= 0 && str_eq(node_name(f, (uint32_t)existing), name)) return FDT_ERR_EXISTS;
    if (existing < 0 && existing != FDT_ERR_NOTFOUND) return existing;
    uint32_t at = 0;
    int r = find_prop(f, parent, "\x01", &at); /* no property has this name */
    if (r != FDT_ERR_NOTFOUND) return r < 0 ? r : FDT_ERR_STRUCT;
    uint32_t bytes = 4 + align4(len + 1) + 4;
    if ((uint64_t)data_end(f) + bytes > f->capacity) return FDT_ERR_NOSPACE;
    shift_struct(f, at, (int32_t)bytes);
    uint8_t *p = f->buf + hdr(f, H_OFF_STRUCT) + at;
    wr32(p, TAG_BEGIN_NODE);
    move_bytes(p + 4, (const uint8_t *)name, len);
    wr32(p + 4 + align4(len + 1), TAG_END_NODE);
    return (int)at;
}

static int cells(const struct fdt *f, int node, const char *name, uint32_t fallback) {
    const uint8_t *v;
    uint32_t len;
    if (fdt_get_prop(f, node, name, &v, &len) != FDT_OK) return (int)fallback;
    if (len != 4) return FDT_ERR_CELLS;
    uint32_t n = rd32(v);
    return (n == 1 || n == 2) ? (int)n : FDT_ERR_CELLS;
}

/* Encodes <address size> using the given cell counts; returns bytes or error. */
static int encode_reg(uint8_t *out, int acells, int scells, uint64_t addr, uint64_t size) {
    if (acells < 0 || scells < 0) return FDT_ERR_CELLS;
    if ((acells == 1 && addr >> 32) || (scells == 1 && size >> 32)) return FDT_ERR_CELLS;
    uint32_t n = 0;
    if (acells == 2) { wr32(out + n, (uint32_t)(addr >> 32)); n += 4; }
    wr32(out + n, (uint32_t)addr); n += 4;
    if (scells == 2) { wr32(out + n, (uint32_t)(size >> 32)); n += 4; }
    wr32(out + n, (uint32_t)size); n += 4;
    return (int)n;
}

static int set_u32(struct fdt *f, int node, const char *name, uint32_t v) {
    uint8_t b[4];
    wr32(b, v);
    return fdt_set_prop(f, node, name, b, 4);
}

static int set_u64(struct fdt *f, int node, const char *name, uint64_t v) {
    uint8_t b[8];
    wr32(b, (uint32_t)(v >> 32));
    wr32(b + 4, (uint32_t)v);
    return fdt_set_prop(f, node, name, b, 8);
}

static int set_str(struct fdt *f, int node, const char *name, const char *s) {
    return fdt_set_prop(f, node, name, s, str_len(s) + 1);
}

/* Node offsets move after every edit, so each step looks its node up again. */
int fdt_fill_linux(struct fdt *f, const struct fdt_linux_params *p) {
    uint8_t reg[16];
    int r, n;
    if (p->mem_size) {
        n = encode_reg(reg, cells(f, 0, "#address-cells", 2), cells(f, 0, "#size-cells", 1),
                       p->mem_base, p->mem_size);
        if (n < 0) return n;
        int mem = fdt_find(f, "/memory");
        if (mem < 0) return mem;
        if ((r = fdt_set_prop(f, mem, "reg", reg, (uint32_t)n)) != FDT_OK) return r;
    }
    int chosen = fdt_find(f, "/chosen");
    if (chosen == FDT_ERR_NOTFOUND) chosen = fdt_add_subnode(f, 0, "chosen");
    if (chosen < 0) return chosen;
    if (p->bootargs && (r = set_str(f, fdt_find(f, "/chosen"), "bootargs", p->bootargs)) != FDT_OK) return r;
    if (p->initrd_end > p->initrd_start) {
        if ((r = set_u64(f, fdt_find(f, "/chosen"), "linux,initrd-start", p->initrd_start)) != FDT_OK) return r;
        if ((r = set_u64(f, fdt_find(f, "/chosen"), "linux,initrd-end", p->initrd_end)) != FDT_OK) return r;
    }
    if (p->fb_base) {
        if (!p->fb_format || !p->fb_width || !p->fb_height || !p->fb_stride) return FDT_ERR_BADNAME;
        chosen = fdt_find(f, "/chosen");
        n = encode_reg(reg, cells(f, chosen, "#address-cells", 2), cells(f, chosen, "#size-cells", 1),
                       p->fb_base, (uint64_t)p->fb_stride * p->fb_height);
        if (n < 0) return n;
        if (fdt_find(f, "/chosen/framebuffer") < 0) return FDT_ERR_NOTFOUND;
        if ((r = fdt_set_prop(f, fdt_find(f, "/chosen/framebuffer"), "reg", reg, (uint32_t)n)) != FDT_OK) return r;
        if ((r = set_u32(f, fdt_find(f, "/chosen/framebuffer"), "width", p->fb_width)) != FDT_OK) return r;
        if ((r = set_u32(f, fdt_find(f, "/chosen/framebuffer"), "height", p->fb_height)) != FDT_OK) return r;
        if ((r = set_u32(f, fdt_find(f, "/chosen/framebuffer"), "stride", p->fb_stride)) != FDT_OK) return r;
        if ((r = set_str(f, fdt_find(f, "/chosen/framebuffer"), "format", p->fb_format)) != FDT_OK) return r;
        if ((r = set_str(f, fdt_find(f, "/chosen/framebuffer"), "status", "okay")) != FDT_OK) return r;
    }
    return FDT_OK;
}
