# Research log

The [living blueprint](BLUEPRINT.md) connects these observations to the system
architecture, implementation status, and next milestones.

## Initial target inventory

- Host reports MacBookPro17,1, Apple M1, 8 GB RAM.
- Source: read-only `system_profiler SPHardwareDataType` on the development host.
- No Apple entry ABI, physical addresses, or boot compatibility has been verified.
- No partitions, boot policy, or firmware have been changed.

## Emulator contract

- Development target: QEMU virt, cortex-a57, one CPU, 128 MiB RAM.
- Payload link address: 0x40080000; stack reserved in the linker script.
- PL011 base: 0x09000000 for this target only.
- Register offsets: DR 0x00, FR 0x18, LCRH 0x2c, CR 0x30.
- Reference: QEMU virt documentation and QEMU PL011 device model.
- Instruction-level tests use a deliberately simplified UART model; they do not
  verify baud rates, real bus ordering, hardware faults, or Apple devices.

## 2026-09-27 — Apple entry research and probe

- Primary sources: Apple Platform Security and pinned Apple XNU source; details
  and links are in [APPLE_BOOT.md](APPLE_BOOT.md). No third-party boot code was
  imported.
- Local method: `/usr/bin/kmutil configure-boot --help`, a read-only help query.
  It documents raw custom boot objects, virtual entry/mapping addresses, and a
  recovery-only operation. No boot-policy operation was performed.
- Source observation: Apple's LocalPolicy documentation describes CustomOS
  payload control transfer. Historical XNU startup consumes a boot-argument
  pointer in `x0`.
- Interpretation: preserving incoming `x0` is a useful first experiment. It is
  not confirmation that this firmware supplies a valid boot-argument pointer
  to our raw object; dereferencing it is deferred.
- New experiment: [entry_probe.S](../src/entry_probe.S) saves `x0`–`x3`, incoming
  SP, its entry address, CurrentEL, and DAIF without accessing Apple devices.
  The [record decoder](../tools/inspect_probe.py) operates only on saved files.
- Evidence class: host tests and synthetic instruction execution; latest results
  are recorded in [BLUEPRINT.md](BLUEPRINT.md). No physical capture exists.
- Remaining unknowns: actual entry privilege/endianness/mappings, writable
  payload storage, cache visibility, output/capture transport, and exact target
  provisioning/recovery procedure.
- Disconfirming tests: a non-writable map should fail the record store; a moved
  image should still record its actual entry address. Synthetic tests cover
  these conditions but cannot establish what Apple's firmware supplies.

## 2026-09-27 — boot_args header re-check and exception handling

- Source: Apple XNU `pexpert/pexpert/arm64/boot.h` at the pinned commit
  `e890dd3c5b68b2b8f7c726c8812e74cc347cb0ba`, fetched as raw text (SHA-256
  `b963e576533b8ee06b981ab6432c1d8d1d5f11a5c320ecfbc26b43012c7bd30c`).
- Confirmed: every field offset in [APPLE_BOOT.md](APPLE_BOOT.md); revision
  constants 1 and 2 (2 adds `bootFlags`); version constants 1 and 2; dark-boot
  flag bit 0; `v_depth` packing (depth bits 0–7, rotate from bit 8, scale from 16).
- Not established: that current firmware uses this layout, that our payload
  receives it, or the framebuffer's pixel channel order and writeability.
- Tool observation: Unicorn 2.1.4 stops with `UC_ERR_EXCEPTION` on BRK/SVC/UDF
  and with unmapped-access errors on aborts, leaving PC at the faulting
  instruction. It never enters the guest vector table, so exception tests model
  entry in the harness. QEMU (not installed) or hardware must test real entry.

## 2026-09-27 — Linux arm64 boot contract and tooling

- Source: Linux `Documentation/arch/arm64/booting.rst` from torvalds/linux,
  latest commit touching it `2bc6b218717b9d08f466f88209251d54bc09b207`
  (SHA-256 of fetched text `3ac50b9d3d96602fbea26bd72c81f924c81162f5330d27de6e60807fbd860a86`).
- Used: 64-byte header layout and magic `0x644d5241`; flags bit 0 endianness,
  bits 1–2 page size, bit 3 placement; image_size 0 means a pre-v3.17 header;
  Image at text_offset above a 2 MB aligned base; DTB 8-byte aligned, at most
  2 MB, not sharing a 2 MB region needing special attributes; initrd and kernel
  inside one 1 GB aligned window of at most 32 GB; x0 = DTB, x1–x3 = 0; DAIF
  masked; EL2 recommended, or EL1.
- Project policy beyond the document: text_offset must be below 2 MB and 4 KB
  aligned; pre-v3.17 and big-endian images are rejected.
- DTB format: Devicetree Specification v0.4, section 5. A generated DTB was
  cross-checked with the third-party `fdt` 0.3.3 Python parser, used only in a
  throwaway environment.
- Tool availability: no Homebrew on this Mac; conda-forge offers no macOS QEMU
  (only `qemu-execve-*` Linux packages); the one macOS arm64 QEMU found was in a
  personal channel and was not installed.

## Future observation template

Record date, exact device and firmware, question, method, raw capture location,
observation, interpretation, confidence, and a disconfirming test. Distinguish
observed values from hypotheses and sourced specifications.
