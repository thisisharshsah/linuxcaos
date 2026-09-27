# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the original entry probe at synthetic addresses; never execute on host."""
import hashlib
import json
import sys
from pathlib import Path
from importlib.metadata import version

from unicorn import (
    Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_READ, UC_PROT_EXEC,
    UC_HOOK_MEM_WRITE, UC_HOOK_CODE, UC_ERR_WRITE_PROT,
)
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_SP, UC_ARM64_REG_PSTATE, UC_ARM64_REG_PC,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.inspect_probe import decode_record

RECORD_OFFSET = 16
RECORD_SIZE = 96
IMAGE = (ROOT / "build/entry-probe.bin").read_bytes()


def execute(base, level, mask):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(base, 0x1000)
    cpu.mem_write(base, IMAGE)
    # Deliberately unmapped pointers/SP: the probe must not dereference them.
    inputs = [0xDEAD000012345678, 0x1111222233334444, 0xF000000000000007, 0xABCD1234EEFF5678]
    incoming_sp = 0x123456780000
    cpu.reg_write(UC_ARM64_REG_PSTATE, (level << 2) | 1 | mask)
    cpu.reg_write(UC_ARM64_REG_SP, incoming_sp)
    for reg, value in zip(
        [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3], inputs
    ):
        cpu.reg_write(reg, value)
    writes = []
    parked = []

    def on_write(uc, access, address, size, value, data):
        writes.append((address, size))
        assert base + RECORD_OFFSET + 16 <= address
        assert address + size <= base + RECORD_OFFSET + 88

    cpu.hook_add(UC_HOOK_MEM_WRITE, on_write)
    cpu.hook_add(UC_HOOK_CODE, lambda uc, address, size, data: parked.append(address),
                 begin=base + len(IMAGE) - 8, end=base + len(IMAGE) - 1)
    cpu.emu_start(base, base + len(IMAGE), count=100)
    actual = bytes(cpu.mem_read(base + RECORD_OFFSET, RECORD_SIZE))
    result = decode_record(actual)
    assert result["status"] == "captured", result
    for index, value in enumerate(inputs):
        assert int(result[f"x{index}"], 16) == value
    assert int(result["incoming_sp"], 16) == incoming_sp
    assert int(result["entry_pc"], 16) == base
    assert result["exception_level"] == level
    assert int(result["daif"], 16) == mask
    assert cpu.reg_read(UC_ARM64_REG_PSTATE) & 0x3c0 == 0x3c0
    assert cpu.reg_read(UC_ARM64_REG_SP) == incoming_sp
    park_addresses = {base + len(IMAGE) - 8, base + len(IMAGE) - 4}
    assert cpu.reg_read(UC_ARM64_REG_PC) in park_addresses
    assert all(parked.count(address) > 1 for address in park_addresses), parked
    assert writes[-1] == (base + RECORD_OFFSET + 16, 8), writes
    # Only record value bytes can change. Header, reserved word and code survive.
    memory = bytes(cpu.mem_read(base, len(IMAGE)))
    assert memory[:32] == IMAGE[:32]
    assert memory[104:] == IMAGE[104:]
    return actual, result


assert decode_record(IMAGE[16:112])["status"] == "pending"
# Last instructions are WFE and a branch back to WFE, with no trailing bytes.
assert IMAGE[-8:] == bytes.fromhex("5f2003d5ffffff17")
reports = []
for base, level, mask in [
    (0x40080000, 1, 0),
    (0x800100000, 1, 0x3c0),
    (0x1000000000, 1, 0x140),
]:
    record, report = execute(base, level, mask)
    reports.append(report)

# The source assumes writable memory; show that a read/execute-only map fails.
cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
cpu.mem_map(0x40080000, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
cpu.mem_write(0x40080000, IMAGE)
try:
    cpu.emu_start(0x40080000, 0x40080000 + len(IMAGE), count=100)
except UcError as exc:
    assert exc.errno == UC_ERR_WRITE_PROT, exc
else:
    raise AssertionError("Read/execute-only payload mapping should reject record writes")

(ROOT / "build/probe-record.synthetic.bin").write_bytes(record)
(ROOT / "build/probe-test.json").write_text(json.dumps({
    "schema_version": 1,
    "environment": "Unicorn with synthetic register state; not Apple hardware",
    "execution_coverage": "Little-endian EL1 only; EL2 and EL3 not validated",
    "unicorn_version": version("unicorn"),
    "ziglang_version": version("ziglang"),
    "image": {
        "path": "build/entry-probe.bin",
        "size_bytes": len(IMAGE),
        "sha256": hashlib.sha256(IMAGE).hexdigest(),
        "linked_base": "0x0",
        "entry_offset": 0,
        "record_offset": RECORD_OFFSET,
    },
    "results": reports,
    "read_execute_only_mapping": "write rejected as expected",
}, indent=2) + "\n")
print("PASS: entry probe relocation, EL1 register capture, bounded writes, parking, writable-map requirement")
