"""Find BL/B.W call sites to target(s) by decoding the Thumb-2 BL encoding at every halfword. usage: callers.py BIN addr..."""
import sys, struct
d=open(sys.argv[1],'rb').read(); B=0x08040000
T={int(a,16)&~1 for a in sys.argv[2:]}
def bl_target(off):
    h1,h2=struct.unpack_from('<HH',d,off)
    if (h1>>11)!=0b11110: return None
    kind=h2>>14 & 0b11; link=(h2>>12)&0b101
    if link not in (0b101,0b001): return None   # BL (1x1) or B.W T4 (0x1)
    S=(h1>>10)&1; imm10=h1&0x3ff; J1=(h2>>13)&1; J2=(h2>>11)&1; imm11=h2&0x7ff
    I1=1-(J1^S); I2=1-(J2^S)
    imm=(S<<24)|(I1<<23)|(I2<<22)|(imm10<<12)|(imm11<<1)
    if S: imm-=1<<25
    return B+off+4+imm, ('bl' if link==0b101 else 'b.w')
for off in range(0,len(d)-4,2):
    r=bl_target(off)
    if r and r[0] in T: print(f"{B+off:#x} {r[1]:4s} -> {r[0]:#x}")
