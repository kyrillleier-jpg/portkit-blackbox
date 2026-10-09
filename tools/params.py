"""Dump the parameter-table registrations (FUN_08069f00): id, label, xml name, register function. usage: params.py BIN"""
import sys, struct, re
from capstone import *
from capstone.arm import *
d=open(sys.argv[1],'rb').read(); B=0x08040000
def u32(a): return struct.unpack_from('<I',d,a-B)[0]
def cstr(a):
    if not (B<=a<B+len(d)): return None
    s=d[a-B:a-B+40].split(b'\0')[0]
    return s.decode('latin1') if s and all(32<=c<127 for c in s) else None
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.detail=True; md.skipdata=True
lo,hi=0x08069f00,0x0806bbc0
regs={}; stack={}
out=[]
for i in md.disasm(d[lo-B:hi-B], lo):
    if i.id==0: continue
    ops=i.operands
    if i.mnemonic.startswith('ldr') and len(ops)==2 and ops[1].type==ARM_OP_MEM and ops[1].mem.base==ARM_REG_PC:
        regs[ops[0].reg]=u32(((i.address+4)&~3)+ops[1].mem.disp)
    elif i.mnemonic.startswith(('mov','movs','mov.w','movw')) and len(ops)==2:
        if ops[1].type==ARM_OP_IMM: regs[ops[0].reg]=ops[1].imm
        elif ops[1].type==ARM_OP_REG: regs[ops[0].reg]=regs.get(ops[1].reg)
    elif i.mnemonic.startswith('str') and len(ops)==2 and ops[1].type==ARM_OP_MEM and ops[1].mem.base==ARM_REG_SP:
        stack[ops[1].mem.disp]=regs.get(ops[0].reg)
    elif i.mnemonic=='bl':
        f=ops[0].imm; pid=regs.get(ARM_REG_R1)
        strs=[cstr(v) for v in (regs.get(ARM_REG_R2),regs.get(ARM_REG_R3),stack.get(0),stack.get(4),stack.get(8)) if isinstance(v,int)]
        strs=[s for s in strs if s]
        if isinstance(pid,int) and pid<0x400:
            out.append(f"{i.address:#x} fn={f:#x} id={pid:#05x} r2={regs.get(ARM_REG_R2)!r:>12} {strs}")
print("\n".join(out))
