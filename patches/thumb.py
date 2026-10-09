"""Thumb-2 encoding helpers for patchsets (BL encoder after blackbox-mod/patches/thumb.py, MIT, Justin Joe)."""
import os
import struct
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x08040000
STOCK_END = 0x080E3E90          # end of the stock 2.3.4 image = origin of the code cave (src/cave.ld)


def bl(at, target):
    """BL from `at` to Thumb function `target` (bit 0 ignored)."""
    off = (target & ~1) - (at + 4)
    assert -(1 << 24) <= off < (1 << 24) and off % 2 == 0, f"BL out of range {at:#x}->{target:#x}"
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    h1 = 0xF000 | (s << 10) | ((off >> 12) & 0x3FF)
    h2 = 0xD000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF)
    return struct.pack("<HH", h1, h2)


def bl_target(code, at):
    """Target of the BL encoded in `code` (4 bytes) at `at`, or None if it is not a BL."""
    h1, h2 = struct.unpack("<HH", code)
    if h1 >> 11 != 0b11110 or (h2 >> 14) & 0b11 != 0b11 or not (h2 >> 12) & 1:
        return None
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s:
        off -= 1 << 25
    return at + 4 + off


def symbols(elf):
    out = subprocess.run(["arm-none-eabi-nm", elf], capture_output=True, text=True, check=True).stdout
    return {name: int(addr, 16) for addr, kind, name in (l.split() for l in out.splitlines() if len(l.split()) == 3)}
