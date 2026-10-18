"""The parameter manifest of the last JOEBOX build: what its firmware knows, by XML name (the key presets and
settings.tml use). Runs the image's whole registration (0x0808c158) in Unicorn and reads the parameter table.

  python3 -I tests/manifest_jb.py      -> out/bb/jb/release/params.json (and the build's own folder)

Table entry (28 bytes, 0x0808c0a8): +0 id, +2 type (5 = list), +4 label, then for a list +8 names, +0xc count,
for a number +0x10 min, +0x14 max; +0x18 xml name.
"""
import json
import os
import struct
import sys

os.environ["PK_BB"] = "jb"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1  # noqa: E402

from bb_emu import BBEmu  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = os.path.join(ROOT, "out", "bb", "jb", "release")

e = BBEmu()
e.mu.mem_map(0xC0000000, 0x400000)
e.mu.mem_map(0x20000000, 0x20000)
e.mu.mem_map(0x38800000, 0x1000)
sd = [0xC0000000]


def sdram(uc):
    n = uc.reg_read(UC_ARM_REG_R0) * max(1, uc.reg_read(UC_ARM_REG_R1))
    p = sd[0]
    sd[0] += (n + 15) & ~15
    uc.reg_write(UC_ARM_REG_R0, p)


e.stub(0x0804436C, sdram)
e.stub(0x080443A8, lambda uc: (uc.reg_write(UC_ARM_REG_R1, 1), sdram(uc)))
e.call(0x0808C158)
table = e.r32(0x2401F4FC)


def s(a):
    try:
        return bytes(e.mu.mem_read(a, 48)).split(b"\0")[0].decode("latin1") if a else ""
    except Exception:
        return ""


out = {}
for pid in range(0, 1024):
    try:
        raw = bytes(e.mu.mem_read(table + 28 * pid, 28))
    except Exception:
        break
    eid, typ = struct.unpack_from("<HB", raw)
    if eid != pid or (pid and not any(raw)):
        continue
    w = struct.unpack_from("<6I", raw, 4)
    xml = s(w[5])
    if not xml:
        continue
    d = {"id": pid, "type": typ, "label": s(w[0])}
    if typ == 5:
        d["count"] = w[2]
        d["names"] = [s(e.r32(w[1] + 4 * k)) for k in range(min(w[2], 200))] if w[1] else []
    else:
        d["min"] = struct.unpack("<i", struct.pack("<I", w[3]))[0]
        d["max"] = struct.unpack("<i", struct.pack("<I", w[4]))[0]
    out[xml] = d

info = json.load(open(os.path.join(REL, "build.json")))
for d in {REL, info.get("dir", REL)}:
    json.dump({"groups": info["groups"], "params": out}, open(os.path.join(d, "params.json"), "w"), indent=0)
print(f"manifest: {len(out)} parameters")
