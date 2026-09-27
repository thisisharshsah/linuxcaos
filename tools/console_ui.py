# SPDX-License-Identifier: GPL-2.0-or-later
"""Interactive host-side terminal console for the ARM64 serial monitor.

Runs build/monitor.bin in Unicorn emulator with real-time interactive PL011 UART
I/O connected to host stdin/stdout. Enables developers to test and interact
with the monitor CLI on macOS without requiring QEMU installed.
"""

import argparse
import os
import select
import sys
import termios
import tty
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

ROOT = Path(__file__).resolve().parents[1]
RAM_BASE = 0x40000000
RAM_SIZE = 0x200000
ENTRY_POINT = 0x40080000
UART_BASE = 0x09000000
UART_SIZE = 0x1000

# PL011 register offsets
UART_DR = 0x00
UART_FR = 0x18
UART_FR_TXFF = 1 << 5
UART_FR_RXFE = 1 << 4


class ConsoleRunner:
    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.running = False
        self.rx_buffer = bytearray()

    def run_interactive(self):
        if not self.binary_path.exists():
            print(f"Error: {self.binary_path} not found. Run 'make' first.", file=sys.stderr)
            return 1

        payload = self.binary_path.read_bytes()
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        cpu.mem_map(RAM_BASE, RAM_SIZE)
        cpu.mem_write(RAM_BASE, b"\x00" * RAM_SIZE)
        cpu.mem_write(ENTRY_POINT, payload)
        cpu.mem_map(UART_BASE, UART_SIZE)

        def uart_read(uc, access, address, size, value, data):
            offset = address - UART_BASE
            if offset == UART_FR:
                # If no input available, RXFE bit is set (0x10)
                flag = 0 if self.rx_buffer else UART_FR_RXFE
                uc.mem_write(address, flag.to_bytes(4, "little"))
            elif offset == UART_DR:
                if self.rx_buffer:
                    char = self.rx_buffer.pop(0)
                    uc.mem_write(address, char.to_bytes(4, "little"))
                else:
                    uc.mem_write(address, (0).to_bytes(4, "little"))

        def uart_write(uc, access, address, size, value, data):
            offset = address - UART_BASE
            if offset == UART_DR:
                char_byte = value & 0xFF
                sys.stdout.write(chr(char_byte))
                sys.stdout.flush()

        cpu.hook_add(UC_HOOK_MEM_READ, uart_read, begin=UART_BASE, end=UART_BASE + UART_SIZE - 1)
        cpu.hook_add(UC_HOOK_MEM_WRITE, uart_write, begin=UART_BASE, end=UART_BASE + UART_SIZE - 1)

        print("=== ARM64 Serial Monitor Console (Unicorn) ===")
        print("Type 'help' for commands. Press Ctrl-] to exit.\n")
        sys.stdout.flush()

        is_tty = sys.stdin.isatty()
        old_settings = None
        if is_tty:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())

        self.running = True
        try:
            # Execute in small instruction slices so we can poll stdin
            pc = ENTRY_POINT
            slice_count = 5000
            while self.running:
                # Check for stdin input
                r, _, _ = select.select([sys.stdin], [], [], 0.005)
                if r:
                    chunk = os.read(sys.stdin.fileno(), 128)
                    if not chunk:
                        break
                    for b in chunk:
                        if b == 0x1D:  # Ctrl-]
                            self.running = False
                            break
                        self.rx_buffer.append(b)
                    if not self.running:
                        break

                try:
                    cpu.emu_start(pc, ENTRY_POINT + 0x100000, count=slice_count)
                    pc = cpu.reg_read(260)  # PC
                except Exception as exc:
                    if is_tty and old_settings:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    print(f"\nEmulator stopped: {exc}", file=sys.stderr)
                    break
        finally:
            if is_tty and old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            print("\n=== Console session ended ===")

        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Interactive console runner for ARM64 serial monitor")
    parser.add_argument(
        "--binary",
        type=Path,
        default=ROOT / "build/monitor.bin",
        help="Path to monitor raw binary (default: build/monitor.bin)",
    )
    args = parser.parse_args(argv)
    runner = ConsoleRunner(args.binary)
    return runner.run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
