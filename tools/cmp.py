import re, sys, hashlib
m = open(sys.argv[1],'rb').read(); b = open(sys.argv[2],'rb').read()
def strs(d, n=5):
    return set(x.decode() for x in re.findall(rb'[\x20-\x7e]{%d,}'%n, d))
sm, sb = strs(m), strs(b)
common = sm & sb
print("strings micro", len(sm), "blackbox", len(sb), "common", len(common))
kw = ['Interp','Overdrive','Fidelity','Reverb','Delay','Granular','Slicer','Comp','Filter','Cutoff','Resonance','Sustain','Density','Scatter','Grain','Biquad','EQ','Pump','Duck','Chord','Solo','Mute','Sidechain','Saturat','Drive','Bitcrush','Crush','Sample Rate','Mono Poly','Multi']
for k in kw:
    cm = sorted(s for s in sm if k.lower() in s.lower())[:6]
    cb = sorted(s for s in sb if k.lower() in s.lower())[:6]
    print(f"\n[{k}] micro: {cm}\n      bb:    {cb}")
# code similarity: hash 64-byte aligned (2-byte step) windows in code region
W=48
def wins(d, step=2):
    h=set()
    for i in range(0, len(d)-W, step):
        w=d[i:i+W]
        if w.count(0)>W//2 or len(set(w))<8: continue
        h.add(hashlib.md5(w).digest()[:8])
    return h
hm=wins(m); hb=wins(b)
inter=hm&hb
print("\nwindows micro",len(hm),"bb",len(hb),"shared",len(inter), "%.1f%% of micro"%(100*len(inter)/len(hm)))
