/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "framebuffer.h"
#include "font.h"

/*
 * All framebuffer accesses are aligned volatile 32-bit words: this keeps the
 * compiler from emitting memset/memcpy calls (there is no libc) and avoids
 * unaligned accesses, which fault on Device memory while the MMU is off.
 */

int fb_console_init(struct fb_console *fb, uint64_t base, uint32_t width,
                    uint32_t height, uint32_t stride, uint32_t scale,
                    uint32_t fg, uint32_t bg) {
    if ((base & 3) || (stride & 3)) return FB_ERR_ALIGN;
    if (scale < FB_MIN_SCALE || scale > FB_MAX_SCALE) return FB_ERR_SCALE;
    if (width == 0 || height == 0 || width > FB_MAX_DIMENSION || height > FB_MAX_DIMENSION)
        return FB_ERR_GEOMETRY;
    if (width < FONT_WIDTH * scale || height < FONT_HEIGHT * scale) return FB_ERR_GEOMETRY;
    if ((uint64_t)stride < (uint64_t)width * 4 || stride > FB_MAX_STRIDE) return FB_ERR_STRIDE;
    uint64_t span = (uint64_t)stride * height;
    if (base > UINT64_MAX - span) return FB_ERR_RANGE;

    fb->base = (volatile uint32_t *)(uintptr_t)base;
    fb->width = width;
    fb->height = height;
    fb->stride = stride;
    fb->scale = scale;
    fb->cols = width / (FONT_WIDTH * scale);
    fb->rows = height / (FONT_HEIGHT * scale);
    fb->col = 0;
    fb->row = 0;
    fb->fg = fg;
    fb->bg = bg;
    return FB_OK;
}

uint64_t fb_console_span(const struct fb_console *fb) {
    return (uint64_t)fb->stride * fb->height;
}

static volatile uint32_t *pixel_row(const struct fb_console *fb, uint32_t y) {
    return fb->base + (uint64_t)y * (fb->stride / 4);
}

static void fill_rows(struct fb_console *fb, uint32_t y0, uint32_t y1) {
    for (uint32_t y = y0; y < y1; y++) {
        volatile uint32_t *p = pixel_row(fb, y);
        for (uint32_t x = 0; x < fb->width; x++) p[x] = fb->bg;
    }
}

void fb_console_clear(struct fb_console *fb) {
    fill_rows(fb, 0, fb->height);
    fb->col = 0;
    fb->row = 0;
}

static void draw_glyph(struct fb_console *fb, char c) {
    const uint8_t *glyph = font8x16[(unsigned char)c - FONT_FIRST_CHAR];
    uint32_t s = fb->scale;
    uint32_t x0 = fb->col * FONT_WIDTH * s;
    uint32_t y0 = fb->row * FONT_HEIGHT * s;
    for (uint32_t gy = 0; gy < FONT_HEIGHT; gy++) {
        uint8_t bits = glyph[gy];
        for (uint32_t sy = 0; sy < s; sy++) {
            volatile uint32_t *p = pixel_row(fb, y0 + gy * s + sy) + x0;
            for (uint32_t gx = 0; gx < FONT_WIDTH; gx++) {
                uint32_t color = (bits & (0x80U >> gx)) ? fb->fg : fb->bg;
                for (uint32_t sx = 0; sx < s; sx++) *p++ = color;
            }
        }
    }
}

/* Moves every text row up by one; pixels below the last full row are untouched. */
static void scroll(struct fb_console *fb) {
    uint32_t line = FONT_HEIGHT * fb->scale;
    uint32_t used = fb->rows * line;
    for (uint32_t y = line; y < used; y++) {
        volatile uint32_t *dst = pixel_row(fb, y - line);
        volatile uint32_t *src = pixel_row(fb, y);
        for (uint32_t x = 0; x < fb->width; x++) dst[x] = src[x];
    }
    fill_rows(fb, used - line, used);
}

static void newline(struct fb_console *fb) {
    fb->col = 0;
    if (fb->row + 1 < fb->rows) fb->row++;
    else scroll(fb);
}

void fb_console_putc(struct fb_console *fb, char c) {
    if (c == '\n') {
        newline(fb);
    } else if (c == '\r') {
        fb->col = 0;
    } else if (c == '\b') {
        if (fb->col) fb->col--;
    } else if (c >= FONT_FIRST_CHAR && c <= FONT_LAST_CHAR) {
        if (fb->col == fb->cols) newline(fb);
        draw_glyph(fb, c);
        fb->col++;
    }
}
