# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the hardware-run kit builder."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.make_hw_kit import LINK_ADDRESS, kmutil_command, make_kit


class HwKitTests(unittest.TestCase):
    def test_kit_contents_match_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp, "p.bin")
            payload.write_bytes(b"\x01\x02\x03" * 100)
            out = Path(tmp, "kit")
            digest = make_kit(payload, out)
            self.assertEqual(digest, hashlib.sha256(payload.read_bytes()).hexdigest())
            self.assertEqual((out / "screen-probe.bin").read_bytes(), payload.read_bytes())
            self.assertEqual((out / "SHA256SUMS").read_text(), f"{digest}  screen-probe.bin\n")
            info = (out / "BUILD-INFO.txt").read_text()
            self.assertIn(f"sha256: {digest}", info)
            self.assertIn(kmutil_command(), info)
            self.assertIn(digest, (out / "REPORT-TEMPLATE.md").read_text())
            env = (out / "probeos.env").read_text()
            self.assertIn(f"PROBE_SHA256={digest}\n", env)
            self.assertIn("PROBE_VA=0xfffffe0007004000\n", env)
            self.assertTrue((out / "recovery.sh").exists())
            # Rebuilding replaces the kit instead of mixing old files in.
            (out / "stale.txt").write_text("x")
            make_kit(payload, out)
            self.assertFalse((out / "stale.txt").exists())

    def test_kmutil_command_uses_equal_entry_and_base(self):
        cmd = kmutil_command("ProbeOS")
        self.assertIn("--raw", cmd)
        self.assertEqual(cmd.count(f"{LINK_ADDRESS:#x}"), 2)
        self.assertIn('-v "/Volumes/ProbeOS"', cmd)
        self.assertEqual(LINK_ADDRESS, 0xFFFFFE0007004000)


if __name__ == "__main__":
    unittest.main()
