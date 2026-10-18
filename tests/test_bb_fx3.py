"""Unicorn tests for FX3 on the Blackbox (bb/src/fx3.c, reverb.c, fx3_thunk.S) on out/bb/master+clip+fx3/BLACKBOX.bin.

Real firmware code runs for: the stock plate init 0x08074d1c (operator new 0x080443a8 replaced; compared with our
template), the plate core 0x08074f50 (Type Plate), the settings store, the buffer accessors and the mix 0x0804da6c, the
send curve 0x08060930.

  python3 -I tests/test_bb_fx3.py        (after bb/build.py and bb/patch.py master clip fx3)
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R3, UC_ARM_REG_R4  # noqa: E402

from bb_emu import APP_PADS, BASE, IMG, SETTINGS, SYM, BBEmu, bl_target, check, done  # noqa: E402

e = BBEmu()
PLATE = 0x38001000
N = 128

# --- sites
for at, name in ((0x08053516, "fx3_master"), (0x08059ACE, "fx3_send_a"), (0x080688D0, "fx3_send_b")):
    t = bl_target(IMG[at - BASE:at - BASE + 4], at)
    check(f"{at:#x} -> {name}", t == SYM[name] & ~1, hex(t or 0))
conf = [struct.unpack_from("<H", IMG, a - BASE)[0] for a in (0x080EF0A0, 0x080EF208, 0x080EF370, 0x080EF4DC, 0x080EF640,
                                                             0x080EF912, 0x080EFA7A, 0x080EFBE2, 0x080EFD4C)]
check("FX3 Send (0x1f2) at the end of all nine Conf pages", conf == [0x1F2] * 9, conf)
check("settings store capacity 80", IMG[0x08094820 - BASE:0x08094822 - BASE] == b"\x50\x21")

# --- plate template = the stock init's result (operator new -> our buffers)
allocs = []
e.mu.mem_map(0x60000000, 0x40000)                           # the stock init's 213 KB of buffers (test only)


def new(uc):
    n = uc.reg_read(UC_ARM_REG_R0)
    p = 0x60000000 + sum(m for _, m in allocs)
    allocs.append((p, n))
    uc.reg_write(UC_ARM_REG_R0, p)


e.stub(0x080443A8, new)
stock = e.new(0xC0)
e.call(0x08074D1C, stock)
e.unstub(0x080443A8)
sw = struct.unpack("<44I", e.mu.mem_read(stock, 0xB0))

# settings store at SETTINGS with the defaults chain (also runs fx3_init)
ents = e.new(80 * 8)
e.w32(SETTINGS + 4, ents)
e.mu.mem_write(SETTINGS + 0xA, struct.pack("<HH", 0, 80))
e.call(SYM["bb_defaults"], SETTINGS, 0xB4, 1)
cnt = struct.unpack("<H", e.mu.mem_read(SETTINGS + 0xA, 2))[0]
check(f"settings: {cnt} entries after the defaults (stock 1 + mod 1 + dist 5 + FX3 15)", cnt == 22)
ow = struct.unpack("<44I", e.mu.mem_read(PLATE, 0xB0))
bufw = {8, 11, 14, 17, 20, 25, 30, 33, 37, 39, 41, 43}
check("plate state: all non-buffer words as the stock init leaves them",
      all(ow[k] == sw[k] for k in range(44) if k not in bufw), [(k, hex(ow[k]), hex(sw[k])) for k in range(44)
                                                                if k not in bufw and ow[k] != sw[k]])
check("plate buffers: same sizes and order as the stock init, packed in D2 SRAM from 0x30000000",
      [n for _, n in allocs] == [2048] * 4 + [4096] * 2 + [32768] * 6
      and [ow[k] for k in sorted(bufw)] == [0x30000000 + sum(n for _, n in allocs[:i]) for i in range(12)])
check("D2 SRAM clocks: RCC_AHB2ENR bits 29-31 set", e.r32(0x580244DC) >> 29 == 7)


def setv(pid, v):
    for k in range(cnt):
        if struct.unpack_from("<H", e.mu.mem_read(ents + 8 * k, 2))[0] == pid:
            e.w32(ents + 8 * k + 4, v)
            return
    raise KeyError(hex(pid))


# --- send: a pad record with FX3 Send, scratch buffers
rec = APP_PADS + 1 * 0xF0 + 2 * 0x30
t3 = e.new(4)
e.mu.mem_write(t3, b"\x03")
e.call(0x08094A1C, rec, t3)
e.call(0x08093ECC, rec, 0x1F2, 1000)
pad = e.new(0x700)
e.w32(pad + 0x18, 1 << 8 | 2)


def buf(left, right=None, silent=0):
    b, L, R = e.new(0x14), e.new(4 * N), e.new(4 * N)
    e.wf(L, left)
    e.wf(R, right if right is not None else left)
    e.mu.mem_write(b, struct.pack("<IIIIBB2x", N, N, L, R, silent, 1))
    return b, L, R


ACC_L, ACC_R = 0x30044000, 0x30044200
e.w32(0x38000E00 + 0x2C, 0)                                 # acc_n
s1, _, _ = buf([1.0] * N, [0.5] * N)
e.call(SYM["fx3_send"], s1, pad)
g_full = e.rf(ACC_L, 1)[0]
e.call(SYM["fx3_send"], s1, pad)
check(f"send: FX3 Send 100 % -> gain {g_full:.3f}; two pads add up; right plane kept apart",
      0.5 < g_full <= 1.0 and abs(e.rf(ACC_L, 1)[0] - 2 * g_full) < 1e-6 and abs(e.rf(ACC_R, 1)[0] - g_full) < 1e-6)
e.call(0x08093ECC, rec, 0x1F2, 0)
before = e.rf(ACC_L, 1)[0]
e.call(SYM["fx3_send"], s1, pad)
check("send: FX3 Send 0 -> nothing added", e.rf(ACC_L, 1)[0] == before)
e.call(0x08093ECC, rec, 0x1F2, 1000)
ssil, _, _ = buf([1.0] * N, silent=1)
e.call(SYM["fx3_send"], ssil, pad)
check("send: silent scratch -> nothing added", e.rf(ACC_L, 1)[0] == before)

# the thunk: scratch from the caller's [sp + 0x18], pad r4, r3 = FX2 gain pointer kept, s15 = *r3
gainp = e.new(4)
e.wf(gainp, [0.25])
e.w32(0x38000E00 + 0x2C, 0)
e.call(SYM["fx3_send_a"], 0x11, 0x22, 0x33, gainp, stack=[0] * 6 + [s1], regs=[(UC_ARM_REG_R4, pad)])
from unicorn.arm_const import UC_ARM_REG_S15  # noqa: E402
s15 = struct.unpack("<f", struct.pack("<I", e.mu.reg_read(UC_ARM_REG_S15)))[0]
check("thunk fx3_send_a: scratch from [sp, #0x18], s15 = FX2 gain, r0-r3 kept",
      abs(e.rf(ACC_L, 1)[0] - g_full) < 1e-6 and s15 == 0.25
      and e.regs(UC_ARM_REG_R0, UC_ARM_REG_R3) == [0x11, gainp])


# --- effect: an impulse through each type, added to bus 0 together with the FX2 return
B0, L0, R0 = e.new(0x14), e.new(4 * N), e.new(4 * N)
F2, LF, RF = e.new(0x14), e.new(4 * N), e.new(4 * N)
IM, LI, RI = e.new(0x14), e.new(4 * N), e.new(4 * N)


def fill(b, L, R, vals):
    e.wf(L, vals)
    e.wf(R, vals)
    e.mu.mem_write(b, struct.pack("<IIIIBB2x", N, N, L, R, 0, 1))


def run_type(typ, blocks=120, predly=0):
    setv(0x1B8, typ)
    setv(0x1BB, predly)
    e.w32(0x38000E00, 0)                                      # fresh FX3 state ...
    e.call(SYM["fx3_init"])                                   # ... and memory
    out = []
    for k in range(blocks):
        if k == 0:
            e.w32(0x38000E00 + 0x2C, 0)
            fill(IM, LI, RI, [1.0] + [0.0] * (N - 1))
            e.call(SYM["fx3_send"], IM, pad)
        fill(B0, L0, R0, [0.0] * N)
        fill(F2, LF, RF, [0.001] * N)
        e.call(SYM["fx3_master"], B0, F2)
        out += e.rf(L0, N)
    return out


for typ, name in ((0, "Plate"), (1, "Room"), (2, "Hall"), (3, "Chamber")):
    y = run_type(typ)
    tail = [v - 0.001 for v in y]                             # the FX2 return's 0.001 is in every sample
    ok_num = all(math.isfinite(v) for v in tail)
    e1 = sum(v * v for v in tail[:N * 40])
    e2 = sum(v * v for v in tail[N * 80:])
    peak = max(abs(v) for v in tail)
    check(f"{name}: impulse -> tail (energy {e1:.2e} early, {e2:.2e} late), bounded (peak {peak:.3f}), FX2 return kept",
          ok_num and e1 > 1e-6 and e2 < e1 and peak < 2.0 and abs(y[N * 119 + 5] - 0.001 - tail[N * 119 + 5]) < 1e-9)

y = run_type(0, blocks=200, predly=1000)                     # 12256 samples at 29.8 kHz = 0.41 s pre-delay
first = next((i for i, v in enumerate(y) if abs(v - 0.001) > 1e-6), None)
check(f"Pre-Delay 100 %: first output at {first} frames (0.41 s = 19740)", first is not None and 19000 < first < 21000)

done()
