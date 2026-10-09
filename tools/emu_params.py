"""Run the parameter-table init (0x08069f00) in Unicorn and print every list registration (0x08069e7c):
id, label, xml name, entries. usage: emu_params.py MICRO.BIN [id ...]"""
import struct, sys
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_CPU_ARM_MAX)
d = open(sys.argv[1], "rb").read(); B = 0x08040000
want = {int(a, 16) for a in sys.argv[2:]}
mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB); mu.ctl_set_cpu_model(UC_CPU_ARM_MAX)
mu.mem_map(B, (len(d) + 0xFFFF) & ~0xFFFF); mu.mem_write(B, d)
mu.mem_map(0x24000000, 0x80000)
mu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20); mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
RET, heap = 0x24000000, [0x24040000]
def s(a):
    if not (B <= a < B + len(d)): return f"<{a:#x}>"
    return d[a - B:a - B + 40].split(b"\0")[0].decode("latin1")
def ret(uc): uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
def alloc(uc, a, *_):
    n = uc.reg_read(UC_ARM_REG_R0); p = heap[0]; heap[0] += (n + 7) & ~7
    uc.mem_write(p, bytes(n)); uc.reg_write(UC_ARM_REG_R0, p); ret(uc)
def reg_list(uc, a, *_):
    pid, lab, names = (uc.reg_read(r) for r in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
    sp = uc.reg_read(UC_ARM_REG_SP)
    cnt, xml = struct.unpack("<II", uc.mem_read(sp, 8))
    if not want or pid in want:
        items = [s(struct.unpack("<I", uc.mem_read(names + 4 * k, 4))[0]) for k in range(min(cnt, 40))]
        print(f"id={pid:#05x} {s(lab)!r:16} xml={s(xml)!r:18} {cnt}: {items}")
    ret(uc)
mu.hook_add(UC_HOOK_CODE, lambda uc, a, *_: uc.emu_stop(), begin=RET, end=RET)
mu.hook_add(UC_HOOK_CODE, alloc, begin=0x08042DC0, end=0x08042DC0)
mu.hook_add(UC_HOOK_CODE, reg_list, begin=0x08069E7C, end=0x08069E7C)
table = 0x24030000
mu.reg_write(UC_ARM_REG_R0, table); mu.reg_write(UC_ARM_REG_SP, 0x2407F000); mu.reg_write(UC_ARM_REG_LR, RET | 1)
mu.emu_start(0x08069F00 | 1, RET, count=5_000_000)
