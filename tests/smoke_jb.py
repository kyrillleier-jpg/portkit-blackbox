"""Smoke test of the last JOEBOX build (out/bb/jb/release + cave.elf + bank2.bin), whatever groups it has: the whole
parameter registration, the settings init and a clip pad record run without a fault and stay within capacity, and the
clip reader call goes where the groups say. Run by the dashboard after every build.

  python3 -I tests/smoke_jb.py
"""
import json
import os
import struct
import sys

os.environ["PK_BB"] = "jb"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1  # noqa: E402

from bb_emu import BASE, IMG, SYM, BBEmu, bl_target, check, done  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
info = json.load(open(os.path.join(ROOT, "out", "bb", "jb", "release", "build.json")))
groups = set(info["groups"])

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
check("parameter registration (stock + JOEBOX + portkit) runs through", True)
st = e.new(0x20)
e.call(0x0809481C, st)
cnt, cap = e.r16(st + 0xA), e.r16(st + 0xC)
check(f"global settings: {cnt} of {cap}", 0 < cnt <= cap)
rec, t3 = e.new(0x30), e.new(4)
e.mu.mem_write(t3, b"\x03")
e.call(0x08094A1C, rec, t3)
cnt, cap = e.r16(rec + 0xA), e.r16(rec + 0xC)
check(f"clip pad record: {cnt} of {cap}", 0 < cnt <= cap)

t = bl_target(IMG[0x08066622 - BASE:0x08066622 - BASE + 4], 0x08066622)
want = ("pk_clip_entry" if "filter" in groups else "pk_clip_entry_stock") if "pk_stretch" in groups else \
       ("clip_read_b" if "filter" in groups else None)
check(f"clip reader call -> {want or 'stock 0x080662e4'}",
      t == (SYM[want] & ~1 if want else 0x080662E4), hex(t or 0))
tab = struct.unpack_from("<I", IMG, 0x080EEE90 - BASE)[0]
has_extra = bool(groups & {"pk_dist", "pk_fx3"})
check(f"Tools tab 'Extra' {'present' if has_extra else 'absent'}", (tab == SYM["pk_tab"]) == has_extra)
check("image ends below bank 2", BASE + len(IMG) <= 0x08100000)
done()
