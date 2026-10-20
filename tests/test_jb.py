"""Unicorn tests for portkit merged into JOEBOX 1 (bb/joebox; out/bb/jb/release/BLACKBOX.bin + bank 2).

Real firmware and JOEBOX code runs for: the whole parameter registration 0x0808c158 (stock + JOEBOX + ours), the
global settings init 0x0809481c and the pad record init by type 0x08094a1c (JOEBOX's capacities), store get / set,
the stream read 0x08063634 on an in-memory stream, the stock plate init 0x08074d1c and core 0x08074f50 (bank 2 calls
it), the buffer accessors, the send curve. b2_live (JOEBOX cpu.c: is bank 2 this build's payload) is stubbed: true,
and false for the bypass checks. Distortion and SSL output compared with the bitbox micro's (PORTKIT_MICRO, see below).

  python3 -I tests/test_jb.py        (after python3 bb/joebox/build.py)
"""
import math
import os
import struct
import sys

os.environ["PK_BB"] = "jb"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,  # noqa: E402
                               UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_S0, UC_ARM_REG_S15, UC_ARM_REG_SP)

from bb_emu import APP_PADS, BASE, IMG, SETTINGS, SYM, BBEmu, bl_target, check, done  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bb", "joebox", "patches"))
import pk  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "bb", "joebox"))
import features  # noqa: E402
GROUPS_ALL = features.resolve(features.default())

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bb", "joebox"))
import ids  # noqa: E402
I = ids.ident
P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE, P_FX3SEND = (I(n) for n in ("SHIFT", "PLAYLEN", "STRETCH", "SMODE",
                                                                              "LFADE", "FX3SEND"))
G = dict(dtype=I("D_TYPE"), drive=I("D_DRIVE"), tone=I("D_TONE"), mix=I("D_MIX"), level=I("D_LEVEL"),
         rtype=I("R_TYPE"), decay=I("R_DECAY"), damp=I("R_DAMP"), predly=I("R_PREDLY"), size=I("R_SIZE"),
         rlevel=I("R_LEVEL"))
STORE_SET = 0x08093ECC
N = 128

e = BBEmu()
e.mu.mem_map(0xC0000000, 0x400000)                           # SDRAM pool for JOEBOX's allocations
e.mu.mem_map(0x20000000, 0x20000)                            # DTCM
e.mu.mem_map(0x38800000, 0x1000)                             # backup SRAM (JOEBOX's bank 2 marks)
sd = [0xC0000000]


def sdram(uc):
    n = uc.reg_read(UC_ARM_REG_R0) * max(1, uc.reg_read(UC_ARM_REG_R1))
    p = sd[0]
    sd[0] += (n + 15) & ~15
    uc.mem_write(p, bytes(min(n, 0x100000)))
    uc.reg_write(UC_ARM_REG_R0, p)


e.stub(0x0804436C, sdram)
e.stub(0x080443A8, lambda uc: (uc.reg_write(UC_ARM_REG_R1, 1), sdram(uc)))
live = [1]
e.stub(SYM["b2_live"], lambda uc: uc.reg_write(UC_ARM_REG_R0, live[0]))

# --- sites
bad = [hex(at) for at, name in pk.branches(GROUPS_ALL) if bl_target(IMG[at - BASE:at - BASE + 4], at) != SYM[name] & ~1]
check(f"{len(pk.branches(GROUPS_ALL))} call sites lead to portkit's code", not bad, bad)
bad = [hex(at) for at, name in pk.pointers(GROUPS_ALL) if struct.unpack_from("<I", IMG, at - BASE)[0] != SYM[name]]
check("Sync beats table and Tools tab name point at ours", not bad, bad)
check("bank 2 holds portkit's DSP", all(0x08100000 <= SYM[s] < 0x081E0000 for s in ("pk_wsola", "pk_dist_bus",
                                                                                  "pk_fx_block", "pk_ssl_run", "pk_loop_fade")))
check("bank 1 holds the hooks", all(0x080F1E78 <= SYM[s] < 0x08100000 for s in ("bb_register", "pk_clip_entry",
                                                                             "fx3_master", "master_dist")))
check("image ends below bank 2", BASE + len(IMG) <= 0x08100000, hex(BASE + len(IMG)))

# --- the whole registration: stock + JOEBOX + ours
e.call(0x0808C158)
table = e.r32(0x2401F4FC)
check(f"parameter table grown to {ids.TABLE_SLOTS} slots (allocation, clear, bounds)",
      all(e.r16(table + 28 * p) == p for p in (P_SHIFT, G["rlevel"])) and sd[0] - table >= 28 * ids.TABLE_SLOTS)


def entry(pid):
    raw = bytes(e.mu.mem_read(table + 28 * pid, 28))
    return struct.unpack_from("<HB", raw) + struct.unpack_from("<6I", raw, 4)


ours = {G["dtype"]: (5, "Dist Type:"), G["drive"]: (7, "Drive:"), G["rtype"]: (5, "FX3 Type:"),
        G["decay"]: (8, "FX3 Decay:"), G["rlevel"]: (8, "FX3 Level:"), P_SHIFT: (1, "Shift ms:"),
        P_PLAYLEN: (5, "Play Len:"), P_STRETCH: (1, "Stretch %:"), P_SMODE: (5, "Str Mode:"),
        P_LFADE: (1, "Loop Fade:"), P_FX3SEND: (8, "FX3 Send:")}
got = {pid: (entry(pid)[1], e.cstr(entry(pid)[2])) for pid in ours}
check("our parameters registered (type, label)", got == ours, got)
rng = {pid: (struct.unpack("<i", struct.pack("<I", entry(pid)[5]))[0], entry(pid)[6])
       for pid in (G["drive"], G["level"], P_SHIFT, P_STRETCH, P_LFADE, P_FX3SEND)}
check("ranges: Drive 0..36000, Level -24000..12000, Shift / Stretch -100..100, Loop Fade 0..50, FX3 Send 0..1000",
      rng == {G["drive"]: (0, 36000), G["level"]: (-24000, 12000), P_SHIFT: (-100, 100), P_STRETCH: (-100, 100),
              P_LFADE: (0, 50), P_FX3SEND: (0, 1000)}, rng)
jb = {0x1DB: "Master FX:", 0x1B6: "Insert:", 0x1C7: "Input:", 0x1D0: None, 0x94: "Sync:"}
gotjb = {pid: e.cstr(entry(pid)[2]) for pid in jb}
check("JOEBOX's own entries still there (Master FX, Insert, Input, Comp Thresh) and Sync has 8 names",
      gotjb[0x1DB] == "Master FX:" and gotjb[0x1B6] == "Insert:" and gotjb[0x1C7] == "Input:" and entry(0x1D0)[0] == 0x1D0
      and entry(0x94)[4] == 8 and e.cstr(e.r32(entry(0x94)[3] + 28)) == "1/32", gotjb)
pl = entry(P_PLAYLEN)
names = [e.cstr(e.r32(pl[3] + 4 * k)) for k in range(pl[4])]
check("Play Len: 129 names made at boot: Full, 1/4, 1/2, 3/4, 1, 1 1/4 .. 12 3/4 .. 32",
      len(names) == 129 and names[:6] == ["Full", "1/4", "1/2", "3/4", "1", "1 1/4"] and names[51] == "12 3/4"
      and names[128] == "32", names[:6] + names[50:52] + names[-1:])

# --- global settings: stock + JOEBOX + ours, within JOEBOX's 96
st = e.new(0x20)
e.call(0x0809481C, st)
cnt, cap, ents = e.r16(st + 0xA), e.r16(st + 0xC), e.r32(st + 4)
gl = {e.r16(ents + 8 * k): e.r32(ents + 8 * k + 4) for k in range(cnt)}
want = {G["dtype"]: 0, G["drive"]: 12000, G["tone"]: 1000, G["mix"]: 1000, G["level"]: 0, G["rtype"]: 0,
        G["decay"]: 600, G["damp"]: 500, G["predly"]: 0, G["size"]: 500, G["rlevel"]: 500}
check(f"global settings: {cnt} of {cap} entries, ours with their defaults, JOEBOX's Master FX there",
      cnt <= cap and cap == 96 and all(gl.get(k) == v for k, v in want.items()) and 0x1DB in gl, (cnt, cap))


def settings_store():
    """the app's settings store at SETTINGS, initialised by the real init"""
    e.call(0x0809481C, SETTINGS)


settings_store()


def setg(name, v):
    e.call(STORE_SET, SETTINGS, G[name], v & 0xFFFFFFFF)


# --- pad records (type 3 = full clip record): ours after FX2 Send, within 96
def record(row, col):
    return APP_PADS + row * 0xF0 + col * 0x30


t3 = e.new(4)
e.mu.mem_write(t3, b"\x03")
for row in range(4):
    for col in range(4):
        e.call(0x08094A1C, record(row, col), t3)
cnt, cap, ents = e.r16(record(1, 2) + 0xA), e.r16(record(1, 2) + 0xC), e.r32(record(1, 2) + 4)
ids = [e.r16(ents + 8 * k) for k in range(cnt)]
k = ids.index(0xDA)
check(f"clip pad record: {cnt} of {cap} entries, ours right after FX2 Send, all 0",
      cnt <= cap and ids[k + 1:k + 7] == [P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE, P_FX3SEND]
      and all(e.r32(ents + 8 * (k + 1 + i) + 4) == 0 for i in range(6)), (cnt, cap))


def set_param(pid, v, row=1, col=2):
    e.call(STORE_SET, record(row, col), pid, v & 0xFFFFFFFF)


def engine_pad(row=1, col=2):
    p = e.new(0x700)
    e.w32(p + 0x18, row << 8 | col)
    return p


# --- Shift through the read thunks, real stream read on an in-memory stream (value = index)
stream = e.new(0x40)
plane = e.new(4 * 1000)
e.wf(plane, [float(i) for i in range(1000)])
e.w32(stream + 4, plane)
e.w32(stream + 8, plane)
e.w32(stream + 0x10, 1000)
cpad = engine_pad()


def clip_read(pos, n=64):
    dst = e.new(4 * n)
    e.call(SYM["clip_read1_thunk"], stream, dst, n, pos, stack=(0,), regs=[(UC_ARM_REG_R5, cpad)])
    return [int(v) for v in e.rf(dst, n)]


set_param(P_SHIFT, 10)
check("Shift +10 ms: reads 480 frames later, wraps at the file end",
      clip_read(0) == list(range(480, 544)) and clip_read(500) == list(range(980, 1000)) + list(range(0, 44)))
set_param(P_SHIFT, 0)
check("Shift 0: as stock", clip_read(100) == list(range(100, 164)))

# Loop Fade (bank 2), and without bank 2: no fade, no fault
plane2 = e.new(4 * 2000)
e.wf(plane2, [1.0] * 2000)
e.w32(stream + 4, plane2)
e.w32(stream + 8, plane2)
e.w32(stream + 0x10, 2000)
set_param(P_LFADE, 10)
dst = e.new(4 * 2000)
e.call(SYM["clip_read1_thunk"], stream, dst, 2000, 0, stack=(0,), regs=[(UC_ARM_REG_R5, cpad)])
g = e.rf(dst, 2000)
live[0] = 0
e.call(SYM["clip_read1_thunk"], stream, dst, 2000, 0, stack=(0,), regs=[(UC_ARM_REG_R5, cpad)])
g0 = e.rf(dst, 2000)
live[0] = 1
check("Loop Fade 10 ms (bank 2): 0 at the start, 1 after 480 frames, ~0 at the end; without bank 2: untouched",
      g[0] == 0.0 and abs(g[479] - 1.0) < 0.01 and g[1000] == 1.0 and g[1999] < 0.01 and g0 == [1.0] * 2000)
set_param(P_LFADE, 0)
e.w32(stream + 4, plane)
e.w32(stream + 8, plane)
e.w32(stream + 0x10, 1000)


# Play Len / Stretch thunks (Blackbox registers)
def segments(q, count, unit, stretch=0, which="clip_segments12"):
    set_param(P_STRETCH, stretch)
    p = engine_pad()
    e.w32(p + 0x240, count)
    e.w32(p + 0x220, unit)
    e.mu.mem_write(p + 0x1F5, b"\x01")
    set_param(P_PLAYLEN, q)
    e.call(SYM[which], 0x11, 0x22, 0x33, 0x44, regs=[(UC_ARM_REG_R6, p)])
    r = e.regs(UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    set_param(P_PLAYLEN, 0)
    set_param(P_STRETCH, 0)
    return ((r[1] + r[2]) if which == "clip_segments12" else (r[2] + r[3])) & 0xFFFFFFFF


check("Play Len 1 bar at Sync 1/4: 4 (both sites); Full: 16; Stretch +100 %: 8",
      segments(4, 16, 960) == 4 and segments(4, 16, 960, which="clip_segments23") == 4 and segments(0, 16, 960) == 16
      and segments(0, 16, 960, stretch=100) == 8)
set_param(P_STRETCH, 100)
p = engine_pad()
e.wf(p + 0x1FC, [1000.0])
e.call(SYM["clip_seglen_thunk"], regs=[(UC_ARM_REG_R4, p)])
s15 = struct.unpack("<f", struct.pack("<I", e.mu.reg_read(UC_ARM_REG_S15)))[0]
set_param(P_STRETCH, 0)
check("Stretch +100 %: segment length x 2 (s15)", s15 == 2000.0, s15)

# --- pk_clip_entry: Smooth -> pk_clip_render, otherwise JOEBOX's clip_read_b, registers and stack as at the call
seen = []
e.stub(SYM["clip_read_b"], lambda uc: seen.append(("jb", uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R2),
                                                    e.r32(uc.reg_read(UC_ARM_REG_SP)))))
e.stub(SYM["pk_clip_render"], lambda uc: seen.append(("pk", uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R2),
                                                       e.r32(uc.reg_read(UC_ARM_REG_SP)))))
sp_ = engine_pad()
e.mu.mem_write(sp_ + 0x1F5, b"\x01")
e.wf(sp_ + 0x1FC, [24000.0])
e.wf(sp_ + 0x204, [24000.0])
src_buf = e.new(0x14)
e.w32(src_buf, 512)
frac = sp_ + 0x30 + 0x1C


def entry_call(mode):
    set_param(P_SMODE, mode)
    seen.clear()
    e.call(SYM["pk_clip_entry"], sp_, 0, 0x1234, 0, stack=(128, 0, frac, src_buf, 0, 0),
           regs=[(UC_ARM_REG_S0, 0x3F800000)])
    return seen[:]


jump, smooth = entry_call(1), entry_call(2)
live[0] = 0
smooth_dead = entry_call(2)
live[0] = 1
set_param(P_SMODE, 0)
check("clip reader call: Jump -> clip_read_b, Smooth -> pk_clip_render, Smooth without bank 2 -> clip_read_b; "
      "pad, position and the stack arguments passed on",
      jump == [("jb", sp_, 0x1234, 128)] and smooth == [("pk", sp_, 0x1234, 128)] and smooth_dead[0][0] == "jb",
      (jump, smooth, smooth_dead))
e.unstub(SYM["clip_read_b"])
e.unstub(SYM["pk_clip_render"])

# --- distortion: bank 2's output = the micro's, for every type; without bank 2 the bus is untouched
busL, busR, bus = e.new(4 * 512), e.new(4 * 512), e.new(0x14)


def dist_run(left, right, settings):
    e.w32(0x38000000, 0)
    for k_, v in settings.items():
        setg(k_, v)
    out_l, out_r = [], []
    for b in range(0, len(left) - N + 1, N):
        e.mu.mem_write(bus, struct.pack("<IIIIBB2x", 512, N, busL, busR, 0, 1))
        e.wf(busL, left[b:b + N])
        e.wf(busR, right[b:b + N])
        e.call(SYM["master_dist"], bus)
        out_l += e.rf(busL, N)
        out_r += e.rf(busR, N)
    return out_l, out_r


sig_l = [0.5 * math.sin(2 * math.pi * 220 * k / 48000) + 0.2 * math.sin(2 * math.pi * 3100 * k / 48000) for k in range(N * 16)]
sig_r = [0.4 * math.sin(2 * math.pi * 330 * k / 48000 + 1.0) for k in range(N * 16)]
# Reference: the bitbox micro's DSP, run in its patched image (portkit-micro's tests/render_master.py, which needs
# that project's firmware/MICRO.BIN and build). Set PORTKIT_MICRO=<portkit-micro checkout>; without it the
# comparisons with the micro are skipped and only the Blackbox side is checked.
_micro = os.environ.get("PORTKIT_MICRO")
ns = None
if _micro:
    _rm = os.path.join(_micro, "tests", "render_master.py")
    ns = {"__file__": _rm, "__name__": "render_master"}
    exec(compile(open(_rm).read(), _rm, "exec"), ns)
else:
    print("skip comparisons with the bitbox micro's DSP (set PORTKIT_MICRO to a built portkit-micro checkout)")
for typ, name in ((1, "Soft"), (2, "Hard"), (3, "Fold"), (4, "Tube")):
    s = dict(dtype=typ, drive=18000, tone=1000, mix=700, level=-6000)
    bl_, br_ = dist_run(sig_l, sig_r, s)
    check(f"Distortion {name} (bank 2): output finite and changed", all(math.isfinite(x) for x in bl_ + br_)
          and bl_ != sig_l)
    if not ns:
        continue
    m = ns["Master"]()
    ms = dict(ns["NEUTRAL"])
    ms.update(s)
    m.set(**ms)
    ml, mr = m.run(sig_l, sig_r)
    err = max(max(abs(a - b) for a, b in zip(bl_, ml)), max(abs(a - b) for a, b in zip(br_, mr)))
    check(f"Distortion {name} (bank 2) = the micro's master_dist (max diff {err:.1e})", err < 1e-6, err)
live[0] = 0
ul, _ = dist_run(sig_l, sig_r, dict(dtype=2, drive=18000))
live[0] = 1
check("Distortion without bank 2: bus untouched", ul == [struct.unpack("<f", struct.pack("<f", x))[0] for x in sig_l])
setg("dtype", 0)

# --- FX3: first block sets up the plate (as the stock init leaves it), sends add up, impulse -> tail
B0, L0, R0 = e.new(0x14), e.new(4 * N), e.new(4 * N)
F2, LF, RF = e.new(0x14), e.new(4 * N), e.new(4 * N)


def fill(b, L, R, vals, silent=0):
    e.wf(L, vals)
    e.wf(R, vals)
    e.mu.mem_write(b, struct.pack("<IIIIBB2x", N, N, L, R, silent, 1))


def master_block(fx2=0.0):
    fill(B0, L0, R0, [0.0] * N)
    fill(F2, LF, RF, [fx2] * N)
    e.call(SYM["fx3_master"], B0, F2)
    return e.rf(L0, N)


e.w32(0x38000E00, 0)
master_block()                                              # first block with bank 2: memory set up
stock = e.new(0xC0)
allocs = []
e.mu.mem_map(0x60000000, 0x40000)


def new(uc):
    n = uc.reg_read(UC_ARM_REG_R0)
    p_ = 0x60000000 + sum(m_ for _, m_ in allocs)
    allocs.append((p_, n))
    uc.reg_write(UC_ARM_REG_R0, p_)


e.stub(0x080443A8, new)
e.call(0x08074D1C, stock)
sw = struct.unpack("<44I", e.mu.mem_read(stock, 0xB0))
ow = struct.unpack("<44I", e.mu.mem_read(0x38001000, 0xB0))
bufw = [8, 11, 14, 17, 20, 25, 30, 33, 37, 39, 41, 43]
check("FX3 set up on the first block: plate words as the stock init, its 12 buffers packed in D2 SRAM, clocks on",
      e.r32(0x38000E00) == 0x46583342 and all(ow[k_] == sw[k_] for k_ in range(44) if k_ not in bufw)
      and [ow[k_] for k_ in bufw] == [0x30000000 + sum(n for _, n in allocs[:i]) for i in range(12)]
      and e.r32(0x580244DC) >> 29 == 7)

rec = record(1, 2)
set_param(P_FX3SEND, 1000)
pad = engine_pad()
S1, L1, R1 = e.new(0x14), e.new(4 * N), e.new(4 * N)
results = {}
for typ, name in ((0, "Plate"), (1, "Room"), (2, "Hall"), (3, "Chamber")):
    setg("rtype", typ)
    out = []
    for blk in range(100):
        if blk == 0:
            fill(S1, L1, R1, [1.0] + [0.0] * (N - 1))
            e.call(SYM["fx3_send_a"], 0, 0, 0, F2 + 0x10, stack=[0] * 6 + [S1], regs=[(UC_ARM_REG_R4, pad)])
        out += master_block(0.001)
    tail = [v - 0.001 for v in out]
    e1, e2 = sum(v * v for v in tail[:N * 30]), sum(v * v for v in tail[N * 70:])
    results[name] = (e1 > 1e-6 and e2 < e1 and all(math.isfinite(v) for v in tail) and max(map(abs, tail)) < 2.0)
check("FX3 send (thunk) -> reverb tail for Plate, Room, Hall, Chamber; FX2 return kept", all(results.values()), results)
live[0] = 0
fill(S1, L1, R1, [1.0] + [0.0] * (N - 1))
e.call(SYM["fx3_send_a"], 0, 0, 0, F2 + 0x10, stack=[0] * 6 + [S1], regs=[(UC_ARM_REG_R4, pad)])
dead = master_block(0.001)
live[0] = 1
check("FX3 without bank 2: only the FX2 return reaches bus 0", all(abs(v - 0.001) < 1e-9 for v in dead))

# --- SSL model: pk_ssl (bank 2) = the micro's SSL compressor, block by block; JOEBOX list has "SSL" appended
e.call(0x0808C158)                                          # registration again (the table was reused above)
table = e.r32(0x2401F4FC)
comp = entry(0xB4)
cnames = [e.cstr(e.r32(comp[3] + 4 * k)) for k in range(comp[4])]
check("Compressor list: JOEBOX's eight + SSL appended", cnames == ["Off", "Stock", "Glue", "Punch", "Opto", "Squash",
                                                                 "Limit", "Smash", "SSL"], cnames)
S = {k: I(v) for k, v in (("thresh", "S_THRESH"), ("ratio", "S_RATIO"), ("attack", "S_ATTACK"), ("rel", "S_REL"),
                          ("gain", "S_GAIN"), ("mix", "S_MIX"))}
SL, SR = e.new(4 * N), e.new(4 * N)
drums = [0.6 * math.sin(2 * math.pi * 110 * k / 48000) * (1.0 if (k // 6000) % 2 == 0 else 0.15) for k in range(N * 40)]
for ratio, attack, rel, mixv in ((0, 5, 4, 1000), (2, 0, 0, 1000), (1, 3, 4, 400)):
    for k_, v in (("thresh", -20000), ("ratio", ratio), ("attack", attack), ("rel", rel), ("gain", 3000), ("mix", mixv)):
        e.call(STORE_SET, SETTINGS, S[k_], v & 0xFFFFFFFF)
    e.w32(0x38001C40, 0)
    out = []
    for b in range(0, len(drums), N):
        e.wf(SL, drums[b:b + N])
        e.wf(SR, drums[b:b + N])
        e.call(SYM["pk_ssl"], SL, SR, N)
        out += e.rf(SL, N)
    check(f"SSL ratio {ratio} attack {attack} release {rel} mix {mixv}: output finite",
          all(math.isfinite(x) for x in out))
    if not ns:
        continue
    m = ns["Master"]()
    ms = dict(ns["NEUTRAL"])
    ms.update(ctype=1, thresh=-20000, sratio=ratio, sattack=attack, srelease=rel, gain=3000, cmix=mixv)
    m.set(**ms)
    ml, _ = m.run(drums, drums)
    err = max(abs(a - b) for a, b in zip(out, ml))
    check(f"SSL ratio {ratio} attack {attack} release {rel} mix {mixv}: = the micro's (max diff {err:.1e})", err < 1e-5, err)

# --- recording: the pad rebuilt during a recording keeps its sends
rec2 = e.new(0x30)
e.call(0x08094A1C, rec2, t3)
for pid, v in ((0xD9, 700), (0xDA, 300), (P_FX3SEND, 500), (0xC8, 123)):
    e.call(STORE_SET, rec2, pid, v)
e.call(SYM["rec_reinit"], rec2, t3)
got = {pid: e.r32(e.r32(rec2 + 4) + 8 * [e.r16(e.r32(rec2 + 4) + 8 * k) for k in range(e.r16(rec2 + 0xA))].index(pid) + 4)
       for pid in (0xD9, 0xDA, P_FX3SEND, 0xC8)}
check("recording rebuild: FX1/FX2/FX3 Send kept, other settings back to default",
      got[0xD9] == 700 and got[0xDA] == 300 and got[P_FX3SEND] == 500 and got[0xC8] != 123, got)

# --- Rec Input FX: list, the three thunks, the FX sum
ri = entry(0x9A)
rnames = [e.cstr(e.r32(ri[3] + 4 * k)) for k in range(ri[4])]
check("Rec Input: L+R, Left, Right, Resam + FX + USB", rnames == ["L+R", "Left", "Right", "Resam", "FX", "USB"], rnames)
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_R8, UC_ARM_REG_PC  # noqa: E402


def zflag(fn, **regs):
    e.call(SYM[fn], *[regs.get(r, 0) for r in ("r0", "r1", "r2", "r3")])
    return bool(e.mu.reg_read(UC_ARM_REG_CPSR) & (1 << 30))


check("record start: stereo for L+R, Resam, FX and USB, mono for Left / Right",
      [zflag("rec_stereo_thunk", r0=v) for v in range(6)] == [True, False, False, True, True, True])
from bb_emu import RET  # noqa: E402
from unicorn import UC_HOOK_CODE  # noqa: E402
skipped = []
e.mu.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: (skipped.append(1), uc.emu_stop()), begin=RET + 8, end=RET + 8)
mon = []
for v in range(6):
    skipped.clear()
    e.call(SYM["rec_mon_thunk"], 0, 0, 0, v)
    mon.append(bool(skipped))
check("input monitor skipped (return + 8) for Resam, FX and USB only", mon == [False, False, False, True, True, True], mon)
taps = []
e.stub(0x0806277E, lambda uc: taps.append("stock"))
dst = e.new(0x14)
dl, dr = e.new(4 * N), e.new(4 * N)
e.mu.mem_write(dst, struct.pack("<IIIIBB2x", N, N, dl, dr, 1, 0))
for v in (0, 3, 4):
    e.call(SYM["rec_src_thunk"], 0, 0, 0, v, regs=[(UC_ARM_REG_R8, dst)])
e.unstub(0x0806277E)
# FX sum: FX1 return 0.25, FX2 return 0.5 through fx3_master (FX3 silent)
A, LA, RA = e.new(0x28), e.new(4 * N), e.new(4 * N)      # bus 0xa and 0xb, 20 bytes each
F2b, LB, RB = A + 20, e.new(4 * N), e.new(4 * N)
fill(A, LA, RA, [0.25] * N)
fill(F2b, LB, RB, [0.5] * N)
fill(B0, L0, R0, [0.0] * N)
e.mu.mem_write(0x38000E00, bytes(4))      # FX3 state cleared: its tail from the tests above stays out
e.call(SYM["fx3_master"], B0, F2b)
e.call(SYM["rec_src_thunk"], 0, 0, 0, 4, regs=[(UC_ARM_REG_R8, dst)])
fxl = e.rf(dl, 4)
check("record source: Resam -> stock tap, FX -> FX1 + FX2 (+ FX3) copied into the record buffer, L+R untouched",
      taps == ["stock"] and all(abs(x - 0.75) < 1e-6 for x in fxl), (taps, fxl))

# --- Rec Input USB: endpoint 3 (JOEBOX usbdev.c's hooks -> bank 1 usbin_* -> bank 2), the ring, the rate-matched reader
import math  # noqa: E402
from unicorn import UC_HOOK_MEM_READ  # noqa: E402
try:
    e.mu.mem_map(0x40040000, 0x4000)                     # OTG_HS registers and its FIFO window
except Exception:
    pass
OTG, UI, RING_A, BUF = 0x40040000, 0x38003F00, 0x38004000, 0x38006400
fifo = []


def fifo_read(uc, access, addr, size, value, data):
    uc.mem_write(OTG + 0x1000, struct.pack("<I", fifo.pop(0) if fifo else 0xDEADBEEF))


e.mu.hook_add(UC_HOOK_MEM_READ, fifo_read, begin=OTG + 0x1000, end=OTG + 0x1003)


def packet(frames):
    """[(l, r) 24-bit ints] -> (FIFO words, byte count)"""
    raw = b"".join(struct.pack("<i", l)[:3] + struct.pack("<i", r)[:3] for l, r in frames)
    n = len(raw)
    raw += bytes((-n) % 4)
    return list(struct.unpack(f"<{len(raw) // 4}I", raw)), n


def rx(frames):
    words, n = packet(frames)
    fifo[:] = words
    e.call(SYM["usbin_rx"], n)
    return not fifo                                      # every word of the packet read out


def ring_at(k):
    return struct.unpack("<ii", bytes(e.mu.mem_read(RING_A + 8 * (k % 1024), 8)))


e.call(SYM["usbin_reset"])
check("USB in: closed after core_setup", e.r32(UI) == 0)
live[0] = 0
e.call(SYM["usbin_open"], 1)
check("USB in: without bank 2 the stream does not open", e.r32(UI) == 0)
live[0] = 1
e.w32(OTG + 0x808, 0)                                   # DSTS: frame 0 now
e.call(SYM["usbin_open"], 1)
ctl, tsiz = e.r32(OTG + 0xB60), e.r32(OTG + 0xB70)
check("USB in: open = endpoint 3 active, isochronous, 294 bytes, armed for the next (odd) frame",
      e.r32(UI) == 0x55534231 and ctl & 0x7FF == 294 and ctl & (1 << 15) and (ctl >> 18) & 3 == 1
      and ctl & (1 << 31) and ctl & (1 << 29) and tsiz == (1 << 19) | 294, (hex(ctl), hex(tsiz)))
r0 = e.call(SYM["usbin_alt"])
check("USB in: GET_INTERFACE answers alt 1", e.mu.reg_read(UC_ARM_REG_R0) == 1)
pkt = [(k * 1000 - 24000, -k * 777 + 8388607 * (k == 47)) for k in range(48)]
ok = rx(pkt)
check("USB in: a 48-frame packet: all 72 words read, 48 frames in the ring (24 bit, sign kept)",
      ok and e.r32(UI + 4) == 48 and [ring_at(k) for k in range(48)] == pkt, [ring_at(k) for k in (0, 1, 47)])
words, _ = packet(pkt[:10])
fifo[:] = words + [0]
e.call(SYM["usbin_rx"], 62)
check("USB in: a packet of an odd size: read out, counted bad, nothing written",
      not fifo and e.r32(UI + 12) == 1 and e.r32(UI + 4) == 48)
fifo[:] = []
e.w32(OTG + 0x808, 1 << 8)                              # frame 1: next is even
e.mu.mem_write(OTG + 0xB60, struct.pack("<I", 294 | (1 << 15) | (1 << 18)))
e.call(SYM["usbin_done"])
check("USB in: transfer done / frame missed -> armed again, for the next frame's parity (even)",
      e.r32(OTG + 0xB60) & (1 << 31) and e.r32(OTG + 0xB60) & (1 << 28), hex(e.r32(OTG + 0xB60)))
e.call(SYM["usbin_open"], 0)
check("USB in: closed: endpoint 3 inactive", e.r32(UI) == 0 and not e.r32(OTG + 0xB60) & (1 << 15))
check("USB in: closed: a packet is still read out of the FIFO, and dropped", rx(pkt) and e.r32(UI + 4) == 48)

# reader: what the recorder gets (rec_src_thunk with Rec Input 5 -> rec_usb_copy)
e.call(SYM["usbin_open"], 1)
SR, F0, AMP = 48000.0, 997.0, 0.5
src_n = [0]


def push(frames):
    """the computer sends `frames` more of a sine, in packets of up to 48"""
    while frames > 0:
        m = min(48, frames)
        fr = []
        for _ in range(m):
            v = int(round(AMP * math.sin(2 * math.pi * F0 * src_n[0] / SR) * 8388607))
            fr.append((v, -v))
            src_n[0] += 1
        rx(fr)
        frames -= m


def rec_block():
    """what the recorder's buffer holds after the source step: (silent, L, R)"""
    e.mu.mem_write(dst, struct.pack("<IIIIBB2x", N, N, dl, dr, 0, 1))
    e.wf(dl, [9.0] * N)
    e.wf(dr, [9.0] * N)
    e.call(SYM["rec_src_thunk"], 0, 0, 0, 5, regs=[(UC_ARM_REG_R8, dst)])
    l, r = e.rf(e.r32(dst + 8), N), e.rf(e.r32(dst + 12), N)
    quiet = e.mu.mem_read(dst + 16, 1)[0] == 1 or (max(map(abs, l)) == 0 and max(map(abs, r)) == 0)
    return int(quiet), l, r


push(300)
sil, _, _ = rec_block()
check("USB in: under 8 ms of fresh data: the recorder gets silence", sil == 1)
push(200)
sil, l, r = rec_block()
w = e.r32(UI + 4)
want = [AMP * math.sin(2 * math.pi * F0 * (w - 384 + k) / SR) for k in range(N)]
err = max(abs(a - b) for a, b in zip(l, want))
check(f"USB in: then it starts 384 frames behind the computer, sample for sample (max err {err:.1e}), R = -L",
      sil == 0 and err < 2e-7 and all(abs(a + b) < 1e-9 for a, b in zip(l, r)), err)
def drift(factor, blocks=7500):
    """the computer's clock off by `factor` for ~20 s: (silence seen, largest step, settled rate, fills, under, resync)"""
    acc, prev, worst, fills = 0.0, None, 0.0, []
    u0, s0 = e.r32(0x38006500 + 20), e.r32(0x38006500 + 24)
    for blk in range(blocks):
        acc += 128 * factor
        k = int(acc)
        acc -= k
        push(k)
        sil, l, r = rec_block()
        if sil:
            return True, worst, 0, fills, 0, 0
        seq = ([prev] if prev is not None else []) + l
        worst = max(worst, max(abs(seq[i + 1] - seq[i]) for i in range(len(seq) - 1)))
        prev = l[-1]
        if blk % 500 == 499:                            # the reader's smoothed fill (frames ahead before a block)
            fills.append(round(struct.unpack("<f", bytes(e.mu.mem_read(0x38006500 + 16, 4)))[0]))
    ratio = struct.unpack("<f", struct.pack("<I", e.r32(0x38006500 + 12)))[0]
    return False, worst, ratio, fills, e.r32(0x38006500 + 20) - u0, e.r32(0x38006500 + 24) - s0


slope = 2 * math.pi * F0 / SR * AMP
for factor in (1.001, 0.999):
    e.call(SYM["usbin_open"], 0)                        # a fresh stream for each computer (its clock does not jump)
    e.call(SYM["usbin_open"], 1)
    push(500)
    rec_block()
    sil, worst, ratio, fills, under, resync = drift(factor, 15000)
    check(f"USB in: computer's clock {factor - 1:+.1%} over 40 s: no gap, no jump (largest step {worst:.4f}, a sine "
          f"step at most {slope:.4f}), rate {ratio:.5f}, buffer back at {fills[-1] if fills else '-'} of 384 frames "
          f"(lowest {min(fills) if fills else '-'})",
          not sil and worst < slope * 1.05 and abs(ratio - factor) < 0.0002 and under == 0 and resync == 0
          and abs(fills[-1] - 384) < 30 and min(fills) > 200, (worst, ratio, under, resync, fills))
# the computer stops: what is buffered (~9 ms) plays out, then silence, and the old ring is never played again
played = 0
while played < 8 and not rec_block()[0]:
    played += 1
sil1, _, _ = rec_block()
sil2, _, _ = rec_block()
push(200)
sil3, _, _ = rec_block()
push(250)
sil4, l, _ = rec_block()
check(f"USB in: the computer stops -> its last {played} blocks play out, then silence (not the old ring again); "
      "back: silence until 8 ms are new, then sound",
      played <= 4 and (sil1, sil2, sil3, sil4) == (1, 1, 1, 0) and max(abs(x) for x in l) > 0.3,
      (played, sil1, sil2, sil3, sil4))
e.call(SYM["usbin_open"], 0)
sil5, _, _ = rec_block()
check("USB in: stream closed -> Rec Input USB records silence", sil5 == 1)

done()
