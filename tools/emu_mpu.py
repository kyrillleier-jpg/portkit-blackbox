"""Run MPU_Config (0x08041098) in Unicorn and dump the four HAL_MPU_ConfigRegion (0x0804a340) arguments. usage: emu_mpu.py MICRO.BIN"""
import sys, struct
from unicorn import *
from unicorn.arm_const import *
d=open(sys.argv[1],'rb').read(); B=0x08040000
mu=Uc(UC_ARCH_ARM, UC_MODE_THUMB|UC_MODE_MCLASS)
mu.mem_map(B,(len(d)+0xfff)&~0xfff); mu.mem_write(B,d)
mu.mem_map(0x24000000,0x80000); mu.mem_map(0xE0000000,0x100000)
RET=0x24000000
def ret(uc): uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
def hook(uc, a, size, _):
    if a==RET: uc.emu_stop()
    elif a in (0x0804a2fc, 0x0804a31c): ret(uc)          # MPU disable / enable: skipped
    elif a==0x0804a340:
        p=uc.reg_read(UC_ARM_REG_R0); s=bytes(uc.mem_read(p,16))
        en,num=s[0],s[1]; base=struct.unpack_from('<I',s,4)[0]; size=s[8]
        print(f"region {num}: enable={en} base={base:#010x} size=2^{size+1}={1<<(size+1):#x} "
              f"end={base+(1<<(size+1)):#010x} srd={s[9]:#04x} TEX={s[10]} AP={s[11]} XN={s[12]} S={s[13]} C={s[14]} B={s[15]}")
        ret(uc)
mu.hook_add(UC_HOOK_CODE, hook)
mu.reg_write(UC_ARM_REG_SP, 0x2407f000); mu.reg_write(UC_ARM_REG_LR, RET|1)
mu.emu_start(0x08041098|1, RET, count=100000)
