"""Map addresses inside a Bitbox micro function to the same instructions in its Blackbox counterpart.

  python3 tools/falign.py <micro func> <bb func> [<micro addr> ...]   -> per address: BB address, both instructions
  python3 tools/falign.py --callers <bb target> [<micro target>]      -> BL call sites of a function in both images

The two functions are disassembled up to their first `pop {.., pc}` / `pop.w` past `span` bytes and aligned on
normalized instructions (tools/fmatch.py: branch targets and pc-relative offsets ignored) with difflib. An address
maps only if its instruction lies in a matching block; the printed pair shows the real operands for checking
(different struct offsets show up there). Leads only ("vermutet") until checked.
"""
import difflib
import os
import sys

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmatch import norm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x08040000
IMGS = {"micro": os.path.join(ROOT, "firmware", "MICRO.BIN"), "bb": os.path.join(ROOT, "firmware", "BLACKBOX.bin")}
_data = {}


def data(which):
    if which not in _data:
        _data[which] = open(IMGS[which], "rb").read()
    return _data[which]


def func(which, start, span=0x1800):
    d = data(which)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.skipdata = True
    out = []
    for i in md.disasm(d[start - BASE:start - BASE + span], start):
        out.append(i)
    return out


def align(ma, ba, span=0x1800):
    m, b = func("micro", ma, span), func("bb", ba, span)
    sm = difflib.SequenceMatcher(None, [norm(i) for i in m], [norm(i) for i in b], autojunk=False)
    mp = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            mp[m[blk.a + k].address] = b[blk.b + k]
    return {i.address: i for i in m}, mp


def callers(which, target, end=0xB4000):
    d = data(which)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.skipdata = True
    return [i.address for i in md.disasm(d[:end], BASE) if i.mnemonic == "bl" and int(i.op_str[1:], 16) == target]


def main(a):
    if a[0] == "--callers":
        print("bb   :", " ".join(hex(x) for x in callers("bb", int(a[1], 16))))
        if len(a) > 2:
            print("micro:", " ".join(hex(x) for x in callers("micro", int(a[2], 16))))
        return
    ma, ba = int(a[0], 16), int(a[1], 16)
    mins, mp = align(ma, ba)
    print(f"aligned {len(mp)} of {len(mins)} instructions")
    for x in a[2:]:
        x = int(x, 16)
        i, j = mins.get(x), mp.get(x)
        if i is None:
            print(f"{x:#010x}: not an instruction start in the micro function")
        elif j is None:
            print(f"{x:#010x}: {i.mnemonic} {i.op_str}  ->  no match")
        else:
            print(f"{x:#010x}: {i.mnemonic} {i.op_str}  ->  {j.address:#010x}: {j.mnemonic} {j.op_str}")


if __name__ == "__main__":
    main(sys.argv[1:])
