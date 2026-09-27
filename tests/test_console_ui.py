# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for host-side interactive console UI tool."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.console_ui import ConsoleRunner, main


class ConsoleRunnerTests(unittest.TestCase):
    def test_missing_binary_returns_error(self):
        runner = ConsoleRunner(ROOT / "build/nonexistent-binary.bin")
        f = io.StringIO()
        with contextlib.redirect_stderr(f):
            result = runner.run_interactive()
        self.assertEqual(result, 1)

    def test_cli_parser_help(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f), self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_run_interactive_with_exit_key(self):
        # Test that ConsoleRunner handles Ctrl-] (0x1D) exit key cleanly
        runner = ConsoleRunner(ROOT / "build/monitor.bin")
        r_fd, w_fd = os.pipe()
        os.write(w_fd, b"\x1d")  # Send Ctrl-] immediately
        os.close(w_fd)
        
        orig_stdin = sys.stdin
        f_out = io.StringIO()
        fake_in = io.TextIOWrapper(os.fdopen(r_fd, "rb"))
        try:
            sys.stdin = fake_in
            with contextlib.redirect_stdout(f_out):
                res = runner.run_interactive()
            self.assertEqual(res, 0)
            self.assertIn("ARM64 Serial Monitor Console", f_out.getvalue())
        finally:
            sys.stdin = orig_stdin
            fake_in.close()


if __name__ == "__main__":
    unittest.main()
