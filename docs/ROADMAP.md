# Development milestones

See the [living blueprint](BLUEPRINT.md) for architecture and implementation
status side by side, with dated progress updates.

## 0 — Executable foundation (implemented)

ARM64 startup, linker layout, polling console, bounded command input, and
instruction-level integration tests. QEMU device-level verification remains
pending until QEMU is installed. This is a development harness, not an M1 port.

## 1 — Independent Apple boot research (in progress)

Apple's documented CustomOS policy route and the installed raw-payload interface
are recorded in [APPLE_BOOT.md](APPLE_BOOT.md). A separate original
[entry-state probe](ENTRY_PROBE.md), host decoder, and synthetic validation
harness now exist. These are preparation for physical testing, not completion
of M1. See the [blueprint](BLUEPRINT.md) for current validation evidence.

Record the owner-authorized custom boot process, accepted executable format,
entry registers, exception level, memory ownership, firmware dependencies, and
recovery procedure for MacBookPro17,1. Record observations rather than infer
addresses from emulator behavior. Identify a suitable second debugging machine
and transport. Keep the development host recoverable.

Deliverable: a documented Apple entry ABI plus an independently implemented
payload packaging tool. Exit criterion: an original payload executes on the
target and produces a repeatable, externally observable marker.

## 2 — Hardware diagnostics

Capture boot arguments and the firmware hardware description. Establish a
validated console/framebuffer path, exception vectors, timer, memory map,
and cache/MMU rules. Each finding needs hardware, firmware version, evidence,
and a reproduction procedure in the research log.

Preparation so far: a platform-neutral framebuffer text console, tested only
against emulator memory (see the [blueprint](BLUEPRINT.md)). Using it on the M1
requires a sourced or measured framebuffer description first.

Exit criterion: stable diagnostic output and captured exception reports across
repeated cold boots. No unverified register writes.

## 3 — Linux handoff

Create a Linux-compatible device tree and memory reservations; load and validate
an ARM64 Linux Image and initramfs. Satisfy the documented Linux entry register,
cache, exception-level, and interrupt-controller requirements. Develop the
minimum required Linux platform patches independently; track their provenance
and licensing alongside the kernel source.

Exit criterion: Linux reaches an initramfs shell on the physical target with
repeatable boot logs. Emulator success alone does not satisfy this milestone.

## 4 — Incremental hardware enablement

Develop and validate interrupt controller, SMP, power management, IOMMU, storage,
USB/input, networking, display/GPU, and audio support. Ordering depends on actual
dependencies found during research. Individual subsystems can be substantial
projects, especially firmware-mediated devices and GPU support.

Exit criterion: published per-device support matrix backed by hardware tests.

## 5 — Distribution and installation

Only after reliable boot and storage: reproducible Linux builds, package
integration, updates, an installer, and a tested recovery path. Full parity
with macOS is not promised.
