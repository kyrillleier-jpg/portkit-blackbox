"""Catalogue widget setRect calls: `ldr rX, [rY, #0x20]; add r1, sp, #k; blx rX` with the rect {x, y, w, h} stored
at sp+k just before (immediates or registers). usage: rects.py BIN > re/rects_micro.txt"""
import re, sys
from capstone import *
from capstone.arm import *
d = open(sys.argv[1], 'rb').read(); B = 0x08040000
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS); md.detail = True; md.skipdata = True
ins = [i for i in md.disasm(d[:0x80000], B) if i.id]
for k, i in enumerate(ins):
    if i.mnemonic != 'blx':
        continue
    win = ins[max(0, k - 24):k]
    vt = [w for w in win if w.mnemonic == 'ldr' and re.match(r'\w+, \[\w+, #0x20\]$', w.op_str)]
    a1 = [w for w in win if re.match(r'add(\.w)?$', w.mnemonic) and re.match(r'r1, sp, #(0x[0-9a-f]+|\d+)$', w.op_str)]
    if not vt or not a1:
        continue
    base = int(a1[-1].op_str.split('#')[1], 0)
    regs, vals = {}, {}
    for w in win:
        s = w.mnemonic + ' ' + w.op_str
        m = re.match(r'movs?(?:\.w)?|movw', w.mnemonic)
        if m and len(w.operands) == 2 and w.operands[1].type == ARM_OP_IMM:
            regs[w.reg_name(w.operands[0].reg)] = w.operands[1].imm
        m = re.match(r'(str|strh)(?:\.w)? (\w+), \[sp, #(0x[0-9a-f]+|\d+)\]$', s)
        if m:
            off = int(m.group(3), 0) - base
            if 0 <= off < 16:
                vals[off] = regs.get(m.group(2), m.group(2))
        m = re.match(r'strd (\w+), (\w+), \[sp, #(0x[0-9a-f]+|\d+)\]$', s)
        if m:
            off = int(m.group(3), 0) - base
            for j, r in enumerate((m.group(1), m.group(2))):
                if 0 <= off + 4 * j < 16:
                    vals[off + 4 * j] = regs.get(r, r)
    rect = [vals.get(o, '?') for o in (0, 4, 8, 12)]
    print(f"{i.address:#x} rect(x,y,w,h)={rect}")
