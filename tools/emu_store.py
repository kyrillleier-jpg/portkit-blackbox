"""Unicorn check: pad-record store init (0x08089fc4) -> 0xd2 present; set (0x080894fa) / get (0x080894d0) round trip.
usage: emu_store.py MICRO.BIN"""
import sys, struct
from unicorn import *
from unicorn.arm_const import *
d=open(sys.argv[1],'rb').read(); B=0x08040000
mu=Uc(UC_ARCH_ARM, UC_MODE_THUMB|UC_MODE_MCLASS)
mu.mem_map(B, (len(d)+0xfff)&~0xfff); mu.mem_write(B, d)
mu.mem_map(0x24000000, 0x80000)                    # AXI SRAM, zeroed
mu.mem_map(0x20000000, 0x20000)                    # DTCM
mu.mem_map(0xE0000000, 0x100000)                   # SCS (FPU enable)
mu.mem_write(0xE000ED88, struct.pack('<I', 0xF<<20))
RET=0x24000000                                      # return trap
calls=[]
def hook(uc, addr, size, _):
    if addr==RET: uc.emu_stop()
mu.hook_add(UC_HOOK_CODE, hook, begin=RET, end=RET+2)
heap=[0x24060000]
def alloc(uc, addr, size, _):                       # 0x08042dc0(size, n): calloc-like; stand-in bump allocator
    n=uc.reg_read(UC_ARM_REG_R0)*max(1,uc.reg_read(UC_ARM_REG_R1)); p=heap[0]; heap[0]+=(n+7)&~7
    uc.mem_write(p, bytes(n)); uc.reg_write(UC_ARM_REG_R0, p)
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
mu.hook_add(UC_HOOK_CODE, alloc, begin=0x08042dc0, end=0x08042dc0)
def call(fn, *args, sp=0x2407f000):
    for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3), args): mu.reg_write(r, v)
    mu.reg_write(UC_ARM_REG_SP, sp); mu.reg_write(UC_ARM_REG_LR, RET|1)
    mu.emu_start(fn|1, RET, count=2_000_000)
    return mu.reg_read(UC_ARM_REG_R0)
# FPU on (CPACR)
APP=0x24013cb0; rec=APP+0x1840+1*0xf0+2*0x30       # row 1, col 2
typ=0x24070000; mu.mem_write(typ, b'\x45')
call(0x08089fc4, rec, typ)
cnt=struct.unpack('<H', mu.mem_read(rec+0xa,2))[0]; ent=struct.unpack('<I', mu.mem_read(rec+4,4))[0]
ids=[struct.unpack('<H', mu.mem_read(ent+8*k,2))[0] for k in range(cnt)] if ent else []
print(f"record {rec:#x}: {cnt} entries @ {ent:#x}; 0xd2 present: {0xd2 in ids}")
print("get 0xd2 after init:", call(0x080894d0, rec, 0xd2))
call(0x080894fa, rec, 0xd2, 1)
print("get 0xd2 after set 1:", call(0x080894d0, rec, 0xd2))
