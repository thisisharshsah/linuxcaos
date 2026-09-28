# SPDX-License-Identifier: GPL-2.0-or-later
"""Device tree for the Hypervisor.framework test VM that boots Linux.

Describes what tools/hvf_run.c provides: one CPU, RAM, a GICv3 created with
hv_gic_create, the ARM generic timer, PSCI over HVC, and the PL011 serial port
used as the kernel's early console. This is a test VM, not an Apple machine.
Binding references: Linux Documentation/devicetree/bindings (arm,gic-v3,
arm,armv8-timer, arm,psci).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.fdt import Node, build_dtb, string, u32  # noqa: E402

GIC_PPI, IRQ_LEVEL_HIGH = 1, 4
GIC_PHANDLE = 1
UART = 0x09000000


def cells64(*values):
    return u32(*[w for v in values for w in (v >> 32, v & 0xFFFFFFFF)])


def vm_tree(ram_base, ram_size, gic_dist, dist_size, gic_redist, redist_size, bootargs):
    # Arch timer PPIs: secure phys 13, non-secure phys 14, virtual 11, hyp 10.
    timer_irqs = [c for ppi in (13, 14, 11, 10) for c in (GIC_PPI, ppi, IRQ_LEVEL_HIGH)]
    return Node("", {"#address-cells": u32(2), "#size-cells": u32(2),
                     "compatible": string("linux-on-apple-silicon,hvf-test-vm"),
                     "model": string("Hypervisor.framework test VM"),
                     "interrupt-parent": u32(GIC_PHANDLE)}, [
        Node("chosen", {"bootargs": string(bootargs)}),
        Node("cpus", {"#address-cells": u32(1), "#size-cells": u32(0)}, [
            Node("cpu@0", {"device_type": string("cpu"), "compatible": string("arm,armv8"),
                           "reg": u32(0)})]),
        Node(f"memory@{ram_base:x}", {"device_type": string("memory"),
                                      "reg": cells64(ram_base, ram_size)}),
        Node(f"interrupt-controller@{gic_dist:x}", {
            "compatible": string("arm,gic-v3"), "#interrupt-cells": u32(3),
            "interrupt-controller": b"", "phandle": u32(GIC_PHANDLE),
            "reg": cells64(gic_dist, dist_size, gic_redist, redist_size)}),
        Node("timer", {"compatible": string("arm,armv8-timer"), "interrupts": u32(*timer_irqs),
                       "always-on": b""}),
        Node("psci", {"compatible": string("arm,psci-1.0") + string("arm,psci-0.2"),
                      "method": string("hvc")}),
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    num = lambda s: int(s, 0)
    parser.add_argument("--ram", type=num, nargs=2, metavar=("BASE", "SIZE"), required=True)
    parser.add_argument("--gic", type=num, nargs=4, metavar=("DIST", "DSIZE", "REDIST", "RSIZE"), required=True)
    parser.add_argument("--bootargs", default=f"earlycon=pl011,mmio32,{UART:#x} keep_bootcon "
                                              "rdinit=/init panic=-1 loglevel=6")
    args = parser.parse_args(argv)
    args.output.write_bytes(build_dtb(vm_tree(*args.ram, *args.gic, args.bootargs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
