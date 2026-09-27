# Apple custom-boot research and first-entry experiment

Research date: **2026-09-27**. This document supports the
[living blueprint](BLUEPRINT.md) and records primary-source evidence for milestone
M1. **No Apple entry interface, payload acceptance, or physical-M1 execution has
been validated.** Project boot/platform code is independently authored; the
existing Linux kernel remains the intended OS core.

## What the sources establish

| Question | Primary-source evidence | What remains unproven here |
| --- | --- | --- |
| Can Apple firmware transfer control to a custom OS? | Apple's LocalPolicy documentation describes `coih`, a SHA-384 hash of a CustomOS Image4 manifest. iBoot uses that manifest's payload instead of XNU for control transfer. The documented policy update route is `kmutil configure-boot` in One True Recovery (1TR). [Apple: LocalPolicy contents](https://support.apple.com/en-gb/guide/security/secc745a0845/web) | Acceptance of an artifact produced by this project; the complete entry contract. |
| What policy permits this? | Apple says Permissive Security permits locally Secure Enclave signed boot objects and provides an architectural route for an arbitrary OS kernel. Signature verification still occurs. [Apple: Startup Disk security policy](https://support.apple.com/en-gb/guide/security/sec7d92dc49f/web) | The exact provisioning procedure for a separate project boot target and its recovery procedure. No policy changes were performed. |
| Which earlier firmware remains Apple's? | The documented chain begins with Boot ROM and LLB, then iBoot. LLB and iBoot also load firmware for other components. [Apple: boot process](https://support.apple.com/en-ca/guide/security/secac71d5623/web) | Which devices and firmware services remain usable at our entry point. This project does not replace Boot ROM or Apple-signed firmware. |
| Can the input be a raw binary? | Installed Apple `kmutil` help documents `--raw`, `--custom-boot-object`, `--lowest-virtual-address`, and `--entry-point`. The last two are **virtual addresses**, with iBoot mapping the raw object at the requested lowest virtual address. | Permitted addresses, alignment, image size, segment permissions, relocation behavior, and entry CPU state. Help output is interface documentation, not a successful boot test. |

The local observation was made with `/usr/bin/kmutil configure-boot --help` on
**macOS 27.0, build 26A428**. Only help was executed. The help calls the operation
recovery-only and also mentions Mach-O payload compression. This is enough to
justify researching a raw-file workflow; it does not establish that an arbitrary
ELF file or the current QEMU monitor is a valid Apple payload. Our JSON test
report is validation metadata, not Apple's Image4 manifest.

The Apple security pages are live documents retrieved on the research date;
Apple's boot-process and security-policy pages display publication dates of
2021-02-18. The local help describes this installed macOS build, not every
recoveryOS or firmware version.

## Entry-register hypothesis from Apple's kernel

Source baseline: Apple XNU tag **`xnu-7195.81.3`**, peeled Git commit
**`e890dd3c5b68b2b8f7c726c8812e74cc347cb0ba`**. The tag was resolved against Apple's
public repository. It is a historical source baseline, not a claim that this
checkout matches the running macOS kernel.

Apple's ARM64 startup labels its cold-entry argument as `x0` containing boot
arguments. The entry trampoline branches to that routine, which preserves `x0`,
reads memory parameters through it, establishes stacks and translation tables,
and later converts the argument address before entering C. These are observations
of an **XNU consumer**, not a public guarantee for every CustomOS raw payload.
[Apple XNU startup, pinned source](https://github.com/apple-oss-distributions/xnu/blob/e890dd3c5b68b2b8f7c726c8812e74cc347cb0ba/osfmk/arm64/start.s#L293)

Working hypothesis: a custom payload may receive a boot-argument pointer in
`x0`. Our first experiment must preserve the incoming value without dereferencing
it. The cited code does not establish our incoming exception level, `x1`–`x3`,
stack validity, current address translations, write permissions, cache state,
interrupt state, or a callable firmware console. No register value or physical
address has been measured on the M1.

## Candidate boot-argument layout for offline decoding

Apple's pinned ARM64 header describes a `boot_args` structure with revision and
version fields, memory bases and sizes, video information, a device-tree pointer,
a command line, and trailing flags. It defines a 608-byte command-line field.
[Apple XNU boot header, pinned source](https://github.com/apple-oss-distributions/xnu/blob/e890dd3c5b68b2b8f7c726c8812e74cc347cb0ba/pexpert/pexpert/arm64/boot.h#L23)

The following offsets are **derived using ordinary ARM64 LP64 alignment** from
that header; they are not a captured firmware structure or a universal format.

| Byte offset | Candidate field | Size in bytes |
| --- | --- | --- |
| `0x000`, `0x002` | `Revision`, `Version` | 2 each |
| `0x008`, `0x010` | `virtBase`, `physBase` | 8 each |
| `0x018`, `0x020` | `memSize`, `topOfKernelData` | 8 each |
| `0x028` | `Video`: base, display, row bytes, width, height, depth | 48 |
| `0x058` | `machineType` | 4 |
| `0x060`, `0x068` | `deviceTreeP`, `deviceTreeLength` | 8, 4 |
| `0x06c` | `CommandLine` | 608 |
| `0x2d0`, `0x2d8` | `bootFlags`, `memSizeActual` | 8 each |

Derived total size: `0x2e0` (736 bytes), including alignment padding. The same
header defines revision constants 1 and 2 (revision 2 adds `bootFlags`), version
constants 1 and 2, bit 0 of `bootFlags` as dark boot, and packs `v_depth` as
pixel depth in bits 0–7, rotation from bit 8, and scale from bit 16.

[inspect_bootargs.py](../tools/inspect_bootargs.py) implements this as an offline
decoder: it accepts only a bounded byte capture, exposes revision/version,
rejects truncated or unsupported layouts, and never reads a live pointer
supplied in a capture. Pointer-bearing fields are evidence
to investigate, not proof that those addresses are valid or safe to access.
Neither the device-tree encoding nor framebuffer writeability is established by
this field list.

## First experiment and its limits

The proposed first-entry probe is a small, independently written ARM64 raw image:

1. Preserve incoming `x0`–`x3` and the incoming stack-pointer value without using
   the incoming stack or dereferencing those registers.
2. Record its own entry address, `CurrentEL`, and the original interrupt-mask
   state (`DAIF`) into an explicitly reserved record inside the payload.
3. Finish the record and park execution. Do not touch Apple MMIO, attempt a Linux
   handoff, or infer a UART address from the QEMU monitor.
4. Decode saved records on the host. Track artifact hash, toolchain version,
   record version, requested mapping, target/firmware details, and test class.

Before a hardware attempt, executable instruction tests can load the identical
raw bytes at multiple addresses, seed distinct register values, and verify the
record plus bounded execution. These tests can establish the probe's relocation
behavior and data capture under their specified emulator state. The current
implementation and actual test results belong in [BLUEPRINT.md](BLUEPRINT.md);
this research plan alone is not test evidence.

There are three unresolved prerequisites for a useful physical experiment:

| Prerequisite | Why it matters | Evidence needed next |
| --- | --- | --- |
| Entry privileges and writable payload storage | Reading privileged state and storing the record may fault. The raw-file help does not promise these properties. | A documented contract or independently observed entry state/mappings for the exact target firmware. |
| An observable record or visible marker | A record in RAM followed by a loop cannot be retrieved by an ordinary reboot. CPU caches may also affect external visibility. | A demonstrated capture/transport method and its cache rules, or a separately validated display/debug output channel. |
| A dedicated boot target and a repeatable return path | A packaged object alone does not establish provisioning or recoverability. | A concrete target-specific experiment and recovery procedure, reviewed before changing boot configuration. |

Until these are resolved, raw-image generation and emulator tests are preparatory
work. A physical pass requires a repeatable observable result from our code on
the target Mac and a saved capture. Host tests, Unicorn instruction tests, and
QEMU device-model tests cannot satisfy that gate.

## Secondary-source findings (Asahi documentation, 2026-09-27)

At the project owner's request, Asahi Linux's public documentation was read
(not its code); sources and details are in [RESEARCH.md](RESEARCH.md). It
reports that iBoot enters a custom payload **at EL2 with the MMU off and `x0`
pointing to `boot_args`**, consistent with the hypothesis above; that RAM starts
at physical `0x8_0000_0000`; that flat ARM64 images are accepted since macOS
12.1; and that iBoot locks the boot CPU's reset vector (RVBAR) to the top of the
entry page, so that page must be treated as resident code. These are documented
claims from a third party, not our measurements, and they refine rather than
replace the experiment plan: the probe should confirm them on this Mac.

## Research provenance

The original investigation used Apple's security documentation, the two pinned
Apple XNU files linked above, and installed Apple command help. No Asahi, m1n1,
or U-Boot implementation was consulted or incorporated for this work. Asahi
documentation (not code) was consulted afterwards, as recorded above. Reading
Apple's public definitions for interface research does not itself constitute an
audited clean-room process. No Apple source is vendored by this document.
