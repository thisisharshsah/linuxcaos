# SPDX-License-Identifier: GPL-2.0-or-later
PYTHON ?= .venv/bin/python
ZIG = $(PYTHON) -m ziglang
# Project-local compiler cache, removed by `make clean`, so a clean build is
# fully self-contained. (GNU Make 3.81 on macOS compares whole-second
# timestamps; after rapid in-place edits, run `make clean` before trusting a build.)
export ZIG_LOCAL_CACHE_DIR = $(CURDIR)/build/zig-cache
export ZIG_GLOBAL_CACHE_DIR = $(CURDIR)/build/zig-cache
# -mstrict-align: with the MMU off all memory is Device memory, where unaligned
# accesses fault, so the compiler must never merge accesses into unaligned ones.
CFLAGS = -target aarch64-freestanding-none -mcpu=cortex_a57 -ffreestanding -fno-stack-protector -fno-pic -mgeneral-regs-only -mstrict-align -Wall -Wextra -Werror -O2 -nostdlib

# Board support for the monitor: platform/<name>/{platform.c,link.ld}.
PLATFORM ?= qemu-virt
PLATFORM_DIR = platform/$(PLATFORM)
ifeq ($(wildcard $(PLATFORM_DIR)/platform.c),)
$(error Unknown PLATFORM '$(PLATFORM)'; available: $(notdir $(patsubst %/,%,$(dir $(wildcard platform/*/platform.c)))))
endif

.PHONY: all probe screen-probe font host test run console clean
all: build/monitor.bin build/entry-probe.bin build/screen-probe.bin

probe: build/entry-probe.bin

MONITOR_SRC = src/start.S src/vectors.S src/monitor.c src/exception.c src/framebuffer.c src/linux_boot.c $(PLATFORM_DIR)/platform.c
MONITOR_HDR = src/exception.h src/framebuffer.h src/font.h src/linux_boot.h src/monitor.h src/platform.h

build/monitor.elf: $(MONITOR_SRC) $(MONITOR_HDR) $(PLATFORM_DIR)/link.ld
	mkdir -p build
	$(ZIG) cc $(CFLAGS) -Isrc -Wl,-T,$(PLATFORM_DIR)/link.ld -Wl,--build-id=none $(MONITOR_SRC) -o $@

build/monitor.bin: build/monitor.elf tools/elf_to_binary.py
	$(PYTHON) tools/elf_to_binary.py $< $@

build/entry-probe.elf: src/entry_probe.S platform/entry-probe.ld
	mkdir -p build
	$(ZIG) cc $(CFLAGS) -Wl,-T,platform/entry-probe.ld -Wl,--build-id=none src/entry_probe.S -o $@

build/entry-probe.bin: build/entry-probe.elf tools/elf_to_binary.py
	$(PYTHON) tools/elf_to_binary.py --base 0 $< $@

# M1 screen probe: position-independent raw payload (see docs/SCREEN_PROBE.md).
# It is linked twice at different bases; identical bytes prove that the image
# contains no absolute addresses and can run wherever the firmware loads it.
SCREEN_SRC = src/screen_probe_entry.S src/screen_probe.c src/bootargs.c src/framebuffer.c
SCREEN_HDR = src/bootargs.h src/framebuffer.h src/font.h
# No jump or lookup tables: with -fno-pic they hold absolute addresses.
SCREEN_CFLAGS = -fno-zero-initialized-in-bss -fno-jump-tables
screen-probe: build/screen-probe.bin

build/screen-probe.elf: $(SCREEN_SRC) $(SCREEN_HDR) platform/screen-probe.ld
	mkdir -p build
	$(ZIG) cc $(CFLAGS) $(SCREEN_CFLAGS) -Isrc -Wl,-T,platform/screen-probe.ld -Wl,--build-id=none $(SCREEN_SRC) -o $@

build/screen-probe-rebased.elf: $(SCREEN_SRC) $(SCREEN_HDR) platform/screen-probe.ld
	mkdir -p build
	sed 's/^    \. = 0;$$/    . = 0x40000000;/' platform/screen-probe.ld > build/screen-probe-rebased.ld
	$(ZIG) cc $(CFLAGS) $(SCREEN_CFLAGS) -Isrc -Wl,-T,build/screen-probe-rebased.ld -Wl,--build-id=none $(SCREEN_SRC) -o $@

build/screen-probe.bin: build/screen-probe.elf build/screen-probe-rebased.elf tools/elf_to_binary.py
	$(PYTHON) tools/elf_to_binary.py --base 0 build/screen-probe.elf $@
	$(PYTHON) tools/elf_to_binary.py --base 0x40000000 build/screen-probe-rebased.elf build/screen-probe-rebased.bin
	cmp $@ build/screen-probe-rebased.bin || { rm -f $@; echo "screen probe is not position-independent"; exit 1; }

# Portable modules also built for the host, so tests exercise the same C code.
HOST_LIB = build/host/libportable.so
HOST_SRC = src/linux_boot.c src/bootargs.c src/framebuffer.c
host: $(HOST_LIB)

$(HOST_LIB): $(HOST_SRC) src/linux_boot.h src/bootargs.h src/framebuffer.h src/font.h
	mkdir -p build/host
	$(ZIG) cc -shared -fPIC -O2 -Wall -Wextra -Werror -Isrc -o $@ $(HOST_SRC)

# Regenerate the bitmap font header after editing tools/font8x16.txt.
font:
	$(PYTHON) tools/generate_font.py

# The emulator tests model the qemu-virt platform only.
test: all host
	$(PYTHON) tools/generate_font.py --check
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) tests/emulate.py
	$(PYTHON) tests/emulate_probe.py
	$(PYTHON) tests/emulate_screen_probe.py

run: all
	qemu-system-aarch64 -machine virt -cpu cortex-a57 -smp 1 -m 128M -nographic -monitor none -device loader,file=build/monitor.elf,cpu-num=0

console: all
	$(PYTHON) tools/console_ui.py

clean:
	rm -rf build
