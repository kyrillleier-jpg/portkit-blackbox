"""Offsets accessed via r4 (the object) in a function range, plus 'add rX, r4, #off' address-takes. usage: fields.py BIN start end"""
import sys, re
from capstone import *
d=open(sys.argv[1],'rb').read(); B=0x08040000; s=int(sys.argv[2],16); e=int(sys.argv[3],16)
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.skipdata=True
acc={}
for i in md.disasm(d[s-B:e-B], s):
    for m in re.finditer(r'\[r4(?:, #(0x[0-9a-f]+|\d+))?\]', i.op_str):
        o=int(m.group(1) or '0',0); acc.setdefault(o,set()).add(i.mnemonic.split('.')[0])
    m=re.match(r'(?:r\d+|sb|sl|fp|r8), r4, #(0x[0-9a-f]+|\d+)$', i.op_str)
    if i.mnemonic.startswith('add') and m: acc.setdefault(int(m.group(1),0),set()).add('&addr')
print(' '.join(f"{o:#x}:{'/'.join(sorted(v))}" for o,v in sorted(acc.items())))
