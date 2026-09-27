# Entry-state probe

This is an independently authored, relocatable ARM64 experiment for researching
the first handoff into our code. It records incoming CPU state into its own
payload and parks. **It has been designed for emulator validation; physical M1
execution and a way to retrieve its record are still separate work.**

## How it works

1. Branch over an embedded, initialized record at byte offset 16.
2. Use a PC-relative address to locate that record at the actual load address.
3. Save `x0`–`x3`, the incoming stack pointer, the entry address, `CurrentEL`, and
   `DAIF` (the interrupt masks).
4. Mask interrupts, order the stores, set the completion flag, and park in a
   wait-for-event loop.

It requires privileged AArch64 execution with little-endian data accesses; it
does not set endianness. It does not read through `x0`, use the incoming stack, configure memory
translation, access devices, call firmware, load Linux, or transmit anything.
Registers `x9` and `x10` are scratch. This is a diagnostic endpoint, not a
transparent trampoline: it does not preserve all CPU state or return.

Source: [entry_probe.S](../src/entry_probe.S). Layout:
[entry-probe.ld](../platform/entry-probe.ld). Build: `make probe`.

The ELF is linked at zero to expose offsets; the raw binary uses relative
addressing. Zero is not a proposed Apple load address. The emitted ELF has a
writable/executable segment for the experiment; a raw-image loader may impose
different mappings. No Apple deployment command or boot-policy modification is
part of this build.

## Record layout

All integers are little endian. The fixed record is 96 bytes. A decoder accepts
this exact version and preserves addresses as hexadecimal strings in JSON.

| Byte offset in record | Size | Field |
| --- | --- | --- |
| 0 | 8 | Magic bytes `M1PROBE` followed by NUL |
| 8 | 4 | Format version: 1 |
| 12 | 4 | Record size: 96 |
| 16 | 8 | Status: 0 pending, 1 captured |
| 24, 32, 40, 48 | 8 each | Incoming `x0`, `x1`, `x2`, `x3` |
| 56 | 8 | Incoming stack pointer |
| 64 | 8 | Actual address of the entry instruction |
| 72 | 8 | Raw `CurrentEL`: 4 for EL1, 8 for EL2, 12 for EL3 |
| 80 | 8 | Original `DAIF` register |
| 88 | 8 | Reserved: zero |

Status is written after a memory barrier and followed by another barrier. These
barriers do not flush caches or provide an external capture channel. A decoded
record is untrusted input, not authenticated evidence of execution.

## Local validation and inspection

`make test` builds both payloads, runs host-side tool tests, runs the existing
monitor test, and executes this probe with synthetic register values at several
addresses. It deliberately supplies unmapped argument/stack addresses to detect
accidental dereferences, checks record-only writes and the final parking loop,
and exercises EL1 in little-endian mode with three interrupt-mask patterns.
The installed Unicorn reports EL1 even when the PSTATE mode bits are seeded for
EL2; this setup therefore does not establish EL2 or EL3 execution. The decoder's
support for those record values is tested only with synthetic bytes.
The test also confirms that a read/execute-only mapping rejects the record write.
These checks do not validate Apple's CPU, firmware, or mapping permissions.

Inspect the initial record inside the built image:

```sh
.venv/bin/python tools/inspect_probe.py build/entry-probe.bin --offset 16
```

After `make test`, inspect a **synthetic emulator record**:

```sh
.venv/bin/python tools/inspect_probe.py build/probe-record.synthetic.bin
```

The complete test report is `build/probe-test.json`, including the tested image's
SHA-256 digest, byte size, and tool versions; these artifacts are removed
by `make clean`. There is no physical boot capture yet.

## Physical experiment prerequisites still unresolved

- Establish the chosen virtual address and the entry privilege level.
- Verify the payload record area is writable and mapped; this probe assumes it.
- Determine cache visibility and a way to retrieve the stored record after entry.
- Account for inherited vectors and the interval before interrupts are masked.
- Establish target volume/recovery details and exact firmware version before
  designing any installation procedure.

The currently documented CustomOS route is described in
[APPLE_BOOT.md](APPLE_BOOT.md). Its existence does not establish these execution
conditions. This probe has no physical success indicator until retrieval is solved.
