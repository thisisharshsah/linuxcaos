# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the bitmap-font generator and the committed font header."""

import unittest
from pathlib import Path

from tools.generate_font import FIRST_CHAR, HEIGHT, LAST_CHAR, parse_font, render_header


ROOT = Path(__file__).resolve().parents[1]


def source(glyphs):
    """Build font source text; `glyphs` maps code -> list of 16 row strings."""
    parts = []
    for code, rows in glyphs.items():
        parts.append(f"glyph {code}  # comment")
        parts.extend(rows)
    return "\n".join(parts) + "\n"


def full_font(overrides=None):
    glyphs = {c: ["........"] * HEIGHT for c in range(FIRST_CHAR, LAST_CHAR + 1)}
    glyphs.update(overrides or {})
    return glyphs


class GenerateFontTests(unittest.TestCase):
    def test_committed_header_matches_source(self):
        text = (ROOT / "tools/font8x16.txt").read_text(encoding="ascii")
        self.assertEqual(render_header(parse_font(text)),
                         (ROOT / "src/font.h").read_text(encoding="ascii"))

    def test_bit_order_and_leading_hash_rows(self):
        rows = ["#......."] + ["........"] * 14 + ["......##"]
        glyphs = parse_font(source(full_font({65: rows})))
        self.assertEqual(glyphs[65][0], 0x80)
        self.assertEqual(glyphs[65][15], 0x03)

    def test_header_labels_escape_comment_hazards(self):
        header = render_header(parse_font(source(full_font())))
        self.assertIn("/*  34 'quote' */", header)
        self.assertIn("/*  92 'backslash' */", header)

    def test_rejects_malformed_sources(self):
        good = full_font()
        cases = {
            "missing glyph": {c: r for c, r in good.items() if c != 90},
            "short glyph": {**good, 90: ["........"] * (HEIGHT - 1)},
            "long glyph": {**good, 90: ["........"] * (HEIGHT + 1)},
            "bad pixel": {**good, 90: ["....x..."] + ["........"] * (HEIGHT - 1)},
            "narrow row": {**good, 90: ["......."] + ["........"] * (HEIGHT - 1)},
            "out of range": {**good, 127: ["........"] * HEIGHT},
        }
        for name, glyphs in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_font(source(glyphs))
        with self.assertRaises(ValueError):
            parse_font("glyph 32\n" + "........\n" * HEIGHT + "glyph 32\n")


if __name__ == "__main__":
    unittest.main()
