# SPDX-License-Identifier: GPL-2.0-or-later
"""Repository conventions that keep the project open and easy to extend."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG = "SPDX-License-Identifier: GPL-2.0-or-later"
SOURCE_GLOBS = ("src/*.[chS]", "platform/**/*.c", "platform/**/*.ld",
                "tools/*.py", "tools/*.c", "tools/*.txt", "tests/*.py", "Makefile")


def source_files():
    for pattern in SOURCE_GLOBS:
        yield from sorted(ROOT.glob(pattern))


class RepositoryTests(unittest.TestCase):
    def test_every_source_file_declares_its_license(self):
        files = list(source_files())
        self.assertGreater(len(files), 20)
        for path in files:
            with self.subTest(path=path.relative_to(ROOT)):
                head = path.read_text(encoding="utf-8").splitlines()[:3]
                self.assertTrue(any(TAG in line for line in head),
                                f"add '{TAG}' to the first lines")

    def test_license_is_gpl_2(self):
        text = (ROOT / "LICENSE").read_text(encoding="ascii")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 2, June 1991", text)

    def test_each_platform_is_complete(self):
        platforms = [d for d in (ROOT / "platform").iterdir() if d.is_dir()]
        self.assertIn("qemu-virt", [d.name for d in platforms])
        for d in platforms:
            with self.subTest(platform=d.name):
                self.assertTrue((d / "platform.c").is_file())
                self.assertTrue((d / "link.ld").is_file())
                self.assertIn("__image_start", (d / "link.ld").read_text())


if __name__ == "__main__":
    unittest.main()
