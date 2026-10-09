"""Where does the code at a micro address occur in another image? Matches the first N bytes, then the longest
common prefix, ignoring BL/literal words is not attempted: exact bytes only. usage: bytematch.py A.bin B.bin addr[:n]..."""
import sys
a=open(sys.argv[1],'rb').read(); b=open(sys.argv[2],'rb').read(); B=0x08040000
for spec in sys.argv[3:]:
    addr,_,n=spec.partition(':'); addr=int(addr,16); n=int(n or '20',0)
    pat=a[addr-B:addr-B+n]; hits=[]; i=b.find(pat)
    while i>=0 and len(hits)<5: hits.append(i); i=b.find(pat,i+2)
    out=[]
    for h in hits:
        k=0
        while h+k<len(b) and addr-B+k<len(a) and a[addr-B+k]==b[h+k]: k+=1
        out.append(f"{B+h:#x}(+{k}B)")
    print(f"{addr:#x}: {' '.join(out) or 'no match'}")
