"""All BL sites in the image with caller function (push heuristic). usage: allcalls.py BIN > calls.tsv"""
import sys, struct, importlib.util, os
here=os.path.dirname(os.path.abspath(__file__))
def load(n):
    s=importlib.util.spec_from_file_location(n, os.path.join(here,n+'.py')); return s
d=open(sys.argv[1],'rb').read(); B=0x08040000
def bl(off):
    h1,h2=struct.unpack_from('<HH',d,off)
    if (h1>>11)!=0b11110 or ((h2>>12)&0b101)!=0b101: return None
    S=(h1>>10)&1; J1=(h2>>13)&1; J2=(h2>>11)&1
    imm=(S<<24)|((1-(J1^S))<<23)|((1-(J2^S))<<22)|((h1&0x3ff)<<12)|((h2&0x7ff)<<1)
    if S: imm-=1<<25
    t=B+off+4+imm
    return t if B<=t<B+len(d) else None
def is_push(off):
    h=struct.unpack_from('<H',d,off)[0]
    return (h&0xff00)==0xb500 or (h==0xe92d and struct.unpack_from('<H',d,off+2)[0]&0x4000)
cur=B
for off in range(0,len(d)-4,2):
    if is_push(off): cur=B+off
    t=bl(off)
    if t: print(f"{B+off:#x}\t{cur:#x}\t{t:#x}")
