# SPDX-License-Identifier: GPL-2.0-or-later
PYTHON ?= .venv/bin/python
ZIG = $(PYTHON) -m ziglang
CFLAGS = -target aarch64-freestanding-none -mcpu=cortex_a57 -ffreestanding -fno-stack-protector -fno-pic -mgeneral-regs-only -Wall -Wextra -Werror -O2 -nostdlib

# Board support for the monitor: platform/<name>/{platform.c,link.ld}.
PLATFORM ?= qemu-virt
PLATFORM_DIR = platform/$(PLATFORM)
ifeq ($(wildcard $(PLATFORM_DIR)/platform.c),)
$(error Unknown PLATFORM '$(PLATFORM)'; available: $(notdir $(patsubst %/,%,$(dir $(wildcard platform/*/platform.c)))))
endif

.PHONY: all probe font test run console clean
all: build/monitor.bin build/entry-probe.bin

probe: build/entry-probe.bin

MONITOR_SRC = src/start.S src/vectors.S src/monitor.c src/exception.c src/framebuffer.c $(PLATFORM_DIR)/platform.c
MONITOR_HDR = src/exception.h src/framebuffer.h src/font.h src/monitor.h src/platform.h

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

# Regenerate the bitmap font header after editing tools/font8x16.txt.
font:
	$(PYTHON) tools/generate_font.py

# The emulator tests model the qemu-virt platform only.
test: all
	$(PYTHON) tools/generate_font.py --check
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) tests/emulate.py
	$(PYTHON) tests/emulate_probe.py

run: all
	qemu-system-aarch64 -machine virt -cpu cortex-a57 -smp 1 -m 128M -nographic -monitor none -device loader,file=build/monitor.elf,cpu-num=0

console: all
	$(PYTHON) tools/console_ui.py

clean:
	rm -rf build
