# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent Python model of the framebuffer text console, shared by tests.

It restates the console's behaviour (cursor, wrap, backspace, scroll) and the
pixel formats from their definitions rather than calling the C code.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.generate_font import parse_font  # noqa: E402

GLYPHS = parse_font((ROOT / "tools/font8x16.txt").read_text(encoding="ascii"))


def encode(rgb, pixel):
    """Pixel word for 0x00RRGGBB in a Linux simple-framebuffer format."""
    if pixel == "x8r8g8b8":
        return rgb
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    ten = lambda c: round(c * 1023 / 255)  # full-scale mapping: 0xff -> 0x3ff
    return (ten(r) << 20) | (ten(g) << 10) | ten(b)


def model_cells(stream, cols, rows):
    """Reference console: the character grid the byte stream should leave."""
    # The monitor's `clear` sends this sequence to serial only and erases the framebuffer.
    stream = stream.rsplit(b"\x1b[2J\x1b[H", 1)[-1]
    grid = [[" "] * cols for _ in range(rows)]
    col = row = 0

    def newline():
        nonlocal col, row
        col = 0
        if row + 1 < rows:
            row += 1
        else:
            grid.pop(0)
            grid.append([" "] * cols)

    for ch in stream.decode("ascii"):
        if ch == "\n":
            newline()
        elif ch == "\r":
            col = 0
        elif ch == "\b":
            col = max(col - 1, 0)
        elif " " <= ch <= "~":
            if col == cols:
                newline()
            grid[row][col] = ch
            col += 1
    return ["".join(r) for r in grid]


def render_cells(cells, width, height, scale, fg, bg):
    """Pixel words per row for a cleared console showing `cells`."""
    out = []
    for y in range(height):
        text_row, gy = divmod(y // scale, 16)
        if text_row >= len(cells):
            out.append([bg] * width)  # cleared, never drawn or scrolled
            continue
        row = []
        for x in range(width):
            cell, gx = divmod(x // scale, 8)
            if cell >= len(cells[text_row]):
                row.append(bg)
            else:
                bits = GLYPHS[ord(cells[text_row][cell])][gy]
                row.append(fg if bits & (0x80 >> gx) else bg)
        out.append(row)
    return out
