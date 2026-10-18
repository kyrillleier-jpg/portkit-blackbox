"""Shared helpers for the Blackbox patchsets: Thumb encoders (patches/thumb.py) and the symbol tables of our cave
(out/bb/cave.elf) and of blackbox-mod's (out/bb/base/mod_cave.elf)."""
import os
import sys

BB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BB)
sys.path.append(os.path.join(ROOT, "patches"))     # after bb/patches: same module names
from thumb import BASE, bl, bl_target, symbols  # noqa: E402,F401

SYM = symbols(os.path.join(ROOT, "out", "bb", "cave.elf"))
MOD = symbols(os.path.join(ROOT, "out", "bb", "base", "mod_cave.elf"))
