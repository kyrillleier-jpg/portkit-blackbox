"""Contact sheet of screenshots: python3 sim/sheet.py out.png a.png b.png ... (same size, 4 per row)."""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb2png  # noqa: E402


def readpng(p):
    d = open(p, "rb").read()
    i, idat = 8, b""
    while i < len(d):
        n = struct.unpack(">I", d[i:i + 4])[0]
        t = d[i + 4:i + 8]
        if t == b"IHDR":
            w, h = struct.unpack(">II", d[i + 8:i + 16])
        if t == b"IDAT":
            idat += d[i + 8:i + 8 + n]
        i += 12 + n
    raw, st = zlib.decompress(idat), w * 3
    return w, h, [raw[y * (st + 1) + 1:(y + 1) * (st + 1)] for y in range(h)]


def main(dst, srcs, cols=4):
    w, h, _ = readpng(srcs[0])
    rows = (len(srcs) + cols - 1) // cols
    W = w * min(cols, len(srcs))
    img = bytearray(b"\x1e" * (W * h * rows * 3))
    for n, s in enumerate(srcs):
        _, _, px = readpng(s)
        ox, oy = (n % cols) * w, (n // cols) * h
        for y in range(h):
            o = ((oy + y) * W + ox) * 3
            img[o:o + w * 3] = px[y]
    fb2png.png(dst, W, h * rows, list(img))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
