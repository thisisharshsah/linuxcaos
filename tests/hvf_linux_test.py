# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot a real Linux kernel through the monitor's `boot` command on real Apple cores.

The VM (tools/hvf_run.c with an in-kernel GICv3) stages a Debian arm64 kernel,
our VM device tree, and our initramfs in RAM. The monitor's loader validates,
places, and enters the kernel; our init reports and powers off via PSCI.
This is EL1 in a Hypervisor.framework VM with a generic 4K-page kernel: it
tests our loader against real Linux on real cores, not an M1 boot.
"""
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.vm import prepare_linux_test as vm  # noqa: E402

RUNNER = ROOT / "build/host/hvf_run"
IN = vm.OUT


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        print("SKIP: needs macOS on Apple Silicon")
        return
    needed = [RUNNER, ROOT / "build/monitor.bin", IN / "linux", IN / "vm.dtb", IN / "initramfs.cpio"]
    if not all(p.exists() for p in needed):
        print("SKIP: run `make linux-vm-test` to fetch and build the inputs")
        return
    image, initrd = (IN / "linux").stat().st_size, (IN / "initramfs.cpio").stat().st_size
    command = f"boot {vm.STAGE_IMAGE:x} {image:x} {vm.STAGE_DTB:x} {vm.STAGE_INITRD:x} {initrd:x}\n"
    r = subprocess.run([str(RUNNER), "--fill", "0", "--map", f"{vm.RAM_BASE:#x}:{vm.RAM_SIZE:#x}",
                        "--load", f"{ROOT / 'build/monitor.bin'}@0x40080000",
                        "--load", f"{IN / 'linux'}@{vm.STAGE_IMAGE:#x}",
                        "--load", f"{IN / 'vm.dtb'}@{vm.STAGE_DTB:#x}",
                        "--load", f"{IN / 'initramfs.cpio'}@{vm.STAGE_INITRD:#x}",
                        "--gic", f"{vm.GIC_DIST:#x}:{vm.GIC_REDIST:#x}", "--uart", "0x09000000",
                        "--entry", "0x40080000", "--timeout", "120", "--input", command],
                       capture_output=True, text=True, timeout=300)
    log = r.stdout.replace("\r\n", "\n")
    (IN / "boot.log").write_text(log + r.stderr)
    assert r.returncode == 0 and "[stop: poweroff]" in r.stderr, (r.returncode, r.stderr, log[-3000:])
    for expected in (
        # Our loader: planner layout above the monitor, then the handoff.
        "kernel 0x0000000040200000  dtb 0x0000000042800000  initrd 0x0000000042a00000",
        "Entering Linux.",
        # The kernel: running on an Apple core, using our device tree and command line.
        "Booting Linux on physical CPU 0x0000000000 [0x610",
        "Machine model: Hypervisor.framework test VM",
        f"Kernel command line: {vm.BOOTARGS}",
        # Our init, found through the initrd range fdt.c wrote into /chosen.
        "PROJECT-INIT: userspace is running (pid 1)",
        "PROJECT-INIT: CPU implementer\t: 0x61",
        "PROJECT-INIT: powering off",
        "reboot: Power down",
    ):
        assert expected in log, (expected, log[-3000:])
    print("PASS (real Apple cores, Hypervisor.framework, EL1): monitor `boot` loaded a real Linux "
          "kernel, which ran our initramfs userspace and powered off")


if __name__ == "__main__":
    main()
