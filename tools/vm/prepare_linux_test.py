# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare inputs for booting real Linux through the monitor in the test VM.

Downloads Debian's arm64 installer kernel (a generic 4K-page Linux Image; a
test input, not part of this project) and checks it against the SHA-256 that
Debian publishes, builds our tiny init with the pinned Zig, packs the
initramfs, and writes the VM device tree. Outputs go to build/linux-test/.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "linux-test"
sys.path.insert(0, str(ROOT))
from tools.vm.make_initramfs import build as build_initramfs  # noqa: E402
from tools.vm.make_vm_dtb import vm_tree  # noqa: E402
from tools.fdt import build_dtb  # noqa: E402

# Debian 13 installer netboot kernel, from dists/trixie/main/installer-arm64/current/images/SHA256SUMS
KERNEL_URL = ("https://deb.debian.org/debian/dists/trixie/main/installer-arm64/current/images/"
              "netboot/debian-installer/arm64/linux")
KERNEL_SHA256 = "9c37ace54ef7e1919411fd912e9f34d6982ddd7f4c8ef3c8aee56f4c4d70db67"

# VM layout, shared with tests/hvf_linux_test.py.
RAM_BASE, RAM_SIZE = 0x40000000, 0x20000000
GIC_DIST, GIC_DIST_SIZE = 0x08000000, 0x10000
GIC_REDIST, GIC_REDIST_SIZE = 0x0A000000, 0x20000  # one vCPU's redistributor
STAGE_IMAGE, STAGE_DTB, STAGE_INITRD = 0x50000000, 0x4F000000, 0x4E000000
BOOTARGS = "earlycon=pl011,mmio32,0x9000000 keep_bootcon rdinit=/init panic=-1 loglevel=6"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    kernel = OUT / "linux"
    if not kernel.exists() or hashlib.sha256(kernel.read_bytes()).hexdigest() != KERNEL_SHA256:
        data = subprocess.run(["curl", "-fsSL", KERNEL_URL], capture_output=True, check=True,
                              timeout=900).stdout
        digest = hashlib.sha256(data).hexdigest()
        if digest != KERNEL_SHA256:
            raise SystemExit(f"kernel checksum mismatch: expected {KERNEL_SHA256}, got {digest}"
                             " (Debian may have published a newer kernel; update the pin)")
        kernel.write_bytes(data)
    subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "aarch64-linux-musl", "-static",
                    "-Os", "-Wall", "-Wextra", "-Werror", str(ROOT / "tools/vm/init.c"),
                    "-o", str(OUT / "init")], check=True)
    (OUT / "initramfs.cpio").write_bytes(build_initramfs((OUT / "init").read_bytes()))
    (OUT / "vm.dtb").write_bytes(build_dtb(vm_tree(RAM_BASE, RAM_SIZE, GIC_DIST, GIC_DIST_SIZE,
                                                   GIC_REDIST, GIC_REDIST_SIZE, BOOTARGS)))
    print(f"Linux VM test inputs ready in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
