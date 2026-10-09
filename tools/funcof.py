"""Map addresses to their enclosing function: nearest preceding PUSH {...,lr} / PUSH.W / STMDB sp!. usage: funcof.py BIN < addrs"""
import sys, struct
d=open(sys.argv[1],'rb').read(); B=0x08040000
def is_push(off):
    h=struct.unpack_from('<H',d,off)[0]
    if (h & 0xff00)==0xb500: return True                      # push {.., lr}
    if h==0xe92d: return (struct.unpack_from('<H',d,off+2)[0] & 0x4000)!=0   # push.w {.., lr}
    return False
def start(a):
    off=(a-B)&~1
    while off>0 and not is_push(off): off-=2
    return B+off
for line in sys.stdin:
    a=int(line.split()[0],16); print(f"{a:#x} in {start(a):#x}  {line.strip()}")
