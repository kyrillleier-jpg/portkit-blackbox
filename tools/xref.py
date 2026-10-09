"""PC-relative LDR / ADR references to given addresses (literal-pool slots), Thumb-2. usage: xref.py BIN addr..."""
import sys
from capstone import *
from capstone.arm import *
d=open(sys.argv[1],'rb').read(); base=0x08040000
targets={int(a,16) for a in sys.argv[2:]}
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.detail=True; md.skipdata=True
# linear sweep from every halfword is noisy; sweep window of 4 KiB before each target, at both alignments
for t in sorted(targets):
    lo=max(0,t-base-4096)
    for start in (lo, lo+2):
        for i in md.disasm(d[start:t-base], base+start):
            if i.mnemonic.startswith(('ldr','adr','vldr')) and '[pc' in i.op_str or i.mnemonic.startswith('adr'):
                for op in i.operands:
                    if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
                        ea=((i.address+4)&~3)+op.mem.disp
                        if ea==t: print(f"{t:#x} <- {i.address:#x}  {i.mnemonic} {i.op_str}")
