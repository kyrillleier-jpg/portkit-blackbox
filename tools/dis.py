import sys, struct
from capstone import *
d=open(sys.argv[1],'rb').read(); base=0x08040000
off=int(sys.argv[2],16); n=int(sys.argv[3],0)
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.skipdata=True
for i in md.disasm(d[off:off+n], base+off):
    print(f"{i.address:#010x}  {i.mnemonic:8s} {i.op_str}")
