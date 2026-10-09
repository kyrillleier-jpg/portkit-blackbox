"""Function containing each address, with function starts = every BL/B.W target plus every odd word in the image that
points into code (vtables, callback tables). Prints the start, how it is reached (BL callers / table words).
usage: fstarts.py BIN addr..."""
import struct, sys
d = open(sys.argv[1], 'rb').read(); B = 0x08040000
def bl(off):
    h1, h2 = struct.unpack_from('<HH', d, off)
    if h1 >> 11 != 0b11110 or not (h2 >> 12) & 1 or not (h2 >> 14) & 1 and not (h2 >> 12) & 1: return None
    if (h2 >> 14) & 0b11 != 0b11 and (h2 >> 12) & 0b101 != 0b001: return None
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    imm = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s: imm -= 1 << 25
    t = B + off + 4 + imm
    return t if B <= t < B + len(d) else None
calls, words = {}, {}
for off in range(0, len(d) - 4, 2):
    t = bl(off)
    if t: calls.setdefault(t, []).append(B + off)
for off in range(0, len(d) - 3, 4):
    v = struct.unpack_from('<I', d, off)[0]
    if v & 1 and B <= v < B + 0xA0000: words.setdefault(v & ~1, []).append(B + off)
starts = sorted(set(calls) | set(words))
import bisect
for a in (int(x, 16) for x in sys.argv[2:]):
    f = starts[bisect.bisect_right(starts, a) - 1]
    print(f"{a:#x} in {f:#x}  bl-from {[hex(c) for c in calls.get(f, [])][:6]}  table-words {[hex(w) for w in words.get(f, [])][:4]}")
