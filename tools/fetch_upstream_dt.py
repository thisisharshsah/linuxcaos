# SPDX-License-Identifier: GPL-2.0-or-later
"""Fetch the pinned mainline MacBookPro17,1 device tree and build it with dtc.

Downloads (with curl) the t8103-j293 device-tree sources from a pinned Linux
release and the pinned dtc release, verifies every file against the SHA-256
values recorded below, builds dtc locally, and compiles build/upstream-dt/
t8103-j293.dtb. These upstream files are test inputs only; they are not part of
this repository. Needs network access, curl, make, a C compiler, flex, bison.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "upstream-dt"
TOOLS = ROOT / "build" / "tools"

LINUX_TAG = "v7.2"
LINUX_COMMIT = "8d3ae59288f1e7d58d76558a6ee96d533bc5019f"
LINUX_PLAIN = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain"
DTS = "arch/arm64/boot/dts/apple/t8103-j293.dts"
LINUX_FILES = {
    "arch/arm64/boot/dts/apple/spi1-nvram.dtsi": "a4a26dd2abe3412221761fcbe05958599a7ff07b2fd980ab8a739a175966cc5e",
    "arch/arm64/boot/dts/apple/t8103-j293.dts": "94a83fc87db507d9ce46c705af0aadacbd2a1a54aea8737406df65f33bc3383d",
    "arch/arm64/boot/dts/apple/t8103-jxxx.dtsi": "f1a487761f772ac02cc61041624891d6eb3c29a210e6f56c2a6d65aa99aa60bb",
    "arch/arm64/boot/dts/apple/t8103-pmgr.dtsi": "1a0ac8ee94572a68177d4bdf1d18fa4b52dd15062944f76475c299a91c3ff070",
    "arch/arm64/boot/dts/apple/t8103.dtsi": "64e01abd46560ff8712d2862faf5390152a31a18e7fde596191ea4678752b1c8",
    "include/dt-bindings/gpio/gpio.h": "5423b3866877ead0920ec978b5b072f06087443033a72445b39faed8f288ddc1",
    "include/dt-bindings/interrupt-controller/apple-aic.h": "6a67506ab5333d6e552b3a656e03b34f9769af5c88cf7202b1458e1ba5067f25",
    "include/dt-bindings/interrupt-controller/irq.h": "392400a309a54ea5b1a2ac2e52773d3ab68e07323109b9aed88a69fedc74e082",
    "include/dt-bindings/leds/common.h": "7bb837c9ecda0e57f3ed0ca64e7ade99d9e8a12d947e1971887a163f5edd0977",
    "include/dt-bindings/phy/phy.h": "1bd66286362f02487d3b5eeefb4be3221b949b1eecbfc4ca717fbbbe5e8a61be",
    "include/dt-bindings/pinctrl/apple.h": "2079cb60617b0bb054e2e9e346ec6f5b3fdf8b4464ac9da89e09655e3af183b0",
    "include/dt-bindings/spmi/spmi.h": "c2952b040e5c24726c423e52ba939d389141ff27eb2307fb3888657b455e2b9b",
}
DTC_VERSION = "1.8.1"
DTC_URL = f"https://git.kernel.org/pub/scm/utils/dtc/dtc.git/snapshot/dtc-{DTC_VERSION}.tar.gz"
DTC_SHA256 = "74b50bb19134f6562490afea53e59953dd6c4afb17e5ccb60be32221262d3390"


def fetch(url: str, expected: str) -> bytes:
    data = subprocess.run(["curl", "-fsSL", url], capture_output=True, check=True, timeout=300).stdout
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"checksum mismatch for {url}: expected {expected}, got {actual}")
    return data


def build_dtc() -> Path:
    dtc = TOOLS / f"dtc-{DTC_VERSION}" / "dtc"
    if dtc.exists():
        return dtc
    TOOLS.mkdir(parents=True, exist_ok=True)
    tarball = TOOLS / f"dtc-{DTC_VERSION}.tar.gz"
    tarball.write_bytes(fetch(DTC_URL, DTC_SHA256))
    with tarfile.open(tarball) as tar:
        tar.extractall(TOOLS, filter="data")
    cc = os.environ.get("HOST_CC", "cc")
    subprocess.run(["make", "-s", f"CC={cc}", "NO_PYTHON=1", "NO_YAML=1", "NO_VALGRIND=1", "dtc"],
                   cwd=dtc.parent, check=True)
    return dtc


def main() -> int:
    src = OUT / "src"
    if OUT.exists():
        shutil.rmtree(OUT)
    for path, digest in LINUX_FILES.items():
        target = src / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetch(f"{LINUX_PLAIN}/{path}?id={LINUX_COMMIT}", digest))
    (OUT / "SOURCE.txt").write_text(f"Linux {LINUX_TAG} ({LINUX_COMMIT}), dtc {DTC_VERSION}\n")
    dtc = build_dtc()
    cc = os.environ.get("HOST_CC", "cc")
    pre = OUT / "t8103-j293.pre.dts"
    subprocess.run([cc, "-E", "-P", "-x", "assembler-with-cpp", "-nostdinc", "-undef", "-D__DTS__",
                    "-I", str(src / "include"), "-I", str(src / "arch/arm64/boot/dts/apple"),
                    str(src / DTS), "-o", str(pre)], check=True)
    subprocess.run([str(dtc), "-I", "dts", "-O", "dtb", "-o", str(OUT / "t8103-j293.dtb"), str(pre)],
                   check=True)
    print(f"Built {OUT / 't8103-j293.dtb'} from Linux {LINUX_TAG} with dtc {DTC_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
