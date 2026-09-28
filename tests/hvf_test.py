# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the monitor and screen probe on this Mac's real CPU cores (Hypervisor.framework).

Needs macOS on Apple Silicon; prints SKIP elsewhere. The guest runs at EL1 in a
VM whose memory map tools/hvf_run.c defines, so this is real instruction and
exception behaviour on Apple cores, not an M1 boot (no EL2, iBoot, or Apple
devices). All boot_args and framebuffers are invented test data.
"""
import platform
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.emulate_screen_probe import check_screen, make_bootargs  # noqa: E402
from tests.fbmodel import encode, model_cells, render_cells  # noqa: E402

RUNNER = ROOT / "build/host/hvf_run"
MONITOR = ROOT / "build/monitor.bin"
PROBE = ROOT / "build/screen-probe.bin"
BRK_4D31 = 0xD4200000 | (0x4D31 << 5)


def hvf(*args, input_text=None):
    cmd = [str(RUNNER), *map(str, args)]
    if input_text is not None:
        cmd += ["--input", input_text]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("ascii", "replace").replace("\r\n", "\n"), r.stderr.decode()


def monitor(commands, *extra):
    code, out, err = hvf("--fill", "0xa5", "--map", "0x40000000:0x200000",
                         "--load", f"{MONITOR}@0x40080000", "--entry", "0x40080000",
                         "--uart", "0x09000000", *extra, input_text=commands)
    assert code == 0 and "[stop: idle]" in err, (code, err, out[-2000:])
    assert "BSS cleared; serial ready." in out, out
    return out


def monitor_tests():
    out = monitor("help\ninfo\nregs\nstatus\n")
    assert "CurrentEL: EL1" in out and "Exceptions recovered: 0" in out, out
    vbar = int(out.split("VBAR:      0x")[1][:16], 16)
    assert vbar % 0x800 == 0 and 0x40080000 <= vbar < 0x40180000, hex(vbar)

    # A real BRK taken through the monitor's own vector table on real hardware.
    out = monitor("trap\nstatus\ntrap\nstatus\n")
    assert out.count("EC 0x3c (BRK (AArch64))") == 2 and "Exceptions recovered: 2" in out, out
    esr = int(out.split("ESR:  0x")[1][:16], 16)
    elr = int(out.split("ELR:  0x")[1][:16], 16)
    assert esr >> 26 == 0x3C and esr & 0xFFFF == 0x4D31, hex(esr)
    image = MONITOR.read_bytes()
    assert struct.unpack_from("<I", image, elr - 0x40080000)[0] == BRK_4D31, "ELR is not the BRK"

    # Framebuffer console pixels, written by real stores with the MMU off.
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp, "fb.bin")
        attach = "fb 0x40200000 320 64 1344 x2r10g10b10"
        out = monitor(attach + "\necho real cores\n", "--fill", "0x5a",
                      "--map", "0x40200000:0x100000", "--dump", f"0x40200000:{1344 * 64}:{dump}")
        raw = out.encode()
        stream = raw[raw.index((attach + "\n").encode()) + len(attach) + 1:]
        cells = model_cells(stream, 40, 4)
        want = render_cells(cells, 320, 64, 1, encode(0xE0E0E0, "x2r10g10b10"),
                            encode(0x102040, "x2r10g10b10"))
        mem = dump.read_bytes()
        for y in range(64):
            assert list(struct.unpack_from("<320I", mem, y * 1344)) == want[y], f"fb row {y}"
            assert mem[y * 1344 + 1280:(y + 1) * 1344] == b"\x5a" * 64, f"padding row {y}"

    # kimage on a synthetic Image header.
    with tempfile.TemporaryDirectory() as tmp:
        header = Path(tmp, "Image")
        header.write_bytes(struct.pack("<IIQQQQQQII", 0x91005A4D, 0x14000000, 0, 0x1A00000,
                                       0b1100, 0, 0, 0, 0x644D5241, 0x40))
        out = monitor("kimage 0x40100000\n", "--load", f"{header}@0x40100000")
        assert "page size:   16 KB" in out and "anywhere (48-bit)" in out, out


def probe_case(base, width, height, stride, depth):
    fb_base, args_at = 0x9E0000000, 0x812300040
    fb_size = (stride * height + 0x3FFF) & ~0x3FFF
    args = make_bootargs(fb_base, width, height, stride, depth)
    x = [args_at, 0x1111, 0x2222, 0x3333]
    with tempfile.TemporaryDirectory() as tmp:
        args_file, dump = Path(tmp, "args.bin"), Path(tmp, "fb.bin")
        args_file.write_bytes(args)
        code, _, err = hvf("--map", f"{base:#x}:0x100000", "--load", f"{PROBE}@{base:#x}",
                           "--map", "0x812300000:0x4000", "--load", f"{args_file}@{args_at:#x}",
                           "--fill", "0x5a", "--map", f"{fb_base:#x}:{fb_size:#x}",
                           "--entry", f"{base:#x}", "--reg", "sp=0x7f000000",
                           *[a for i in range(4) for a in ("--reg", f"x{i}={x[i]:#x}")],
                           "--dump", f"{fb_base:#x}:{stride * height}:{dump}")
        assert code == 0 and "[stop: parked]" in err, (code, err)
        state = {"x": x, "sp": 0x7F000000, "pc": base, "el": 4, "daif": 0x3C0}
        check_screen(dump.read_bytes(), width, height, stride, depth, state, args)


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        print("SKIP: Hypervisor.framework tests need macOS on Apple Silicon")
        return
    if not RUNNER.exists():
        print("SKIP: build/host/hvf_run not built (run `make hvf-test`)")
        return
    probe = subprocess.run([str(RUNNER), "--map", "0x40000000:0x4000", "--entry", "0x40000000",
                            "--max-exits", "0"], capture_output=True, text=True)
    if "hv_vm_create failed" in probe.stderr:
        print("SKIP: this machine cannot create a VM:", probe.stderr.strip())
        return
    monitor_tests()
    probe_case(0x40000000, 800, 480, 3264, 30)
    probe_case(0x812344000, 640, 400, 2560, 32)
    probe_case(0xF00000000, 1600, 208, 6528, 30)
    print("PASS (real Apple cores, Hypervisor.framework, EL1): monitor commands, real BRK "
          "exception entry and recovery, x2r10g10b10 console pixels, kimage, screen probe at "
          "three load addresses")


if __name__ == "__main__":
    main()
