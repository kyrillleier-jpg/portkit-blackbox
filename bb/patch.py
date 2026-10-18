"""Patch the blackbox-mod image (bb/build.py) with our Blackbox patchsets and write an SD-card-ready BLACKBOX.bin.

  python3 bb/patch.py master            (run bb/build.py first)  -> out/bb/<sets>/BLACKBOX.bin

Each patchset in bb/patches/ defines PATCHES = [(addr, old_bytes, new_bytes), ...] (plus HOOKS / THUNKS / WORDS for
the checks). The base must be the image bb/build.py made from the stock 3.1.9 (checked by blackbox-mod's patch.py) and
must not have changed since. verify():
  - zero repack: applying nothing reproduces the base bit for bit
  - every changed byte lies inside a registered patch range or the appended cave
  - every rewritten BL (HOOKS, THUNKS) lands on a function of our cave; every rewritten word (WORDS) on a cave symbol
  - the image ends below 0x08100000 (flash bank 1)
Nothing is written unless all checks pass.
"""
import hashlib
import importlib
import os
import sys

BB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BB)
sys.path.insert(0, os.path.join(BB, "patches"))
from bbthumb import BASE, SYM, bl_target  # noqa: E402

OUT = os.path.join(ROOT, "out", "bb")
FLASH_END = 0x08100000


def load_base():
    base = open(os.path.join(OUT, "base", "BLACKBOX.bin"), "rb").read()
    elf, cave = os.path.join(OUT, "cave.elf"), os.path.join(OUT, "cave.bin")
    newest = max(os.path.getmtime(os.path.join(BB, "src", f)) for f in os.listdir(os.path.join(BB, "src")))
    assert os.path.getmtime(elf) >= newest, "out/bb/cave.elf is older than bb/src: run bb/build.py"
    return base, open(cave, "rb").read()


def apply(base, cave, names):
    data = bytearray(base)
    ranges = []
    for name in names:
        for addr, old, new in importlib.import_module(name).PATCHES:
            o = addr - BASE
            assert 0 <= o and o + len(old) <= len(base), f"{name}: {addr:#x} outside the base image"
            assert data[o:o + len(old)] == old, f"{name}: base bytes differ at {addr:#x}"
            assert len(old) == len(new), f"{name}: size change at {addr:#x}"
            assert not any(a < addr + len(new) and addr < b for a, b in ranges), f"{name}: overlapping patch at {addr:#x}"
            data[o:o + len(new)] = new
            ranges.append((addr, addr + len(new)))
            print(f"{name}: {addr:#010x} {old.hex()} -> {new.hex()}")
    if names:
        origin = (BASE + len(base) + 7) & ~7
        data += bytes(origin - BASE - len(data)) + cave
        ranges.append((BASE + len(base), BASE + len(data)))
        print(f"cave: {origin:#010x} append {len(cave)} bytes")
    return data, ranges


def verify(base, cave, data, ranges, names):
    zero, _ = apply(base, cave, [])
    assert bytes(zero) == base, "zero repack differs from the base image"
    for o in range(len(base)):
        if data[o] != base[o]:
            assert any(lo <= BASE + o < hi for lo, hi in ranges), f"unregistered change at {BASE + o:#x}"
    origin = (BASE + len(base) + 7) & ~7
    end = BASE + len(data)
    assert end <= FLASH_END, f"image ends at {end:#x}, beyond flash bank 1"
    funcs = {v & ~1 for v in SYM.values()}
    for name in names:
        mod = importlib.import_module(name)
        for at, _, sym in getattr(mod, "HOOKS", []) + getattr(mod, "THUNKS", []):
            t = bl_target(bytes(data[at - BASE:at - BASE + 4]), at)
            assert t is not None and origin <= t < end and t in funcs and t == SYM[sym] & ~1, f"{name}: BL at {at:#x}"
        for at, _, sym in getattr(mod, "WORDS", []):
            v = int.from_bytes(data[at - BASE:at - BASE + 4], "little")
            assert origin <= v < end and v == SYM[sym], f"{name}: word at {at:#x} = {v:#x}"
    print("verify: zero repack ok, all changes registered, detours and pointers land in the cave, ends below bank 2")


def main(names):
    base, cave = load_base()
    data, ranges = apply(base, cave, names)
    verify(base, cave, data, ranges, names)
    out_dir = os.path.join(OUT, "+".join(names))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "BLACKBOX.bin")
    open(out, "wb").write(data)
    print(f"wrote {out} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})")


if __name__ == "__main__":
    main(sys.argv[1:])
