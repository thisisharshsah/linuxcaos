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

## Future observation template

Record date, exact device and firmware, question, method, raw capture location,
observation, interpretation, confidence, and a disconfirming test. Distinguish
observed values from hypotheses and sourced specifications.
