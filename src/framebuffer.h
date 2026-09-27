/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FRAMEBUFFER_H
#define FRAMEBUFFER_H

#include <stdint.h>

/*
 * Linear framebuffer text console. Each pixel is one little-endian 32-bit word
 * in one of the formats below (names match Linux simple-framebuffer). The
 * caller supplies every geometry value and the format; nothing here assumes a
 * display for any machine. Apple's display format and writeability are unverified.
 */
enum fb_format {
    FB_FORMAT_X8R8G8B8 = 0,    /* 0x00RRGGBB */
    FB_FORMAT_X2R10G10B10 = 1, /* 2 unused bits, then 10 bits each of R, G, B */
};
struct fb_console {
    volatile uint32_t *base;
    uint32_t width, height; /* pixels */
    uint32_t stride;        /* bytes per pixel row, >= width * 4 */
    uint32_t scale;         /* integer glyph magnification */
    uint32_t cols, rows;    /* character cells */
    uint32_t col, row;      /* cursor; col == cols means a deferred wrap */
    uint32_t fg, bg;        /* already encoded in the pixel format */
    uint32_t format;
};

enum fb_status {
    FB_OK = 0,
    FB_ERR_ALIGN,    /* base or stride not 4-byte aligned */
    FB_ERR_GEOMETRY, /* size out of range, or smaller than one character cell */
    FB_ERR_STRIDE,   /* stride shorter than a pixel row or out of range */
    FB_ERR_SCALE,    /* scale outside FB_MIN_SCALE..FB_MAX_SCALE */
    FB_ERR_RANGE,    /* base + stride * height wraps the address space */
    FB_ERR_FORMAT,   /* unknown pixel format */
};

#define FB_MAX_DIMENSION 8192U
#define FB_MAX_STRIDE (FB_MAX_DIMENSION * 4U * 2U)
#define FB_MIN_SCALE 1U
#define FB_MAX_SCALE 8U

/* Validates geometry and fills *fb. Colors are 0x00RRGGBB and are converted to
 * the pixel format. Does not touch framebuffer memory. */
int fb_console_init(struct fb_console *fb, uint64_t base, uint32_t width,
                    uint32_t height, uint32_t stride, uint32_t scale,
                    uint32_t format, uint32_t fg_rgb, uint32_t bg_rgb);
/* Converts 0x00RRGGBB to a pixel word in the given format. */
uint32_t fb_encode_color(uint32_t format, uint32_t rgb);
/* Linux simple-framebuffer name of a format, or 0 if unknown. */
const char *fb_format_name(uint32_t format);
/* Size in bytes of the memory the console may access. */
uint64_t fb_console_span(const struct fb_console *fb);
void fb_console_clear(struct fb_console *fb);
/* Handles printable ASCII, '\n', '\r', and '\b'; ignores everything else. */
void fb_console_putc(struct fb_console *fb, char c);

#endif /* FRAMEBUFFER_H */
