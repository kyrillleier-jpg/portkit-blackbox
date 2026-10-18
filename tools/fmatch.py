"""Find a Bitbox micro 2.3.4 code address in the Blackbox 3.1.9 image by normalized instruction windows.

  python3 tools/fmatch.py <micro addr> [...]          -> best Blackbox candidates per address, with votes

Instructions are normalized (mnemonic + operands, branch targets and pc-relative offsets replaced by placeholders),
windows of W instructions are hashed; every window of the Micro function around the address votes for an offset
(Blackbox address - Micro address). The shared framework (matrixsw/BoomboxFramework) compiles to similar code with
different addresses. A candidate is only a lead: check it by disassembly (status "vermutet" until then).
"""
import os
import re
import sys
from collections import Counter, defaultdict

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x08040000
W = 6
SPAN = 0x200            # bytes of the Micro function looked at, after the address
_cache = {}


def norm(i):
    op = i.op_str
    if i.mnemonic.startswith(("b", "cb")) and "#" in op:
        op = re.sub(r"#0x[0-9a-f]+", "#T", op)
    if "pc" in op:
        op = re.sub(r"#-?0x[0-9a-f]+", "#L", op)
    return i.mnemonic + " " + op


def listing(path, end=0xB4000):
    if path in _cache:
        return _cache[path]
    d = open(path, "rb").read()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.skipdata = True
    ins = [(i.address, norm(i)) for i in md.disasm(d[:end], BASE)]
    _cache[path] = ins
    return ins


def index(ins):
    idx = defaultdict(list)
    for k in range(len(ins) - W):
        idx[hash(tuple(n for _, n in ins[k:k + W]))].append(ins[k][0])
    return idx


def match(addr, micro, bb, bidx):
    pos = {a: k for k, (a, _) in enumerate(micro)}
    k0 = pos.get(addr)
    if k0 is None:
        return []
    votes = Counter()
    k = k0
    while k < len(micro) - W and micro[k][0] < addr + SPAN:
        for b in bidx.get(hash(tuple(n for _, n in micro[k:k + W])), ()):
            votes[b - micro[k][0]] += 1
        k += 1
    return [(addr + off, v) for off, v in votes.most_common(3)]


def main(addrs):
    micro = listing(os.path.join(ROOT, "firmware", "MICRO.BIN"))
    bb = listing(os.path.join(ROOT, "firmware", "BLACKBOX.bin"))
    bidx = index(bb)
    for a in addrs:
        print(f"{a:#010x}:", ", ".join(f"{c:#010x} ({v})" for c, v in match(a, micro, bb, bidx)) or "-")


if __name__ == "__main__":
    main([int(x, 16) for x in sys.argv[1:]])
