# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic tests only: no record here came from a physical Apple target."""

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.inspect_probe import decode_record


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "inspect_probe.py"


def synthetic_record(**overrides):
    values = {
        "magic": b"M1PROBE\x00", "version": 1, "size": 96, "status": 1,
        "x0": 0xFEDCBA9876543210, "x1": 1, "x2": 2, "x3": 3,
        "incoming_sp": 0x123456789ABCDEF0, "entry_pc": 0x800000000,
        "current_el": 8, "daif": 0x3C0, "reserved": 0,
    }
    values.update(overrides)
    return struct.pack("<8sII10Q", *values.values())


class DecodeRecordTests(unittest.TestCase):
    def test_captured_registers_and_evidence_warning(self):
        result = decode_record(synthetic_record())
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["size"], 96)
        self.assertEqual(result["status"], "captured")
        self.assertEqual(result["x0"], "0xfedcba9876543210")
        self.assertEqual([result[f"x{i}"] for i in range(1, 4)], ["0x1", "0x2", "0x3"])
        self.assertEqual(result["incoming_sp"], "0x123456789abcdef0")
        self.assertEqual(result["entry_pc"], "0x800000000")
        self.assertEqual(result["current_el"], "0x8")
        self.assertEqual(result["exception_level"], 2)
        self.assertEqual(result["daif"], "0x3c0")
        self.assertIn("Untrusted evidence", result["evidence_note"])
        self.assertIn("not proof of Apple execution", result["evidence_note"])
        json.dumps(result)

    def test_pending_is_not_a_completed_capture(self):
        data = b"M1PROBE\x00" + struct.pack("<II", 1, 96) + bytes(80)
        result = decode_record(data)
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["exception_level"])
        self.assertEqual(result["x0"], "0x0")

    def test_pending_can_have_partially_written_registers(self):
        result = decode_record(synthetic_record(status=0, current_el=0xFFFFFFFF, daif=1))
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["exception_level"])

    def test_all_supported_exception_levels(self):
        for raw, decoded in ((4, 1), (8, 2), (12, 3)):
            with self.subTest(raw=raw):
                self.assertEqual(decode_record(synthetic_record(current_el=raw))["exception_level"], decoded)

    def test_all_daif_flag_combinations(self):
        for flags in range(16):
            with self.subTest(flags=flags):
                self.assertEqual(decode_record(synthetic_record(daif=flags << 6))["daif"], hex(flags << 6))

    def test_rejects_truncated_and_oversized_records(self):
        valid = synthetic_record()
        for data in (b"", valid[:8], valid[:16], valid[:-1], valid + b"\x00"):
            with self.subTest(length=len(data)), self.assertRaisesRegex(ValueError, "exactly 96"):
                decode_record(data)

    def test_rejects_invalid_header_status_and_reserved(self):
        for changes, message in (
            ({"magic": b"M1PROBE!"}, "magic"),
            ({"version": 0}, "version"),
            ({"version": 2}, "version"),
            ({"size": 95}, "size"),
            ({"size": 97}, "size"),
            ({"status": 2}, "status"),
            ({"status": 0xFFFFFFFFFFFFFFFF}, "status"),
            ({"reserved": 1}, "reserved"),
            ({"status": 0, "reserved": 1}, "reserved"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                decode_record(synthetic_record(**changes))

    def test_rejects_invalid_captured_exception_levels(self):
        for current_el in (0, 1, 2, 3, 5, 7, 16, 0xFFFFFFFFFFFFFFFF):
            with self.subTest(current_el=current_el), self.assertRaisesRegex(ValueError, "CurrentEL"):
                decode_record(synthetic_record(current_el=current_el))

    def test_rejects_every_non_daif_bit(self):
        for bit in set(range(64)) - set(range(6, 10)):
            with self.subTest(bit=bit), self.assertRaisesRegex(ValueError, "DAIF"):
                decode_record(synthetic_record(daif=1 << bit))


class InspectCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "synthetic.bin"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), str(self.path), *args],
            capture_output=True, text=True, check=False,
        )

    def test_default_offset(self):
        self.path.write_bytes(synthetic_record())
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "captured")

    def test_explicit_offset_inside_blob_and_trailing_bytes(self):
        self.path.write_bytes(b"prefix" + synthetic_record() + b"unrelated trailing bytes")
        for offset in ("6", "0x6"):
            with self.subTest(offset=offset):
                result = self.run_cli("--offset", offset)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["entry_pc"], "0x800000000")

    def test_invalid_offsets(self):
        self.path.write_bytes(synthetic_record())
        for offset in ("-1", "invalid", "1.5"):
            with self.subTest(offset=offset):
                result = self.run_cli("--offset", offset)
                self.assertEqual(result.returncode, 2)
                self.assertIn("offset", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_truncated_slice_and_offset_beyond_file(self):
        self.path.write_bytes(synthetic_record())
        for offset in ("1", "96", "1024"):
            with self.subTest(offset=offset):
                result = self.run_cli("--offset", offset)
                self.assertEqual(result.returncode, 2)
                self.assertIn("exactly 96", result.stderr)

    def test_unrepresentable_offset_reports_error_without_traceback(self):
        self.path.write_bytes(synthetic_record())
        result = self.run_cli("--offset", str(1 << 200))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_file(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_record_reports_error_without_json(self):
        self.path.write_bytes(synthetic_record(status=2))
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown probe record status", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
