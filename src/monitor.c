/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Portable monitor: all device access goes through platform.h. */
#include <stdint.h>
#include <stddef.h>
#include "exception.h"
#include "framebuffer.h"
#include "linux_boot.h"
#include "monitor.h"
#include "platform.h"

static char line[80];
static volatile uint64_t bss_probe;
static struct fb_console fb;
static int fb_active;

/* Linker-script symbols bounding the monitor image, BSS, and stack. */
extern char __image_start[], __stack_top[];

static void serial_putc(char c) {
    platform_console_putc(c);
}

/* Console output: serial always, mirrored to the framebuffer when attached. */
static void putch(char c) {
    serial_putc(c);
    if (fb_active) fb_console_putc(&fb, c);
}

static void puts_serial(const char *s) {
    while (*s) {
        if (*s == '\n') putch('\r');
        putch(*s++);
    }
}

static void put_hex_nibble(uint8_t n) {
    n &= 0x0f;
    putch(n < 10 ? (char)('0' + n) : (char)('a' + (n - 10)));
}

static void put_hex8(uint8_t val) {
    put_hex_nibble((uint8_t)(val >> 4));
    put_hex_nibble(val);
}

static void put_hex16(uint16_t val) {
    put_hex8((uint8_t)(val >> 8));
    put_hex8((uint8_t)val);
}

static void put_hex32(uint32_t val) {
    put_hex16((uint16_t)(val >> 16));
    put_hex16((uint16_t)val);
}

static void put_hex64(uint64_t val) {
    put_hex32((uint32_t)(val >> 32));
    put_hex32((uint32_t)val);
}

static const char *skip_spaces(const char *s) {
    while (*s == ' ' || *s == '\t') s++;
    return s;
}

static int parse_hex(const char **s, uint64_t *val) {
    const char *p = skip_spaces(*s);
    if (!*p) return 0;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
    }
    if (!*p) return 0;
    uint64_t res = 0;
    int digits = 0;
    while (*p) {
        char c = *p;
        uint8_t d;
        if (c >= '0' && c <= '9') d = (uint8_t)(c - '0');
        else if (c >= 'a' && c <= 'f') d = (uint8_t)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') d = (uint8_t)(c - 'A' + 10);
        else break;
        res = (res << 4) | (uint64_t)d;
        digits++;
        p++;
    }
    if (digits == 0) return 0;
    *val = res;
    *s = p;
    return 1;
}

static int parse_dec(const char **s, uint64_t *val) {
    const char *p = skip_spaces(*s);
    uint64_t res = 0;
    int digits = 0;
    while (*p >= '0' && *p <= '9') {
        if (res > (UINT64_MAX - 9) / 10) return 0;
        res = res * 10 + (uint64_t)(*p - '0');
        digits++;
        p++;
    }
    if (digits == 0 || (*p != '\0' && *p != ' ' && *p != '\t')) return 0;
    *val = res;
    *s = p;
    return 1;
}

static void put_dec(uint64_t val) {
    char buf[20];
    int n = 0;
    do { buf[n++] = (char)('0' + val % 10); val /= 10; } while (val);
    while (n) putch(buf[--n]);
}

static int cmd_match(const char *input, const char *cmd) {
    while (*cmd) {
        if (*input != *cmd) return 0;
        input++;
        cmd++;
    }
    return (*input == ' ' || *input == '\0');
}

static void cmd_echo(const char *args) {
    const char *p = skip_spaces(args);
    puts_serial(p);
    puts_serial("\n");
}

static void cmd_peek(const char *args) {
    uint64_t addr = 0;
    if (!parse_hex(&args, &addr)) {
        puts_serial("Usage: peek <hex_addr>\n");
        return;
    }
    if (addr & 3) {
        puts_serial("Error: address must be 4-byte aligned\n");
        return;
    }
    uint32_t val = *(volatile uint32_t *)(uintptr_t)addr;
    puts_serial("[0x");
    put_hex64(addr);
    puts_serial("] = 0x");
    put_hex32(val);
    puts_serial("\n");
}

static void cmd_poke(const char *args) {
    uint64_t addr = 0;
    uint64_t val = 0;
    if (!parse_hex(&args, &addr) || !parse_hex(&args, &val)) {
        puts_serial("Usage: poke <hex_addr> <hex_val>\n");
        return;
    }
    if (addr & 3) {
        puts_serial("Error: address must be 4-byte aligned\n");
        return;
    }
    *(volatile uint32_t *)(uintptr_t)addr = (uint32_t)val;
    puts_serial("[0x");
    put_hex64(addr);
    puts_serial("] <= 0x");
    put_hex32((uint32_t)val);
    puts_serial("\n");
}

static void cmd_dump(const char *args) {
    uint64_t addr = 0;
    uint64_t count = 16;
    if (!parse_hex(&args, &addr)) {
        puts_serial("Usage: dump <hex_addr> [count_hex]\n");
        return;
    }
    if (parse_hex(&args, &count)) {
        if (count > 64) count = 64;
        if (count == 0) count = 16;
    }
    uint64_t rows = (count + 15) / 16;
    for (uint64_t r = 0; r < rows; r++) {
        uint64_t row_addr = addr + r * 16;
        put_hex64(row_addr);
        puts_serial(": ");
        for (uint64_t i = 0; i < 16; i++) {
            if (i == 8) putch(' ');
            uint8_t byte = *(volatile uint8_t *)(uintptr_t)(row_addr + i);
            put_hex8(byte);
            putch(' ');
        }
        puts_serial(" |");
        for (uint64_t i = 0; i < 16; i++) {
            uint8_t byte = *(volatile uint8_t *)(uintptr_t)(row_addr + i);
            if (byte >= 32 && byte <= 126) putch((char)byte);
            else putch('.');
        }
        puts_serial("|\n");
    }
}

static inline uint64_t read_current_el(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(val));
    return val;
}

static inline uint64_t read_daif(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, DAIF" : "=r"(val));
    return val;
}

static inline uint64_t read_sp(void) {
    uint64_t val;
    __asm__ volatile("mov %0, sp" : "=r"(val));
    return val;
}

static void cmd_regs(void) {
    uint64_t el = read_current_el();
    uint64_t vbar = exception_vbar();
    uint64_t daif = read_daif();
    uint64_t sp = read_sp();

    puts_serial("CurrentEL: EL");
    put_hex_nibble((uint8_t)(el >> 2));
    puts_serial(" (raw 0x");
    put_hex64(el);
    puts_serial(")\nDAIF:      0x");
    put_hex64(daif);
    puts_serial(" [D=");
    putch((daif & (1ULL << 9)) ? '1' : '0');
    puts_serial(" A=");
    putch((daif & (1ULL << 8)) ? '1' : '0');
    puts_serial(" I=");
    putch((daif & (1ULL << 7)) ? '1' : '0');
    puts_serial(" F=");
    putch((daif & (1ULL << 6)) ? '1' : '0');
    puts_serial("]\nSP:        0x");
    put_hex64(sp);
    puts_serial("\nVBAR:      0x");
    put_hex64(vbar);
    puts_serial("\n");
}

static void cmd_probe(const char *args) {
    uint64_t addr = 0;
    if (!parse_hex(&args, &addr)) {
        puts_serial("Usage: probe <hex_addr>\n");
        return;
    }
    if (addr & 7) {
        puts_serial("Error: address must be 8-byte aligned\n");
        return;
    }
    const uint8_t *rec = (const uint8_t *)(uintptr_t)addr;
    const char magic[8] = {'M', '1', 'P', 'R', 'O', 'B', 'E', '\0'};
    for (int i = 0; i < 8; i++) {
        if (rec[i] != (uint8_t)magic[i]) {
            puts_serial("Error: invalid probe magic (expected M1PROBE)\n");
            return;
        }
    }
    uint32_t version = *(const volatile uint32_t *)(uintptr_t)(addr + 8);
    uint32_t size = *(const volatile uint32_t *)(uintptr_t)(addr + 12);
    uint64_t status = *(const volatile uint64_t *)(uintptr_t)(addr + 16);
    uint64_t x0 = *(const volatile uint64_t *)(uintptr_t)(addr + 24);
    uint64_t x1 = *(const volatile uint64_t *)(uintptr_t)(addr + 32);
    uint64_t x2 = *(const volatile uint64_t *)(uintptr_t)(addr + 40);
    uint64_t x3 = *(const volatile uint64_t *)(uintptr_t)(addr + 48);
    uint64_t sp = *(const volatile uint64_t *)(uintptr_t)(addr + 56);
    uint64_t entry_pc = *(const volatile uint64_t *)(uintptr_t)(addr + 64);
    uint64_t cur_el = *(const volatile uint64_t *)(uintptr_t)(addr + 72);
    uint64_t daif = *(const volatile uint64_t *)(uintptr_t)(addr + 80);

    puts_serial("M1PROBE record @ 0x");
    put_hex64(addr);
    puts_serial("\n  Version:   ");
    put_hex32(version);
    puts_serial("\n  Size:      ");
    put_hex32(size);
    puts_serial(" bytes\n  Status:    ");
    if (status == 1) puts_serial("captured (1)\n");
    else if (status == 0) puts_serial("pending (0)\n");
    else {
        puts_serial("unknown (0x");
        put_hex64(status);
        puts_serial(")\n");
    }
    puts_serial("  Entry PC:  0x");
    put_hex64(entry_pc);
    puts_serial("\n  Exception: EL");
    put_hex_nibble((uint8_t)(cur_el >> 2));
    puts_serial(" (CurrentEL raw 0x");
    put_hex64(cur_el);
    puts_serial(")\n  DAIF:      0x");
    put_hex64(daif);
    puts_serial("\n  SP:        0x");
    put_hex64(sp);
    puts_serial("\n  x0:        0x");
    put_hex64(x0);
    puts_serial("\n  x1:        0x");
    put_hex64(x1);
    puts_serial("\n  x2:        0x");
    put_hex64(x2);
    puts_serial("\n  x3:        0x");
    put_hex64(x3);
    puts_serial("\n");
}

static void cmd_fb(const char *args) {
    const char *p = skip_spaces(args);
    if (!*p) {
        if (!fb_active) { puts_serial("fb: off\n"); return; }
        puts_serial("fb: 0x");
        put_hex64((uint64_t)(uintptr_t)fb.base);
        puts_serial(" ");
        put_dec(fb.width);
        puts_serial("x");
        put_dec(fb.height);
        puts_serial(" stride ");
        put_dec(fb.stride);
        puts_serial(" scale ");
        put_dec(fb.scale);
        puts_serial(" ");
        puts_serial(fb_format_name(fb.format));
        puts_serial(" (");
        put_dec(fb.cols);
        puts_serial("x");
        put_dec(fb.rows);
        puts_serial(" cells)\n");
        return;
    }
    if (cmd_match(p, "off")) {
        fb_active = 0;
        puts_serial("fb: detached\n");
        return;
    }
    uint64_t addr, width, height, stride, scale = 1;
    uint32_t format = FB_FORMAT_X8R8G8B8;
    int ok = parse_hex(&p, &addr) && parse_dec(&p, &width) && parse_dec(&p, &height) &&
             parse_dec(&p, &stride);
    if (ok && *skip_spaces(p) >= '0' && *skip_spaces(p) <= '9') ok = parse_dec(&p, &scale);
    if (ok && *skip_spaces(p)) {
        p = skip_spaces(p);
        if (cmd_match(p, "x8r8g8b8")) { format = FB_FORMAT_X8R8G8B8; p += 8; }
        else if (cmd_match(p, "x2r10g10b10")) { format = FB_FORMAT_X2R10G10B10; p += 11; }
        else ok = 0;
    }
    if (!ok || *skip_spaces(p)) {
        puts_serial("Usage: fb <hex_addr> <width> <height> <stride_bytes> [scale] [x8r8g8b8|x2r10g10b10] | fb off\n");
        return;
    }
    if (width > UINT32_MAX || height > UINT32_MAX || stride > UINT32_MAX || scale > UINT32_MAX) {
        puts_serial("Error: framebuffer geometry out of range\n");
        return;
    }
    struct fb_console next;
    int err = fb_console_init(&next, addr, (uint32_t)width, (uint32_t)height,
                              (uint32_t)stride, (uint32_t)scale, format, 0x00e0e0e0U, 0x00102040U);
    if (err == FB_ERR_ALIGN) { puts_serial("Error: framebuffer address and stride must be 4-byte aligned\n"); return; }
    if (err == FB_ERR_SCALE) { puts_serial("Error: framebuffer scale must be 1-8\n"); return; }
    if (err == FB_ERR_STRIDE) { puts_serial("Error: framebuffer stride must be >= width*4\n"); return; }
    if (err != FB_OK) { puts_serial("Error: framebuffer geometry out of range\n"); return; }
    uint64_t lo = (uint64_t)(uintptr_t)__image_start;
    uint64_t hi = (uint64_t)(uintptr_t)__stack_top;
    if (addr < hi && addr + fb_console_span(&next) > lo) {
        puts_serial("Error: framebuffer overlaps the monitor image or stack\n");
        return;
    }
    fb = next;
    fb_console_clear(&fb);
    fb_active = 1;
    puts_serial("fb: attached ");
    put_dec(fb.cols);
    puts_serial("x");
    put_dec(fb.rows);
    puts_serial(" cells\n");
}

static void cmd_kimage(const char *args) {
    static const char *const errors[] = {
        "", "header too short", "bad magic (not an uncompressed ARM64 Image)",
        "image_size is 0 (pre-v3.17 header; unsupported)", "big-endian kernel",
        "reserved flag bits set", "text_offset not 4 KB aligned below 2 MB",
        "file larger than image_size",
    };
    uint64_t addr = 0;
    if (!parse_hex(&args, &addr)) {
        puts_serial("Usage: kimage <hex_addr>\n");
        return;
    }
    if (addr & 7) {
        puts_serial("Error: address must be 8-byte aligned\n");
        return;
    }
    uint8_t header[LINUX_IMAGE_HEADER_SIZE];
    for (unsigned i = 0; i < sizeof(header); i++)
        header[i] = *(volatile const uint8_t *)(uintptr_t)(addr + i);
    struct linux_image_info info;
    int err = linux_image_parse(header, sizeof(header), 0, &info);
    if (err != LINUX_OK) {
        puts_serial("Not a usable Linux Image: ");
        puts_serial(errors[err]);
        puts_serial("\n");
        return;
    }
    puts_serial("ARM64 Linux Image @ 0x");
    put_hex64(addr);
    puts_serial("\n  text_offset: 0x");
    put_hex64(info.text_offset);
    puts_serial("\n  image_size:  0x");
    put_hex64(info.image_size);
    puts_serial("\n  page size:   ");
    if (info.page_size_kb) { put_dec(info.page_size_kb); puts_serial(" KB"); }
    else puts_serial("unspecified");
    puts_serial("\n  placement:   ");
    puts_serial(info.anywhere ? "anywhere (48-bit)" : "near DRAM start");
    puts_serial("\n");
}

static void dispatch(void) {
    if (cmd_match(line, "help")) {
        puts_serial("help  info  status  echo  dump  peek  poke  regs  probe  kimage  fb  trap  clear\n");
    } else if (cmd_match(line, "info")) {
        puts_serial("ARM64 / ");
        puts_serial(platform_name());
        puts_serial(" / single CPU / MMU off\n");
    } else if (cmd_match(line, "status")) {
        puts_serial("Independent monitor. Apple boot: unimplemented. Linux handoff: unimplemented.\n");
        puts_serial("Exceptions recovered: ");
        put_dec(exception_count());
        puts_serial("\n");
    } else if (cmd_match(line, "echo")) {
        cmd_echo(line + 4);
    } else if (cmd_match(line, "dump")) {
        cmd_dump(line + 4);
    } else if (cmd_match(line, "peek")) {
        cmd_peek(line + 4);
    } else if (cmd_match(line, "poke")) {
        cmd_poke(line + 4);
    } else if (cmd_match(line, "regs")) {
        cmd_regs();
    } else if (cmd_match(line, "probe")) {
        cmd_probe(line + 5);
    } else if (cmd_match(line, "kimage")) {
        cmd_kimage(line + 6);
    } else if (cmd_match(line, "trap")) {
        /* Deliberate breakpoint: checks that exception vectors report and recover. */
        __asm__ volatile("brk #0x4d31");
    } else if (cmd_match(line, "fb")) {
        cmd_fb(line + 2);
    } else if (cmd_match(line, "clear")) {
        /* The escape sequence is for serial terminals; clear the framebuffer directly. */
        for (const char *e = "\033[2J\033[H"; *e; e++) serial_putc(*e);
        if (fb_active) fb_console_clear(&fb);
    } else if (*line) {
        puts_serial("Unknown command. Type help.\n");
    }
}

void console_putc(char c) { putch(c); }
void console_puts(const char *s) { puts_serial(s); }
void console_put_hex64(uint64_t val) { put_hex64(val); }

static void __attribute__((noreturn)) command_loop(void) {
    size_t used = 0;
    int overflow = 0;
    int previous_cr = 0;
    for (;;) {
        char c = platform_console_getc();
        if (c == '\n' && previous_cr) { previous_cr = 0; continue; }
        previous_cr = c == '\r';
        if (c == '\r' || c == '\n') {
            puts_serial("\n");
            line[used] = 0;
            if (overflow) puts_serial("Line too long; command discarded.\n");
            else dispatch();
            used = 0;
            overflow = 0;
            puts_serial("> ");
        } else if (!overflow && (c == '\b' || c == 127)) {
            if (used) { --used; puts_serial("\b \b"); }
        } else if (!overflow && c >= 32 && c <= 126) {
            if (used < sizeof(line) - 1) { line[used++] = c; putch(c); }
            else overflow = 1;
        }
    }
}

void monitor_resume(void) {
    puts_serial("> ");
    command_loop();
}

void monitor_main(void) {
    platform_console_init();
    if (bss_probe != 0) {
        puts_serial("FAIL: BSS not cleared\n");
        for (;;) {}
    }
    puts_serial("Independent ARM64 monitor v0.1\nBSS cleared; serial ready.\n> ");
    command_loop();
}
