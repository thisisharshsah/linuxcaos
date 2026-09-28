# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/probeos.sh and tools/probeos-recovery.sh.

Every system command they use (diskutil, bputil, kmutil, sudo, softwareupdate)
is replaced by a fake on PATH that only records its arguments, so these tests
never touch real disks or boot policies. Paths are redirected into temp dirs.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "tools" / "probeos.sh"
RECOVERY = ROOT / "tools" / "probeos-recovery.sh"
BOOT, PROBE = "BOOT-5FEC-UUID", "PROBE-7A1B-UUID"

FAKE_DISKUTIL = r"""#!/bin/sh
echo "diskutil $*" >> "$STUB_LOG"
case "$1 $2" in
  "info /")
    printf '   Volume Name:               Macintosh HD\n   APFS Container:            disk3\n   APFS Volume Group:         %s\n' "$BOOT_GROUP" ;;
  "info "*)
    [ -f "$STATE/probe_exists" ] || exit 1
    printf '   Volume Name:               %s\n   APFS Container:            disk3\n   APFS Volume Group:         %s\n' "${FAKE_NAME:-ProbeOS}" "$PROBE_GROUP" ;;
  "apfs addVolume") touch "$STATE/probe_exists" ;;
  "apfs deleteVolumeGroup") rm -f "$STATE/probe_exists" ;;
  "apfs listVolumeGroups")
    echo "+-> Volume Group $BOOT_GROUP"
    [ -f "$STATE/probe_exists" ] && echo "+-> Volume Group $PROBE_GROUP" ;;
esac
exit 0
"""
FAKE_RECORDER = r"""#!/bin/sh
echo "$(basename "$0") $*" >> "$STUB_LOG"
name=$(basename "$0")
if [ "$name" = kmutil ] && [ -f "$STATE/kmutil_fail_once" ]; then
  rm -f "$STATE/kmutil_fail_once"; echo "kmutil: simulated failure"; exit 1
fi
exit 0
"""
FAKE_SUDO = r"""#!/bin/sh
echo "sudo $*" >> "$STUB_LOG"
exec "$@"
"""


class Sandbox:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin, self.state = self.tmp / "bin", self.tmp / "state"
        self.volumes, self.preboot, self.recovery = (self.tmp / d for d in ("Volumes", "Preboot", "Recovery"))
        self.apps, self.kit = self.tmp / "Applications", self.tmp / "kit"
        self.log = self.tmp / "log.txt"
        for d in (self.bin, self.state, self.volumes, self.preboot, self.recovery, self.apps, self.kit):
            d.mkdir()
        for name, body in (("diskutil", FAKE_DISKUTIL), ("bputil", FAKE_RECORDER),
                           ("kmutil", FAKE_RECORDER), ("softwareupdate", FAKE_RECORDER),
                           ("sudo", FAKE_SUDO)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.log.write_text("")

    def env(self, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STUB_LOG=str(self.log),
                   STATE=str(self.state), BOOT_GROUP=BOOT, PROBE_GROUP=PROBE,
                   PROBEOS_VOLUMES_ROOT=str(self.volumes), PROBEOS_PREBOOT_ROOT=str(self.preboot),
                   PROBEOS_RECOVERY_ROOT=str(self.recovery), PROBEOS_APPS_ROOT=str(self.apps),
                   PROBEOS_KIT=str(self.kit), PROBEOS_RECORD=str(self.tmp / "removal.txt"))
        env.update(extra)
        return env

    def calls(self):
        return self.log.read_text().splitlines()

    def probe_exists(self, yes=True):
        (self.state / "probe_exists").touch() if yes else None
        (self.volumes / "ProbeOS").mkdir(exist_ok=True)

    def cleanup(self):
        shutil.rmtree(self.tmp)


def run(cmd, env, answers=""):
    return subprocess.run(cmd, input=answers, capture_output=True, text=True, env=env, timeout=60)


class SetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_syntax_and_help(self):
        self.assertEqual(subprocess.run(["bash", "-n", SETUP]).returncode, 0)
        r = run(["bash", SETUP, "help"], self.sb.env())
        for word in ("create-volume", "install-macos", "copy-kit", "remove", "verify-removed",
                     "Loading startup options", "Utilities > Terminal"):
            self.assertIn(word, r.stdout)

    def test_create_volume_dry_run_executes_nothing(self):
        r = run(["bash", SETUP, "--dry-run", "create-volume"], self.sb.env())
        self.assertIn("diskutil apfs addVolume disk3 APFS ProbeOS", r.stdout)
        self.assertNotIn("diskutil apfs addVolume disk3 APFS ProbeOS", self.sb.calls())

    def test_create_volume_needs_yes(self):
        run(["bash", SETUP, "create-volume"], self.sb.env(), "no\n")
        self.assertNotIn("diskutil apfs addVolume disk3 APFS ProbeOS", self.sb.calls())
        run(["bash", SETUP, "create-volume"], self.sb.env(), "yes\n")
        self.assertIn("diskutil apfs addVolume disk3 APFS ProbeOS", self.sb.calls())

    def test_complete_removal_and_verification(self):
        self.sb.probe_exists()
        for base in (self.sb.preboot, self.sb.recovery):
            (base / PROBE).mkdir()
            (base / BOOT).mkdir()
        (self.sb.apps / "Install macOS Test.app").mkdir()
        (self.sb.kit / "screen-probe.bin").write_bytes(b"x")
        r = run(["bash", SETUP, "remove"], self.sb.env(), "yes\n" * 10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"diskutil apfs deleteVolumeGroup {PROBE}", self.sb.calls())
        # Leftovers of ProbeOS are gone; the running system's folders are untouched.
        self.assertFalse((self.sb.preboot / PROBE).exists())
        self.assertFalse((self.sb.recovery / PROBE).exists())
        self.assertTrue((self.sb.preboot / BOOT).exists())
        self.assertTrue((self.sb.recovery / BOOT).exists())
        self.assertFalse((self.sb.apps / "Install macOS Test.app").exists())
        self.assertFalse(self.sb.kit.exists())
        record = (self.sb.tmp / "removal.txt").read_text()
        self.assertIn(f"bputil -r {PROBE}", record)
        self.assertIn(f"bputil -r {PROBE}", r.stdout)
        v = run(["bash", SETUP, "verify-removed"], self.sb.env())
        self.assertEqual(v.returncode, 0, v.stdout)
        self.assertIn("Clean on the macOS side.", v.stdout)

    def test_verify_removed_reports_leftovers(self):
        self.sb.probe_exists()
        v = run(["bash", SETUP, "verify-removed"], self.sb.env())
        self.assertNotEqual(v.returncode, 0)
        self.assertIn("NOT CLEAN: volume ProbeOS still exists", v.stdout)

    def test_refuses_to_touch_the_running_system(self):
        self.sb.probe_exists()
        r = run(["bash", SETUP, "remove"], self.sb.env(PROBE_GROUP=BOOT), "yes\n" * 10)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing", r.stderr)
        self.assertFalse(any("deleteVolumeGroup" in c for c in self.sb.calls()))
        r = run(["bash", SETUP, "install-macos"], self.sb.env(PROBE_GROUP=BOOT), "yes\n")
        self.assertIn("refusing", r.stderr)

    def test_removal_stops_if_deletion_declined(self):
        self.sb.probe_exists()
        (self.sb.preboot / PROBE).mkdir()
        r = run(["bash", SETUP, "remove"], self.sb.env(), "no\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.sb.preboot / PROBE).exists())


class RecoveryScriptTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.payload = b"\x5f\x20\x03\xd5" * 16
        digest = hashlib.sha256(self.payload).hexdigest()
        (self.sb.kit / "screen-probe.bin").write_bytes(self.payload)
        (self.sb.kit / "probeos.env").write_text(
            f"PROBE_PAYLOAD=screen-probe.bin\nPROBE_SHA256={digest}\nPROBE_VA=0xfffffe0007004000\n")
        shutil.copy(RECOVERY, self.sb.kit / "recovery.sh")
        self.script = self.sb.kit / "recovery.sh"
        self.sb.probe_exists()
        self.kmutil = (f"kmutil configure-boot -c {self.sb.kit}/screen-probe.bin --raw "
                       f"--lowest-virtual-address 0xfffffe0007004000 --entry-point 0xfffffe0007004000 "
                       f"-v {self.sb.volumes}/ProbeOS")

    def test_syntax(self):
        self.assertEqual(subprocess.run(["sh", "-n", RECOVERY]).returncode, 0)

    def test_install_sets_policy_then_installs_probe(self):
        r = run(["sh", self.script], self.sb.env(), "yes\nyes\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = [c for c in self.sb.calls() if c.startswith(("bputil", "kmutil"))]
        self.assertEqual(calls, [f"bputil -n -v {PROBE}", self.kmutil])
        self.assertIn("Checksum OK", r.stdout)
        self.assertIn("select ProbeOS".lower(), r.stdout.lower())
        self.assertTrue((self.sb.kit / "recovery.log").exists())

    def test_checksum_mismatch_changes_nothing(self):
        (self.sb.kit / "screen-probe.bin").write_bytes(self.payload + b"!")
        r = run(["sh", self.script], self.sb.env(), "yes\nyes\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stdout + r.stderr)
        self.assertFalse(any(c.startswith(("bputil", "kmutil")) for c in self.sb.calls()))

    def test_refuses_wrong_volume_name(self):
        r = run(["sh", self.script], self.sb.env(FAKE_NAME="Macintosh HD"), "yes\nyes\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any(c.startswith(("bputil", "kmutil")) for c in self.sb.calls()))

    def test_declining_policy_change_stops_before_kmutil(self):
        r = run(["sh", self.script], self.sb.env(), "no\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any(c.startswith("kmutil") for c in self.sb.calls()))

    def test_kmutil_failure_offers_asahi_fallback(self):
        (self.sb.state / "kmutil_fail_once").touch()
        r = run(["sh", self.script], self.sb.env(), "yes\n" * 4)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = [c for c in self.sb.calls() if c.startswith(("bputil", "kmutil"))]
        self.assertEqual(calls, [f"bputil -n -v {PROBE}", self.kmutil,
                                 f"bputil -nkcas -v {PROBE}", self.kmutil])

    def test_undo_restores_full_security(self):
        r = run(["sh", self.script, "undo"], self.sb.env(), "yes\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"bputil -f -v {PROBE}", self.sb.calls())

    def test_remove_policy_only_after_deletion(self):
        r = run(["sh", self.script, "remove-policy", PROBE], self.sb.env(), "yes\n")
        self.assertNotEqual(r.returncode, 0)
        (self.sb.volumes / "ProbeOS").rmdir()
        r = run(["sh", self.script, "remove-policy", PROBE], self.sb.env(), "yes\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"bputil -r {PROBE}", self.sb.calls())


if __name__ == "__main__":
    unittest.main()
