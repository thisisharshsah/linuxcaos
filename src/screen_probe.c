/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * M1 screen probe: the first experiment designed for a Mac with no second
 * machine. It reads boot_args through the incoming x0 (documented by Asahi as
 * the boot_args pointer, unverified here), draws colour bars and a text report
 * of the entry state on the firmware framebuffer, and parks. Its only memory
 * accesses are its own image, the 736-byte boot_args, and the framebuffer. If
 * boot_args or the framebuffer description fails validation it draws nothing.
 *
 * Keep this file free of tables of pointers: the image is position-independent
 * only because it contains no absolute addresses (the build verifies this).
 */
#include <stdint.h>
#include "bootargs.h"
#include "framebuffer.h"

struct probe_entry_state {
    uint64_t x0, x1, x2, x3, sp, pc, current_el, daif;
};

struct probe_entry_state probe_entry; /* filled by screen_probe_entry.S */
static struct fb_console fb;
static uint8_t args_copy[BOOTARGS_SIZE];

static void out(char c) { fb_console_putc(&fb, c); }

static void puts_fb(const char *s) {
    while (*s) out(*s++);
}

static void hex(uint64_t v) {
    puts_fb("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned n = (unsigned)(v >> shift) & 15;
        out((char)(n < 10 ? '0' + n : 'a' + n - 10));
    }
}

static void dec(uint64_t v) {
    char buf[20];
    int n = 0;
    do { buf[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) out(buf[--n]);
}

static void field(const char *name, uint64_t value) {
    puts_fb(name);
    hex(value);
    out('\n');
}

/* Colour bars (red, green, blue, white) across the top: a photo of them shows
 * whether the pixel format guess is right. */
static void draw_bars(const struct bootargs *b) {
    static const uint32_t colors[4] = {0x00ff0000U, 0x0000ff00U, 0x000000ffU, 0x00ffffffU};
    volatile uint32_t *base = (volatile uint32_t *)(uintptr_t)b->video_base;
    uint32_t width = (uint32_t)b->video_width;
    uint32_t bar_height = (uint32_t)(b->video_height / 16);
    for (uint32_t y = 0; y < bar_height; y++) {
        volatile uint32_t *row = base + (uint64_t)y * (b->video_row_bytes / 4);
        for (uint32_t x = 0; x < width; x++)
            row[x] = fb_encode_color(b->pixel_format, colors[(x * 4) / width]);
    }
}

void screen_probe_main(void) {
    /* Copy boot_args with byte loads before parsing; never follow its pointers. */
    if (!probe_entry.x0 || (probe_entry.x0 & 7)) return;
    const volatile uint8_t *src = (const volatile uint8_t *)(uintptr_t)probe_entry.x0;
    for (unsigned i = 0; i < BOOTARGS_SIZE; i++) args_copy[i] = src[i];

    struct bootargs b;
    if (bootargs_parse(args_copy, &b) != BOOTARGS_OK || !b.video_ok) return;
    uint32_t scale = b.video_width >= 1600 ? 2 : 1;
    uint32_t bar_height = (uint32_t)(b.video_height / 16);
    if (fb_console_init(&fb, b.video_base + (uint64_t)bar_height * b.video_row_bytes,
                        (uint32_t)b.video_width, (uint32_t)(b.video_height - bar_height),
                        (uint32_t)b.video_row_bytes, scale, b.pixel_format,
                        0x00ffffffU, 0x00000000U) != FB_OK)
        return;
    draw_bars(&b);
    fb_console_clear(&fb);

    puts_fb("Independent M1 screen probe v1 (GPL-2.0-or-later)\n\n");
    field("entry pc     ", probe_entry.pc);
    puts_fb("CurrentEL    EL");
    out((char)('0' + ((probe_entry.current_el >> 2) & 3)));
    out('\n');
    field("DAIF         ", probe_entry.daif);
    field("incoming sp  ", probe_entry.sp);
    field("x0           ", probe_entry.x0);
    field("x1           ", probe_entry.x1);
    field("x2           ", probe_entry.x2);
    field("x3           ", probe_entry.x3);
    puts_fb("\nboot_args    revision ");
    dec(b.revision);
    puts_fb(" version ");
    dec(b.version);
    out('\n');
    field("virt_base    ", b.virt_base);
    field("phys_base    ", b.phys_base);
    field("mem_size     ", b.mem_size);
    field("top_of_kdata ", b.top_of_kdata);
    field("device_tree  ", b.device_tree);
    field("boot_flags   ", b.boot_flags);
    puts_fb("video        ");
    hex(b.video_base);
    out(' ');
    dec(b.video_width);
    out('x');
    dec(b.video_height);
    puts_fb(" stride ");
    dec(b.video_row_bytes);
    puts_fb(" depth ");
    dec(b.depth_bits);
    /* Direct literals rather than a helper returning pointers: keeps the
     * image free of any table of absolute addresses (the build checks this). */
    puts_fb(b.pixel_format == FB_FORMAT_X2R10G10B10 ? " x2r10g10b10" : " x8r8g8b8");
    puts_fb(b.video_in_ram ? " (inside RAM range)\n" : "\n");
    puts_fb("command line ");
    for (unsigned i = 0; i < 120; i++) {
        char c = (char)args_copy[BOOTARGS_CMDLINE_OFFSET + i];
        if (!c) break;
        out(c >= 32 && c <= 126 ? c : '?');
    }
    puts_fb("\n\nBars above: red, green, blue, white if the pixel format is right.\n");
    puts_fb("Parked. Photograph this screen, then hold the power button to turn off.\n");
}
