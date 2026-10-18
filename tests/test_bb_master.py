"""Unicorn tests for the Blackbox master distortion (bb/src/master.c) on the patched image out/bb/master+clip+fx3/BLACKBOX.bin.

Real firmware code runs for: the parameter table insert (0x0808c0a8 via 0x0808c0d8 / 0x0808c12c), blackbox-mod's
comp_register / comp_defaults (chained by ours), the settings store (add 0x08093ef6, get 0x08093e9c) and the buffer
accessors (0x0804d8e8, 0x0804d9c0). The DSP is compared sample by sample with the Bitbox micro's master_dist (same
code, run in the micro image by tests/render_master.py's Master) for every type with Tone off.

  python3 -I tests/test_bb_master.py        (after bb/build.py and bb/patch.py master clip)
"""
import math
import os
import struct
import sys

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP,
                               UC_CPU_ARM_MAX)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "patches"))
from thumb import BASE, bl_target, symbols  # noqa: E402

IMG = open(os.path.join(ROOT, "out", "bb", "master+clip+fx3", "BLACKBOX.bin"), "rb").read()
SYM = symbols(os.path.join(ROOT, "out", "bb", "cave.elf"))
MOD = symbols(os.path.join(ROOT, "out", "bb", "base", "mod_cave.elf"))
SETTINGS = 0x24020088 + 0x8C90
TABLE_PTR = 0x2401F4FC                     # the parameter table's pointer (literal at 0x0808c0d4)
RET = 0x24000000
STACK = 0x2407F000
IDS = {"dtype": 0x1E8, "drive": 0x1E9, "tone": 0x1EA, "mix": 0x1EB, "level": 0x1EC}
N = 128

failures = 0


def check(what, ok, detail=""):
    global failures
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f"   {detail}"))
    failures += 0 if ok else 1


class BBEmu:
    def __init__(self):
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        mu.ctl_set_cpu_model(UC_CPU_ARM_MAX)
        mu.mem_map(BASE, (len(IMG) + 0xFFFF) & ~0xFFFF)
        mu.mem_write(BASE, IMG)
        mu.mem_map(0x24000000, 0x80000)          # AXI SRAM
        mu.mem_map(0x38000000, 0x10000)          # SRAM4: our state
        mu.mem_map(0x30000000, 0x48000)          # D2 SRAM: FX3
        mu.mem_map(0x58024000, 0x1000)           # RCC (fx3_init switches the D2 SRAM clocks on)
        mu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
        mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        mu.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: uc.emu_stop(), begin=RET, end=RET)
        self.heap = 0x24058000                   # test objects (D2 SRAM belongs to FX3: fx3_init clears it)

    def new(self, size):
        p = self.heap
        self.heap += (size + 15) & ~15
        self.mu.mem_write(p, bytes(size))
        return p

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.mu.mem_read(a, 4))[0]

    def wf(self, a, vals):
        self.mu.mem_write(a, struct.pack(f"<{len(vals)}f", *vals))

    def rf(self, a, n):
        return list(struct.unpack(f"<{n}f", self.mu.mem_read(a, 4 * n)))

    def cstr(self, a):
        return bytes(self.mu.mem_read(a, 32)).split(b"\0")[0].decode()

    def call(self, fn, *args, stack=()):
        mu = self.mu
        sp = STACK - 4 * len(stack)
        for k, v in enumerate(stack):
            self.w32(sp + 4 * k, v)
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            mu.reg_write(r, v & 0xFFFFFFFF)
        mu.reg_write(UC_ARM_REG_SP, sp)
        mu.reg_write(UC_ARM_REG_LR, RET | 1)
        mu.emu_start(fn | 1, RET, count=20_000_000)
        return mu.reg_read(UC_ARM_REG_R0)


e = BBEmu()

# --- hook sites: the mod's BLs are now ours, ours call the mod's functions
for at, name, mod in ((0x0808D350, "bb_register", "comp_register"), (0x08094886, "bb_defaults", "comp_defaults")):
    t = bl_target(IMG[at - BASE:at - BASE + 4], at)
    check(f"{at:#x} -> {name}", t == SYM[name] & ~1, hex(t or 0))
t = bl_target(IMG[0x08053528 - BASE:0x08053528 - BASE + 4], 0x08053528)
check("0x08053528 -> dist_thunk", t == SYM["dist_thunk"] & ~1, hex(t or 0))

# --- settings defaults: the stock entry, blackbox-mod's Comp Thresh, then ours
store = SETTINGS
ents = e.new(64 * 8)
e.w32(store + 4, ents)
e.mu.mem_write(store + 0xA, struct.pack("<HH", 0, 64))
e.call(SYM["bb_defaults"], store, 0xB4, 1)
cnt = struct.unpack("<H", e.mu.mem_read(store + 0xA, 2))[0]
got = [struct.unpack_from("<Hxxi", e.mu.mem_read(ents + 8 * k, 8)) for k in range(cnt)]
check("defaults: Compressor, Comp Thresh, Dist Type/Drive/Tone/Mix/Level, FX3 Decay/Damp/PreDly/Type ...",
      got[:10] == [(0xB4, 1), (0x1D0, 0), (0x1E8, 0), (0x1E9, 12000), (0x1EA, 1000), (0x1EB, 1000), (0x1EC, 0),
                   (0x1B9, 600), (0x1BA, 500), (0x1BB, 0)] and len(got) == 22 and got[10] == (0x1B8, 0), got)

# --- registration: the mod's two entries, then ours (label, type, range, xml)
table = e.new(500 * 28)
e.w32(TABLE_PTR, table)
label = e.new(16)
e.mu.mem_write(label, b"Compressor:\0")
e.call(SYM["bb_register"], table, 0xB4, 4, label, stack=(0, 1, 0))


def entry(pid):
    raw = bytes(e.mu.mem_read(table + 28 * pid, 28))
    pid2, typ = struct.unpack_from("<HB", raw)
    words = struct.unpack_from("<6I", raw, 4)
    return pid2, typ, words


pid, typ, w = entry(0xB4)
check("Compressor is a 7-entry list (blackbox-mod)", pid == 0xB4 and typ == 5 and w[2] == 7, (pid, typ, w))
pid, typ, w = entry(0x1E8)
check("Dist Type: list of 5, xml pkdtype", pid == 0x1E8 and typ == 5 and e.cstr(w[0]) == "Dist Type:" and w[2] == 5
      and [e.cstr(e.r32(w[1] + 4 * k)) for k in range(5)] == ["Off", "Soft", "Hard", "Fold", "Tube"]
      and e.cstr(w[5]) == "pkdtype", (pid, typ, w))
for pid, typ, lab, lo, hi, xml in ((0x1E9, 7, "Drive:", 0, 36000, "pkddrive"), (0x1EA, 8, "Tone:", 0, 1000, "pkdtone"),
                                   (0x1EB, 8, "Mix:", 0, 1000, "pkdmix"), (0x1EC, 7, "Level:", -24000, 12000, "pkdlevel")):
    p2, t2, w = entry(pid)
    ok = (p2, t2, e.cstr(w[0]), w[3] if w[3] < 1 << 31 else w[3] - (1 << 32), w[4], e.cstr(w[5])) == (pid, typ, lab, lo, hi, xml)
    check(f"{lab} registered (type {typ}, {lo}..{hi}, {xml})", ok, (p2, t2, w))

# --- Tools tab and pages
check("Tools page 4 = the distortion ids, then FX3", struct.unpack_from("<6H", IMG, 0x080EEE38 - BASE) == (0x1E8, 0x1E9, 0x1EA, 0x1EB, 0x1EC, 0x1B8))
check("Tools tab 4 named Extra", e.cstr(struct.unpack_from("<I", IMG, 0x080EEE90 - BASE)[0]) == "Extra")
check("both page builders accept page 4", IMG[0x080996D2 - BASE:0x080996D4 - BASE] == b"\x04\x2e"
      and IMG[0x08098D5A - BASE:0x08098D5C - BASE] == b"\x04\x2e")
check("version string 3.1.n+pk3 at all four users",
      all(e.cstr(struct.unpack_from("<I", IMG, a - BASE)[0]) == "3.1.n+pk3" for a in (0x0809AF30, 0x080AEAF4, 0x080C55E8, 0x080C72C8)))


# --- DSP: bus 0 through master_dist, compared with the micro's
def setv(name, v):
    for k in range(cnt):
        if struct.unpack_from("<H", e.mu.mem_read(ents + 8 * k, 2))[0] == IDS[name]:
            e.w32(ents + 8 * k + 4, v)
            return
    raise KeyError(name)


busL, busR = e.new(4 * 512), e.new(4 * 512)
bus = e.new(0x14)


def bb_run(left, right, settings):
    e.w32(0x38000000, 0)                                  # fresh state
    for k, v in settings.items():
        setv(k, v)
    out_l, out_r = [], []
    for b in range(0, len(left) - N + 1, N):
        e.mu.mem_write(bus, struct.pack("<IIIIBB2x", 512, N, busL, busR, 0, 1))
        e.wf(busL, left[b:b + N])
        e.wf(busR, right[b:b + N])
        e.call(SYM["master_dist"], bus)
        out_l += e.rf(busL, N)
        out_r += e.rf(busR, N)
    return out_l, out_r


sig_l = [0.5 * math.sin(2 * math.pi * 220 * k / 48000) + 0.2 * math.sin(2 * math.pi * 3100 * k / 48000) for k in range(N * 24)]
sig_r = [0.4 * math.sin(2 * math.pi * 330 * k / 48000 + 1.0) for k in range(N * 24)]

_src = open(os.path.join(HERE, "render_master.py")).read()
ns = {"__file__": os.path.join(HERE, "render_master.py"), "__name__": "render_master"}
exec(compile(_src, "render_master.py", "exec"), ns)


def micro_run(left, right, settings):
    m = ns["Master"]()
    s = dict(ns["NEUTRAL"])
    s.update(settings)
    m.set(**s)
    return m.run(left, right)


for typ, name in ((1, "Soft"), (2, "Hard"), (3, "Fold"), (4, "Tube")):
    s = dict(dtype=typ, drive=18000, tone=1000, mix=700, level=-6000)
    bl_, br_ = bb_run(sig_l, sig_r, s)
    ml, mr = micro_run(sig_l, sig_r, s)
    err = max(max(abs(a - b) for a, b in zip(bl_, ml)), max(abs(a - b) for a, b in zip(br_, mr)))
    check(f"{name}: Blackbox output = micro output (max diff {err:.2e})", err < 1e-6, err)

off_l, off_r = bb_run(sig_l, sig_r, dict(dtype=0))
check("Off: bus untouched", off_l == [struct.unpack("<f", struct.pack("<f", x))[0] for x in sig_l[:len(off_l)]])

# Tone: 0 % (200 Hz) takes the 3.1 kHz partial down against 100 %
def band(x, hz):
    re_ = sum(v * math.cos(2 * math.pi * hz * k / 48000) for k, v in enumerate(x))
    im_ = sum(v * math.sin(2 * math.pi * hz * k / 48000) for k, v in enumerate(x))
    return math.hypot(re_, im_) / len(x)


open_l, _ = bb_run(sig_l, sig_r, dict(dtype=1, drive=6000, tone=1000, mix=1000, level=0))
dark_l, _ = bb_run(sig_l, sig_r, dict(dtype=1, drive=6000, tone=0, mix=1000, level=0))
a_open, a_dark = band(open_l[N * 4:], 3100), band(dark_l[N * 4:], 3100)
check(f"Tone 0 %: 3.1 kHz {20 * math.log10(a_dark / a_open):.1f} dB vs open", a_dark < a_open * 0.2, (a_open, a_dark))
peak = max(abs(x) for x in open_l)
check(f"Soft +6 dB: bounded (peak {peak:.3f})", peak < 1.05)

print("all ok" if failures == 0 else f"{failures} FAILED")
sys.exit(1 if failures else 0)
