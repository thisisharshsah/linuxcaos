# SPDX-License-Identifier: GPL-2.0-or-later
"""Assemble build/hw-kit: everything the owner needs for a screen-probe run.

The kit holds the exact payload, its SHA-256, build provenance, the kmutil
command with the chosen addresses, and a report template to fill in after the
run. It reads only project files and runs only read-only git and tool queries.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# XNU's arm64 kernel link address (makedefs/MakeInc.def, ARM64_LINK_ADDR, pinned
# commit in docs/APPLE_BOOT.md). A hypothesis for raw payloads, not a finding.
LINK_ADDRESS = 0xFFFFFE0007004000
PAYLOAD = "screen-probe.bin"


def _query(cmd):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def kmutil_command(volume_placeholder="<ProbeOS>"):
    path = f'"/Volumes/{volume_placeholder} - Data/Users/Shared/{PAYLOAD}"'
    return (f"kmutil configure-boot -c {path} --raw "
            f"--lowest-virtual-address {LINK_ADDRESS:#x} --entry-point {LINK_ADDRESS:#x} "
            f'-v "/Volumes/{volume_placeholder}"')


def make_kit(payload: Path, out: Path) -> str:
    data = payload.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / PAYLOAD).write_bytes(data)
    (out / "SHA256SUMS").write_text(f"{digest}  {PAYLOAD}\n")
    # Settings for tools/probeos-recovery.sh (plain shell assignments, no spaces).
    (out / "probeos.env").write_text(
        f"PROBE_PAYLOAD={PAYLOAD}\nPROBE_SHA256={digest}\nPROBE_VA={LINK_ADDRESS:#x}\n")
    shutil.copy2(ROOT / "tools" / "probeos-recovery.sh", out / "recovery.sh")
    commit = _query(["git", "rev-parse", "HEAD"]) or "unknown"
    dirty = "yes" if _query(["git", "status", "--porcelain", "--untracked-files=no"]) else "no"
    zig = _query([sys.executable, "-m", "ziglang", "version"]) or "unknown"
    (out / "BUILD-INFO.txt").write_text(
        f"payload: {PAYLOAD}\nsize: {len(data)} bytes\nsha256: {digest}\n"
        f"git commit: {commit}\nuncommitted changes: {dirty}\nzig: {zig}\n"
        f"kit date: {date.today().isoformat()}\n"
        f"entry offset: 0 (first byte of the image)\n"
        f"virtual address for kmutil: {LINK_ADDRESS:#x} (XNU ARM64_LINK_ADDR; hypothesis)\n\n"
        f"kmutil command (run in 1TR Terminal; replace <ProbeOS> with the volume name):\n"
        f"  {kmutil_command()}\n")
    (out / "REPORT-TEMPLATE.md").write_text(f"""# Screen probe hardware report

Fill this in after the run and give it back together with the photos.

- Date and time:
- Mac model (About This Mac): MacBookPro17,1
- macOS version of the everyday system:
- macOS version of the probe installation:
- Payload SHA-256 (from SHA256SUMS): {digest}
- Git commit (from BUILD-INFO.txt): {commit}

## Setup
- How the probe installation was created (new APFS volume or new partition):
- `bputil` command used, and any messages:
- `kmutil` command used, exact output (copy or photograph):

## Result
- What appeared on screen (text report, colour bars, black screen, Apple logo, other):
- Colour of the four bars from left to right:
- Photos taken (list files):
- How long before the screen changed:
- Anything else unexpected:

## Return to macOS
- Did the everyday macOS start normally afterwards?
""")
    return digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payload", type=Path, default=ROOT / "build" / PAYLOAD)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "hw-kit")
    args = parser.parse_args(argv)
    if not args.payload.exists():
        print(f"make_hw_kit: {args.payload} missing; run `make screen-probe`", file=sys.stderr)
        return 1
    digest = make_kit(args.payload, args.out)
    print(f"Kit ready in {args.out}\nsha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
