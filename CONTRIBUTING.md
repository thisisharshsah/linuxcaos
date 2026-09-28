# Contributing

Thank you for helping. This project writes original boot and platform-support
code to run the existing Linux kernel on Apple Silicon, starting with the M1
MacBook Pro. Read the [living blueprint](docs/BLUEPRINT.md) first; it shows
what exists, what has been proven, and what is next.

## Getting started

Requirements: Python 3.12+, `make`, and a POSIX shell (macOS or Linux; on
Windows use WSL). No system compiler is needed, because the pinned `ziglang`
package supplies the ARM64 toolchain.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make test
```

`make test` must pass before you open a pull request. CI runs the same command
on Linux and macOS.

## Rules for every change

- **License.** All project code is GPL-2.0-or-later ([LICENSE](LICENSE)). Start
  new source files with `SPDX-License-Identifier: GPL-2.0-or-later`; a test
  enforces this.
- **Sign your work.** Add `Signed-off-by: Your Name <email>` to each commit
  (`git commit -s`). This certifies the
  [Developer Certificate of Origin](https://developercertificate.org/): you have
  the right to submit the code under the project license.
- **Write it yourself.** Do not copy code from other Apple Silicon boot projects
  (such as m1n1 or U-Boot) or from proprietary sources. Public documentation,
  including Asahi Linux's, may be read and cited. Mainline Linux is reused as
  the kernel. Record what you relied on in [docs/RESEARCH.md](docs/RESEARCH.md)
  with links.
- **Say exactly what you proved.** Use the blueprint's evidence levels: build
  passed, host tests, Unicorn instruction tests, real-core tests
  (`make hvf-test`, EL1 in a Hypervisor.framework VM), QEMU device tests, or
  physical-M1 validation. Never describe emulator success as hardware support,
  or planned work as implemented.
- **Keep the blueprint current.** For meaningful changes, update the affected
  rows in [docs/BLUEPRINT.md](docs/BLUEPRINT.md), bump its revision, and add a
  history row in the same pull request.
- **Hardware safety.** Every device address or register write needs a cited
  source or recorded observation. Never run guessed MMIO accesses on a real Mac.

## Where to help

- New boards: see [platform/README.md](platform/README.md).
- Open items: the "Immediate next work" table in the blueprint and the
  milestones in [docs/ROADMAP.md](docs/ROADMAP.md).
- Host tools and tests are good first contributions: they run anywhere and need
  no Apple hardware.

## Reporting hardware results

Hardware reports are valuable even when they fail. Include the exact Mac model,
macOS and firmware versions, the commit tested, the exact steps, and raw
captures. Use the observation template in [docs/RESEARCH.md](docs/RESEARCH.md).
Do not change boot security settings on a machine you cannot afford to
recover.
