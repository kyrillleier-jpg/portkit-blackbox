"""Build the Blackbox port: blackbox-mod from source, then our add-on cave behind it.

  python3 bb/build.py            -> out/bb/base/BLACKBOX.bin (blackbox-mod, built here), out/bb/cave.elf / cave.bin

1. blackbox-mod (repos/blackbox-mod, MIT): its build.sh + patch.py with the release's patchset list (README). Its
   patch.py checks the stock 3.1.9 hash (repos/blackbox-mod/firmware/BLACKBOX-3.1.9.bin, a copy of
   firmware/BLACKBOX.bin). Built with our toolchain the cave is not byte-identical to the published 3.1.n json
   (26892 vs 26760 bytes), the sources are the same.
2. Our cave (bb/src) starts 8-aligned right after that image; blackbox-mod's functions that share a hook site with ours
   are linked by address (--defsym from its cave.elf).
"""
import hashlib
import os
import shutil
import subprocess
import sys

BB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BB)
MOD = os.path.join(ROOT, "repos", "blackbox-mod")
OUT = os.path.join(ROOT, "out", "bb")
BASE = 0x08040000
FLASH_END = 0x08100000          # end of flash bank 1; nothing is placed beyond it (bank 2 untested with the bootloader)
MOD_SETS = "solo slice duck chord cond filter cpu od comp seqfix fx2 munchi cave".split()
MOD_SYMS = ["comp_register", "comp_defaults"]
SOURCES = ["master.c", "master_thunk.S", "clip.c", "clip_thunk.S", "stretch.c", "reverb.c", "fx3.c", "fx3_thunk.S"]
CFLAGS = ["-mcpu=cortex-m7", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv5-d16", "-Os", "-ffreestanding", "-nostdlib",
          "-fno-builtin", "-Wall", "-Wextra", "-Werror"]


def run(cmd, cwd=None):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def nm(elf):
    out = subprocess.run(["arm-none-eabi-nm", elf], capture_output=True, text=True, check=True).stdout
    return {n: int(a, 16) for a, k, n in (l.split() for l in out.splitlines() if len(l.split()) == 3)}


def main():
    os.makedirs(os.path.join(OUT, "base"), exist_ok=True)
    stock = os.path.join(MOD, "firmware", "BLACKBOX-3.1.9.bin")
    if not os.path.exists(stock):
        os.makedirs(os.path.dirname(stock), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, "firmware", "BLACKBOX.bin"), stock)
    run(["sh", "build.sh"], cwd=MOD)
    run([sys.executable, "patch.py"] + MOD_SETS, cwd=MOD)
    base = os.path.join(OUT, "base", "BLACKBOX.bin")
    shutil.copyfile(os.path.join(MOD, "out", "+".join(MOD_SETS), "BLACKBOX.bin"), base)
    shutil.copyfile(os.path.join(MOD, "out", "cave.elf"), os.path.join(OUT, "base", "mod_cave.elf"))
    data = open(base, "rb").read()
    origin = (BASE + len(data) + 7) & ~7
    with open(os.path.join(OUT, "cave.ld"), "w") as f:
        f.write(f"MEMORY {{ CAVE (rx) : ORIGIN = {origin:#x}, LENGTH = {FLASH_END - origin:#x} }}\n"
                "SECTIONS {\n  .cave : { *(.text .text.* .rodata .rodata.*) } > CAVE\n"
                "  /DISCARD/ : { *(.data .data.* .bss .bss.* COMMON .ARM.exidx* .comment) }\n}\n")
    msym = nm(os.path.join(OUT, "base", "mod_cave.elf"))
    defs = [f"-Wl,--defsym,{s}={msym[s] | 1:#x}" for s in MOD_SYMS]
    elf = os.path.join(OUT, "cave.elf")
    run(["arm-none-eabi-gcc"] + CFLAGS + ["-T", os.path.join(OUT, "cave.ld"), "-Wl,-e,0"] + defs
        + ["-o", elf] + [os.path.join(BB, "src", s) for s in SOURCES])
    run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".cave", elf, os.path.join(OUT, "cave.bin")])
    size = os.path.getsize(os.path.join(OUT, "cave.bin"))
    print(f"base {len(data)} bytes (sha256 {hashlib.sha256(data).hexdigest()[:16]}), cave at {origin:#x}: {size} bytes, "
          f"{FLASH_END - origin - size} free to {FLASH_END:#x}")


if __name__ == "__main__":
    main()
