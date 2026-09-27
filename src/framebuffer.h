/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FRAMEBUFFER_H
#define FRAMEBUFFER_H

#include <stdint.h>

/*
 * Linear framebuffer text console. Each pixel is one little-endian 32-bit word,
 * 0x00RRGGBB. The caller supplies every geometry value; this file assumes no
 * display address or pixel format for any machine. Apple's firmware-provided
 * display format and writeability are unverified.
 */
struct fb_console {
    volatile uint32_t *base;
    uint32_t width, height; /* pixels */
    uint32_t stride;        /* bytes per pixel row, >= width * 4 */
    uint32_t scale;         /* integer glyph magnification */
    uint32_t cols, rows;    /* character cells */
    uint32_t col, row;      /* cursor; col == cols means a deferred wrap */
    uint32_t fg, bg;
};

enum fb_status {
    FB_OK = 0,
    FB_ERR_ALIGN,    /* base or stride not 4-byte aligned */
    FB_ERR_GEOMETRY, /* size out of range, or smaller than one character cell */
    FB_ERR_STRIDE,   /* stride shorter than a pixel row or out of range */
    FB_ERR_SCALE,    /* scale outside FB_MIN_SCALE..FB_MAX_SCALE */
    FB_ERR_RANGE,    /* base + stride * height wraps the address space */
};

#define FB_MAX_DIMENSION 8192U
#define FB_MAX_STRIDE (FB_MAX_DIMENSION * 4U * 2U)
#define FB_MIN_SCALE 1U
#define FB_MAX_SCALE 8U

/* Validates geometry and fills *fb. Does not touch framebuffer memory. */
int fb_console_init(struct fb_console *fb, uint64_t base, uint32_t width,
                    uint32_t height, uint32_t stride, uint32_t scale,
                    uint32_t fg, uint32_t bg);
/* Size in bytes of the memory the console may access. */
uint64_t fb_console_span(const struct fb_console *fb);
void fb_console_clear(struct fb_console *fb);
/* Handles printable ASCII, '\n', '\r', and '\b'; ignores everything else. */
void fb_console_putc(struct fb_console *fb, char c);

#endif /* FRAMEBUFFER_H */
