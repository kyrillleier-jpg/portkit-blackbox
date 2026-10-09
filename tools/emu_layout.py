"""Run a screen constructor in Unicorn and list its widgets: rect {x, y, w, h} (+4..+0x10), vtable, id (+0x38 for
buttons), text set via 0x0805d1dc, parent. Allocator stubbed. usage: emu_layout.py MICRO.BIN ctor_addr [size]"""
import struct, sys
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc, UcError
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_SP, UC_CPU_ARM_MAX)
d = open(sys.argv[1], 'rb').read(); B = 0x08040000
ctor = int(sys.argv[2], 16); size = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x10000
mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB); mu.ctl_set_cpu_model(UC_CPU_ARM_MAX)
mu.mem_map(B, (len(d) + 0xFFFF) & ~0xFFFF); mu.mem_write(B, d)
mu.mem_map(0x20000000, 0x20000); mu.mem_map(0x24000000, 0x80000); mu.mem_map(0x30000000, 0x80000)
mu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20); mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
RET, OBJ = 0x24000000, 0x24010000
heap = [0x30000000]
def ret(uc): uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
def alloc(uc, a, *_):
    n = uc.reg_read(UC_ARM_REG_R0) * max(1, uc.reg_read(UC_ARM_REG_R1)); p = heap[0]; heap[0] += (n + 15) & ~15
    uc.mem_write(p, bytes(n)); uc.reg_write(UC_ARM_REG_R0, p); ret(uc)
children, texts = [], {}
def add_child(uc, a, *_):
    children.append((uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)))
def set_text(uc, a, *_):
    p = uc.reg_read(UC_ARM_REG_R1)
    try: s = bytes(uc.mem_read(p, 24)).split(b'\0')[0].decode('latin1')
    except UcError: s = f'<{p:#x}>'
    texts[uc.reg_read(UC_ARM_REG_R0)] = s
mu.hook_add(UC_HOOK_CODE, lambda uc, a, *_: uc.emu_stop(), begin=RET, end=RET)
mu.hook_add(UC_HOOK_CODE, alloc, begin=0x08042DC0, end=0x08042DC0)
mu.hook_add(UC_HOOK_CODE, add_child, begin=0x08060D30, end=0x08060D30)
mu.hook_add(UC_HOOK_CODE, set_text, begin=0x0805D1DC, end=0x0805D1DC)
mu.reg_write(UC_ARM_REG_R0, OBJ); mu.reg_write(UC_ARM_REG_SP, 0x2407F000); mu.reg_write(UC_ARM_REG_LR, RET | 1)
try:
    mu.emu_start(ctor | 1, RET, count=20_000_000)
except UcError as ex:
    print("stopped:", ex, hex(mu.reg_read(UC_ARM_REG_PC)))
r32 = lambda a: struct.unpack('<I', mu.mem_read(a, 4))[0]
ri = lambda a: struct.unpack('<i', mu.mem_read(a, 4))[0]
for parent, w in children:
    x, y, wd, h = (ri(w + 4 + 4 * k) for k in range(4))
    rel = f"+{w - OBJ:#06x}" if OBJ <= w < OBJ + size else f"{w:#x}"
    prel = f"+{parent - OBJ:#06x}" if OBJ <= parent < OBJ + size else f"{parent:#x}"
    print(f"{rel:>9} parent {prel:>9} vt {r32(w):#010x} rect x={x:4d} y={y:4d} w={wd:4d} h={h:4d} id={struct.unpack('<H', mu.mem_read(w + 0x38, 2))[0]:#06x} {texts.get(w, '')!r}")
