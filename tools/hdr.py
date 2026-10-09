import sys, struct, math, collections
d=open(sys.argv[1],'rb').read()
def ent(b):
    c=collections.Counter(b); n=len(b)
    return -sum(v/n*math.log2(v/n) for v in c.values())
print("size",len(d))
print("first 64 bytes:", d[:64].hex(' '))
w=struct.unpack('<16I', d[:64])
print("words:", [hex(x) for x in w])
print("entropy whole %.3f"%ent(d))
for i in range(0,len(d),65536):
    print(f"  {i:#08x}: {ent(d[i:i+65536]):.2f}", end='')
print()
base=0x08040000
sp,rv=w[0],w[1]
print("initial SP",hex(sp),"reset",hex(rv), "reset offset in file", hex((rv&~1)-base))
# thumb code sanity: how many of the vector entries point into image
n=sum(1 for x in w[1:] if base<=(x&~1)<base+len(d))
print("vector entries inside image:", n)
