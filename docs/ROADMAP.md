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

The owner has one Mac and no debug cable, so the first experiment is the
[screen probe](SCREEN_PROBE.md): it reports entry state on the display.

Asahi documentation (a secondary source) reports EL2 entry with the MMU off and
`x0` = `boot_args`; the probe should confirm this. Asahi develops on hardware,
not emulators: code is sent over USB-C from a second computer, and a second
Apple Silicon Mac can provide the physical serial console.

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

Preparation so far: exception vectors with crash reports, a platform-neutral
framebuffer text console, and an offline `boot_args` decoder, tested only in
emulators and host tests (see the [blueprint](BLUEPRINT.md)). Using it on the M1
requires a sourced or measured framebuffer description first.

Exit criterion: stable diagnostic output and captured exception reports across
repeated cold boots. No unverified register writes.

## 3 — Linux handoff

Create a Linux-compatible device tree and memory reservations; load and validate
an ARM64 Linux Image and initramfs. Satisfy the documented Linux entry register,
cache, exception-level, and interrupt-controller requirements. Develop the
minimum required Linux platform patches independently; track their provenance
and licensing alongside the kernel source.

Groundwork so far: portable Image header validation and load planning, and a
DTB builder, tested on the host only (see the [blueprint](BLUEPRINT.md)).

The main loader work is filling the mainline device tree (memory, framebuffer,
and other bootloader-supplied properties) from what the firmware provides. The
kernel must be built with 16K pages.

Exit criterion: Linux reaches an initramfs shell on the physical target with
repeatable boot logs. Emulator success alone does not satisfy this milestone.

## 4 — Incremental hardware enablement

Mainline Linux already contains a MacBookPro17,1 device tree and drivers for the
interrupt controller, UART, NVMe, PCIe, USB, IOMMU, SMC, and more (see
[RESEARCH.md](RESEARCH.md)). First reuse and validate that support on the target;
develop independently only what is missing or broken, and track provenance and
licensing of any kernel patches. Firmware-mediated devices and the GPU remain
substantial projects.

Exit criterion: published per-device support matrix backed by hardware tests.

## 5 — Distribution and installation

Only after reliable boot and storage: reproducible Linux builds, package
integration, updates, an installer, and a tested recovery path. Full parity
with macOS is not promised.
