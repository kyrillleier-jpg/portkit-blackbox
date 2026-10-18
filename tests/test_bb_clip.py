"""Unicorn tests for the Blackbox clip functions (bb/src/clip.c, bb/src/clip_thunk.S, bb/src/stretch.c) on
out/bb/master+clip/BLACKBOX.bin. Ported from tests/test_fidelity.py's clip tests (Bitbox micro), with the Blackbox's
registers at the thunk sites.

Real firmware code runs for: the pad record init by type (0x08094a1c -> 0x08093f20, type 3 = full clip record, with
our pad_store_add hooks and the raised capacity), the store get / set, the stream read 0x08063634 on an in-memory stream, the clip parameter
handler 0x08067648 for Sync (ticks from the beats table).

  python3 -I tests/test_bb_clip.py        (after bb/build.py and bb/patch.py master clip)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
                               UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_S15, UC_ARM_REG_SP)

from bb_emu import APP_PADS, BASE, IMG, SYM, BBEmu, bl_target, check, done  # noqa: E402

P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE = 0x1ED, 0x1EE, 0x1EF, 0x1F0, 0x1F1
STORE_SET = 0x08093ECC
STORE_INIT = 0x08094A1C

e = BBEmu()

# --- hook sites
SITES = {0x08094112: "pad_store_add", 0x08094346: "pad_store_add", 0x0808D104: "sync_register",
         0x08066622: "clip_render", 0x0806636E: "clip_read1_thunk", 0x0806644E: "clip_read1_thunk",
         0x080663BA: "clip_read2_thunk", 0x0806642C: "clip_read2_thunk", 0x0806541A: "clip_seek_thunk",
         0x0806578C: "clip_seek_thunk", 0x08066E7A: "clip_segments12", 0x08066C46: "clip_segments23",
         0x0806560C: "clip_seglen_thunk", 0x080655FE: "clip_last_thunk"}
bad = [hex(a) for a, n in SITES.items() if bl_target(IMG[a - BASE:a - BASE + 4], a) != SYM[n] & ~1]
check(f"{len(SITES)} call sites lead to the clip code", not bad, bad)


# --- pad records: real init by type (0x45 grid pads at boot, 3 = full clip record)
def record(row, col):
    return APP_PADS + row * 0xF0 + col * 0x30


def init_record(rec, typ):
    t = e.new(4)
    e.mu.mem_write(t, bytes([typ]))
    e.call(STORE_INIT, rec, t)


def store_ids(rec):
    cnt, cap, ent = e.r16(rec + 0xA), e.r16(rec + 0xC), e.r32(rec + 4)
    return {e.r16(ent + 8 * k): e.r32(ent + 8 * k + 4) for k in range(cnt)}, cnt, cap


for row in range(4):
    for col in range(4):
        init_record(record(row, col), 3)
rec3 = record(1, 2)
ids3, cnt3, cap3 = store_ids(rec3)
NEW = (P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE)
ids_list = list(ids3)
k = ids_list.index(0xDA) if 0xDA in ids_list else -1
check("clip record (type 3): Shift, Play Len, Stretch, Str Mode, Loop Fade = 0, right after FX2 Send (0xda)",
      all(ids3.get(p) == 0 for p in NEW) and ids_list[k + 1:k + 6] == list(NEW), ids_list)
check(f"clip record (type 3): {cnt3} entries (59 stock + 5 clip + FX3 Send), capacity raised to 72", cnt3 == 65 and cap3 == 72
      and ids3.get(0x1F2) == 0,
      (cnt3, cap3))


def set_param(pid, v, row=1, col=2):
    e.call(STORE_SET, record(row, col), pid, v)


def engine_pad(row=1, col=2):
    p = e.new(0x700)
    e.w32(p + 0x18, row << 8 | col)
    return p


# --- Shift: the clip reader's stream calls, real 0x08063634 on an in-memory stream (1000 frames, value = index)
stream = e.new(0x40)
plane = e.new(4 * 1000)
e.wf(plane, [float(i) for i in range(1000)])
e.w32(stream + 4, plane)
e.w32(stream + 8, plane)
e.w32(stream + 0x10, 1000)
cpad = engine_pad()


def clip_read(pos, n=64, pad_=None):
    dst = e.new(4 * n)
    e.call(SYM["clip_read1_thunk"], stream, dst, n, pos, stack=(0,), regs=[(UC_ARM_REG_R5, cpad if pad_ is None else pad_)])
    return [int(v) for v in e.rf(dst, n)]


def clip_read2_calls(pos, n=64):
    """the stock two-plane reads clip_read2 makes, as (n, pos) (0x08063608 only reads streamed files: stubbed)"""
    calls = []

    def rec(uc):
        sp = uc.reg_read(UC_ARM_REG_SP)
        calls.append((uc.reg_read(UC_ARM_REG_R3), e.r32(sp)))
        uc.reg_write(UC_ARM_REG_R0, 1)
    e.stub(0x08063608, rec)
    l_, r_ = e.new(4 * n), e.new(4 * n)
    e.call(SYM["clip_read2_thunk"], stream, l_, r_, n, stack=(pos,), regs=[(UC_ARM_REG_R5, cpad)])
    e.unstub(0x08063608)
    return calls


def stock_read(pos, n=64):
    dst = e.new(4 * n)
    e.call(0x08063634, stream, dst, n, pos, stack=(0,))
    return [int(v) for v in e.rf(dst, n)]


set_param(P_SHIFT, 0)
check("Shift 0: clip read identical to stock", clip_read(100) == stock_read(100) == list(range(100, 164)))
set_param(P_SHIFT, 10)
check("Shift +10 ms: reads 480 frames later", clip_read(0) == list(range(480, 544)))
check("Shift +10 ms: wraps at the file end (seamless)", clip_read(500) == list(range(980, 1000)) + list(range(0, 44)))
check("Shift +10 ms: past the end stays silent as stock", clip_read(990, 20) == list(range(470, 480)) + [0] * 10)
calls = clip_read2_calls(500)
check("Shift +10 ms, both planes: stock read split at the file end (20 frames at 980, 44 at 0)",
      calls == [(20, 980), (44, 0)], calls)
set_param(P_SHIFT, -10)
check("Shift -10 ms: downbeat reads the file's end", clip_read(0) == list(range(520, 584)))
sliced = engine_pad()
e.mu.mem_write(sliced + 0x254, b"\x01")
set_param(P_SHIFT, 10)
check("Shift on a sliced pad: ignored", clip_read(0, pad_=sliced) == list(range(0, 64)))
seeks = []
e.stub(0x0806375C, lambda uc: seeks.append(uc.reg_read(UC_ARM_REG_R1)))
e.call(SYM["clip_seek_thunk"], stream, 992, regs=[(UC_ARM_REG_R4, cpad)])
e.call(SYM["clip_seek_thunk"], stream, 100, regs=[(UC_ARM_REG_R4, cpad)])
e.unstub(0x0806375C)
check("Shift: segment prefetch seek follows (wrapped)", seeks == [472, 580], seeks)
set_param(P_SHIFT, 0)

# --- Loop Fade (clip): 10 ms = 480 frames dip at the file start / end (not synced: loop end = file end)
plane2 = e.new(4 * 2000)
e.wf(plane2, [1.0] * 2000)
e.w32(stream + 4, plane2)
e.w32(stream + 8, plane2)
e.w32(stream + 0x10, 2000)
set_param(P_LFADE, 10)
dst = e.new(4 * 2000)
e.call(SYM["clip_read1_thunk"], stream, dst, 2000, 0, stack=(0,), regs=[(UC_ARM_REG_R5, cpad)])
g = e.rf(dst, 2000)
check("Loop Fade 10 ms: 0 at the start, rising to 1 over 480 frames, 1 in the middle, falling to the end",
      g[0] == 0.0 and abs(g[479] - 1.0) < 0.01 and g[1000] == 1.0 and g[1999] < 0.01 and g[1520] > 0.99, (g[0], g[479], g[1999]))
set_param(P_LFADE, 0)
e.w32(stream + 4, plane)
e.w32(stream + 8, plane)
e.w32(stream + 0x10, 1000)


# --- Play Len: both loop tests, with the Blackbox's registers
def segments(q, count, extra, unit, synced=1, sliced_=0, stretch=0, which="clip_segments12"):
    set_param(P_STRETCH, stretch)
    p = engine_pad()
    e.w32(p + 0x240, count)
    e.w32(p + 0x244, extra)
    e.w32(p + 0x220, unit)
    e.w32(p + 0x224, 0)
    e.mu.mem_write(p + 0x1F5, bytes([synced]))
    e.mu.mem_write(p + 0x254, bytes([sliced_]))
    set_param(P_PLAYLEN, q)
    e.call(SYM[which], 0x11, 0x22, 0x33, 0x44, regs=[(UC_ARM_REG_R6, p)])
    r = e.regs(UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    set_param(P_PLAYLEN, 0)
    set_param(P_STRETCH, 0)
    if which == "clip_segments12":
        return (r[1] + r[2]) & 0xFFFFFFFF, r
    return (r[2] + r[3]) & 0xFFFFFFFF, r                       # `add r3, r2` at 0x08066c4a


n, r = segments(0, 16, 0, 960)
check("Play Len Full (r1/r2 site): count unchanged; r0 / r3 kept, r1 = +0x240", n == 16 and r[0] == 0x11 and r[3] == 0x44
      and r[1] == 16, r)
n, r = segments(0, 16, 0, 960, which="clip_segments23")
check("Play Len Full (r2/r3 site): count unchanged; r0 / r1 kept, r2 = +0x240", n == 16 and r[0] == 0x11 and r[1] == 0x22
      and r[2] == 16, r)
check("Play Len 1 bar at Sync 1/4: 4 segments; 1/4: 1; 2 3/4: 11 (both sites)",
      all(segments(4, 16, 0, 960, which=w)[0] == 4 and segments(1, 16, 0, 960, which=w)[0] == 1
          and segments(11, 16, 0, 960, which=w)[0] == 11 for w in ("clip_segments12", "clip_segments23")))
check("Play Len 1 bar at Sync 1/16 (64 segments): 16; at Sync 1 bar (4 segments): 1",
      segments(4, 64, 0, 240)[0] == 16 and segments(4, 4, 0, 3840)[0] == 1)
check("Play Len longer than the clip: full length; +0x244 part counted", segments(32, 16, 0, 960)[0] == 16
      and segments(4, 15, 1, 960)[0] == 4)
check("Stretch: loop bound 16 -> 8 at +100 %, 32 at -100 %, 11 at +50 %; with Play Len 1 bar: 4",
      segments(0, 16, 0, 960, stretch=100)[0] == 8 and segments(0, 16, 0, 960, stretch=-100)[0] == 32
      and segments(0, 16, 0, 960, stretch=50)[0] == 11 and segments(4, 16, 0, 960, stretch=-100)[0] == 4)
check("Play Len unchanged: sliced pad, not synced, Sync Slice",
      segments(4, 16, 0, 960, sliced_=1)[0] == 16 and segments(4, 16, 0, 960, synced=0)[0] == 16
      and segments(4, 16, 0, 0xF0000)[0] == 16)


def last_count(stretch, count=16):
    set_param(P_STRETCH, stretch)
    p = engine_pad()
    e.w32(p + 0x240, count)
    e.call(SYM["clip_last_thunk"], 0x11, 0x22, 0x33, 0x44, regs=[(UC_ARM_REG_R4, p)])
    r = e.regs(UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    set_param(P_STRETCH, 0)
    return r


check("Stretch: last-segment count in r2 = 16 / 8 / 32, r0 / r1 / r3 kept",
      last_count(0)[2] == 16 and last_count(100)[2] == 8 and last_count(-100) == [0x11, 0x22, 32, 0x44])


def seglen(stretch):
    set_param(P_STRETCH, stretch)
    p = engine_pad()
    e.wf(p + 0x1FC, [1000.0])
    e.call(SYM["clip_seglen_thunk"], 0x11, 0x22, 0x33, 0x44, regs=[(UC_ARM_REG_R4, p)])
    s15 = struct.unpack("<f", struct.pack("<I", e.mu.reg_read(UC_ARM_REG_S15)))[0]
    r = e.regs(UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    set_param(P_STRETCH, 0)
    return s15, r


check("Stretch: segment length (s15) x speed: 1000 / 2000 at +100 % / 500 at -100 %, r0-r3 kept",
      seglen(0)[0] == 1000.0 and seglen(100)[0] == 2000.0 and seglen(-100) == (500.0, [0x11, 0x22, 0x33, 0x44]))

# --- Sync 1/32
seen = {}



def grab(uc):
    sp = uc.reg_read(UC_ARM_REG_SP)
    seen.update(param=uc.reg_read(UC_ARM_REG_R1), label=e.cstr(uc.reg_read(UC_ARM_REG_R2)), names=uc.reg_read(UC_ARM_REG_R3),
                count=e.r32(sp), xml=e.cstr(e.r32(sp + 4)))


e.stub(0x0808C0D8, grab)
label, xml = e.new(16), e.new(16)
e.mu.mem_write(label, b"Sync:\0")
e.mu.mem_write(xml, b"synctype\0")
e.call(SYM["sync_register"], 0, 0x94, label, 0x080EC848, stack=(7, xml))
e.unstub(0x0808C0D8)
names = [e.cstr(e.r32(seen["names"] + 4 * k)) for k in range(seen.get("count", 0))]
check("Sync list: stock 7 + 1/32 appended (old indexes keep their meaning), label / xml passed on",
      names == ["Slice", "1 bar", "1/2", "1/4", "1/8", "1/16", "None", "1/32"] and seen["label"] == "Sync:"
      and seen["xml"] == "synctype", (names, seen))
check("Sync beats table: clip param handler's literal points at the 8-entry table",
      struct.unpack_from("<I", IMG, 0x08067BB4 - BASE)[0] == SYM["sync_beats"]
      and e.rf(SYM["sync_beats"], 8) == [1024.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.0, 0.125])

# --- clip Pos pages
pos = [struct.unpack_from("<10H", IMG, t - BASE) for t in (0x080EF288, 0x080EF990)]
check("clip Pos pages: Loop Mode, Beat Count, Quant Size, Sync, Shift, Play Len, Stretch, Str Mode, Loop Fade",
      all(p == (0x8D, 0xD2, 0x47, 0x94, P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE, 0) for p in pos), pos)

done()
