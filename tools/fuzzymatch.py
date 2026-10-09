"""Find the function in image B most similar to a micro function, by normalised instruction sequence
(branch targets, pc-relative offsets masked). Searches B within +-window of a hint address.
usage: fuzzymatch.py A.bin B.bin a_addr:b_hint[:window] ..."""
import sys, re, difflib
from capstone import *
A=open(sys.argv[1],'rb').read(); Bi=open(sys.argv[2],'rb').read(); BASE=0x08040000
md=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS); md.skipdata=True
def norm(d, addr, n=40):
    out=[]
    for i in md.disasm(d[addr-BASE:addr-BASE+n*4], addr):
        if len(out)>=n: break
        m=i.mnemonic; o=i.op_str
        if m.startswith(('b','cb')) and '#' in o: o=re.sub(r'#0x[0-9a-f]+','#T',o)
        if 'pc' in o: o=re.sub(r'#-?0x[0-9a-f]+|#-?\d+','#L',o)
        out.append(m+' '+o)
    return out
for spec in sys.argv[3:]:
    p=spec.split(':'); a=int(p[0],16); hint=int(p[1],16); w=int(p[2],16) if len(p)>2 else 0x800
    ref=norm(A,a); best=[]
    for c in range(hint-w, hint+w, 2):
        r=difflib.SequenceMatcher(None, ref, norm(Bi,c,len(ref)), autojunk=False).ratio()
        best.append((r,c))
    best.sort(reverse=True)
    print(f"{a:#x} hint {hint:#x}: " + "  ".join(f"{c:#x}={r:.2f}" for r,c in best[:3]))
