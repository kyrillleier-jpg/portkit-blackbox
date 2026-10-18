"""Unicorn harness for the patched Blackbox image (out/bb/master+clip+fx3/BLACKBOX.bin), shared by tests/test_bb_*.py.

As tests/test_fidelity.py's Emu: an A-profile CPU in Thumb state with the FPU on runs the Thumb-2 / FPv5 code; the
firmware's bump allocator 0x0804436c is replaced by one of ours (AXI SRAM 0x24040000 on).
"""
import os
import struct
import sys

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_CPU_ARM_MAX)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "patches"))
from thumb import BASE, bl_target, symbols  # noqa: E402,F401

# the image under test: the 3.1.n build by default; tests/test_jb.py sets PK_BB=jb for the JOEBOX 1 build (two banks)
if os.environ.get("PK_BB") == "jb":
    IMG = open(os.path.join(ROOT, "out", "bb", "jb", "release", "BLACKBOX.bin"), "rb").read()
    B2 = open(os.path.join(ROOT, "out", "bb", "jb", "bank2.bin"), "rb").read()
    SYM = symbols(os.path.join(ROOT, "out", "bb", "jb", "cave.elf"))
    MOD = SYM
else:
    IMG = open(os.path.join(ROOT, "out", "bb", "master+clip+fx3", "BLACKBOX.bin"), "rb").read()
    B2 = b""
    SYM = symbols(os.path.join(ROOT, "out", "bb", "cave.elf"))
    MOD = symbols(os.path.join(ROOT, "out", "bb", "base", "mod_cave.elf"))
APP = 0x24020088
SETTINGS = APP + 0x8C90
APP_PADS = APP + 0x1840
TABLE_PTR = 0x2401F4FC                     # the parameter table's pointer (literal at 0x0808c0d4)
RET = 0x24000000
STACK = 0x2407F000

failures = 0


def check(what, ok, detail=""):
    global failures
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f"   {detail}"))
    failures += 0 if ok else 1


def done():
    print("all ok" if failures == 0 else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


class BBEmu:
    def __init__(self):
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        mu.ctl_set_cpu_model(UC_CPU_ARM_MAX)
        mu.mem_map(BASE, 0x200000)                # both flash banks
        mu.mem_write(BASE, IMG)
        if B2:
            mu.mem_write(0x08100000, B2)
        mu.mem_map(0x24000000, 0x80000)          # AXI SRAM
        mu.mem_map(0x38000000, 0x10000)          # SRAM4: our state
        mu.mem_map(0x30000000, 0x48000)          # D2 SRAM: FX3
        mu.mem_map(0x58024000, 0x1000)           # RCC (fx3_init switches the D2 SRAM clocks on)
        mu.mem_map(0xE0000000, 0x100000)         # SCS: DWT (stretch.c)
        mu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
        mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        mu.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: uc.emu_stop(), begin=RET, end=RET)
        self.heap = 0x24058000                   # test objects (D2 SRAM belongs to FX3: fx3_init clears it)
        self.alloc_at = 0x24040000
        self.stubs, self.hooked = {}, set()
        self.stub(0x0804436C, self._alloc)

    def _hook(self, uc, addr, size, _):
        if addr in self.stubs:
            self.stubs[addr](uc)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def stub(self, addr, fn):
        addr &= ~1
        self.stubs[addr] = fn
        if addr not in self.hooked:
            self.hooked.add(addr)
            self.mu.hook_add(UC_HOOK_CODE, self._hook, begin=addr, end=addr)

    def unstub(self, addr):
        self.stubs.pop(addr & ~1, None)

    def _alloc(self, uc):
        n = uc.reg_read(UC_ARM_REG_R0) * max(1, uc.reg_read(UC_ARM_REG_R1))
        p = self.alloc_at
        self.alloc_at += (n + 15) & ~15
        uc.mem_write(p, bytes(n))
        uc.reg_write(UC_ARM_REG_R0, p)

    def new(self, size):
        p = self.heap
        self.heap += (size + 15) & ~15
        assert self.heap <= 0x2407C000, "test heap exhausted"
        self.mu.mem_write(p, bytes(size))
        return p

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.mu.mem_read(a, 4))[0]

    def r16(self, a):
        return struct.unpack("<H", self.mu.mem_read(a, 2))[0]

    def wf(self, a, vals):
        self.mu.mem_write(a, struct.pack(f"<{len(vals)}f", *vals))

    def rf(self, a, n):
        return list(struct.unpack(f"<{n}f", self.mu.mem_read(a, 4 * n)))

    def cstr(self, a):
        return bytes(self.mu.mem_read(a, 32)).split(b"\0")[0].decode()

    def call(self, fn, *args, stack=(), regs=()):
        mu = self.mu
        sp = STACK - 4 * len(stack)
        for k, v in enumerate(stack):
            self.w32(sp + 4 * k, v)
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            mu.reg_write(r, v & 0xFFFFFFFF)
        for r, v in regs:
            mu.reg_write(r, v & 0xFFFFFFFF)
        mu.reg_write(UC_ARM_REG_SP, sp)
        mu.reg_write(UC_ARM_REG_LR, RET | 1)
        mu.emu_start(fn | 1, RET, count=50_000_000)
        return mu.reg_read(UC_ARM_REG_R0)

    def regs(self, *names):
        return [self.mu.reg_read(r) for r in names]
