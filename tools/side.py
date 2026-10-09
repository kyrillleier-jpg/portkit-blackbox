"""Side-by-side disassembly: side.py A.bin a_addr B.bin b_addr [n]"""
import sys
from capstone import *
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.skipdata=True; BASE=0x08040000
def dis(f,a,n):
    d=open(f,'rb').read(); return [f"{i.address:#x} {i.mnemonic} {i.op_str}" for i in md.disasm(d[a-BASE:a-BASE+n*4],a)][:n]
n=int(sys.argv[5]) if len(sys.argv)>5 else 14
L=dis(sys.argv[1],int(sys.argv[2],16),n); R=dis(sys.argv[3],int(sys.argv[4],16),n)
for l,r in zip(L,R): print(f"{l:48s} | {r}")
