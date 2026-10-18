"""portkit merged into JOEBOX 1 (blackbox-mod, MIT, Justin Joe): one build, two files for the card.

  python3 bb/joebox/build.py [--groups a,b,..]   -> out/bb/jb/release/BLACKBOX.bin + BBEXTRA.BIN

--groups: the switchable groups to build in (bb/joebox/features.py); core groups always are. Default: all.
Each selection also lands in out/bb/jb/builds/<groups hash>/ (with build.json), the last one in out/bb/jb/release.

1. A clean export of blackbox-mod at the pinned commit (JOEBOX 1 rc4) into out/bb/jb/tree; our sources go into its
   src/ (bb/joebox/src: pk.h, pk_main.c and pk_thunk.S in bank 1, pk_dsp.c added to its bank 2 list) and its version
   name becomes "JB1+pk" (eight characters at most, release.h).
2. Its own build (RELEASE=1 ./build.sh: cave, bank 2 payload, pairing sum) and patch.py with the release's patchsets.
   Its stock check (SHA-256 of 3.1.9) runs there.
3. Our patchset (bb/joebox/patches/pk.py) on that image, checked like bb/patch.py: base bytes at every site, zero
   repack, only registered ranges changed, every BL / pointer lands on a symbol of the cave, image below 0x08100000.
Built with our toolchain the result is not byte-identical to the public JOEBOX 1 files; the sources are the same.
"""
import hashlib
import importlib
import json
import os
import shutil
import struct
import subprocess
import sys

JB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(JB))
MOD = os.path.join(ROOT, "repos", "blackbox-mod")
OUT = os.path.join(ROOT, "out", "bb", "jb")
TREE = os.path.join(OUT, "tree")
COMMIT = "66329ad"            # JOEBOX 1 (rc4), 2026-10-17
STOCK_SHA256 = "281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d"
MOD_SETS = "solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave".split()
NAME = "JB1+pk"
BASE = 0x08040000
CAVE_START = 0x080F1E78
FLASH_END = 0x08100000

sys.path.insert(0, os.path.join(ROOT, "patches"))
from thumb import bl_target, symbols  # noqa: E402
sys.path.insert(0, JB)
import features  # noqa: E402


def run(cmd, cwd=None, env=None):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


# JOEBOX sources changed for the SSL model (group pk_ssl): its Compressor list gains "SSL" (appended: stored values keep
# their meaning), comp_process hands that model to pk_ssl (pk_main.c, DSP in bank 2) where its own models run (after
# Master FX, before the clipper), and the Compressor knob page shows SSL's controls. Every edit is checked.
SSL_EDITS = [
    ("src/comp.c", '#include "clip.h"\n', '#include "clip.h"\n#include "pk_ids.h"\nvoid pk_ssl(float *l, float *r, int n);   /* portkit */\n'),
    ("src/comp.c", 'const char *const comp_names[3 + MODELS] = {"Off", "Stock", "Glue", "Punch", "Opto", "Squash", "Limit", "Smash"};',
     'const char *const comp_names[4 + MODELS] = {"Off", "Stock", "Glue", "Punch", "Opto", "Squash", "Limit", "Smash", "SSL"};'),
    ("src/comp.c", "fw_register_list(table, param, label, comp_names, 3 + MODELS, xml);",
     "fw_register_list(table, param, label, comp_names, 4 + MODELS, xml);"),
    ("src/comp.c", "    if (model < 2 || model > MODEL_SMASH) {\n",
     "    if (model == MODEL_SMASH + 1) {                         /* portkit: SSL */\n"
     "        n = out1(obj, bufs, &l, &r);\n"
     "        if (n > 0)\n"
     "            pk_ssl(l, r, n);\n"
     "        clip_stage(obj, bufs);\n"
     "        int *after = (int *)obj[2];\n"
     "        return after ? (*(chain_fn *)(*after + 0xc))(after, bufs) : 1;\n"
     "    }\n"
     "    if (model < 2 || model > MODEL_SMASH) {\n"),
    ("src/master.c", "#include <stdint.h>\n", "#include <stdint.h>\n#include \"pk_ids.h\"\n"),
    ("src/master.c", "static const uint16_t page_smash[] = {",
     "static const uint16_t page_ssl[] = {P_COMP, P_S_THRESH, P_S_RATIO, P_S_ATTACK, P_S_REL, P_S_GAIN, P_S_MIX, P_CLIPPER, 0};\n"
     "static const uint16_t page_smash[] = {"),
    ("src/master.c", "fw_setting(SETTINGS, P_COMP) == COMP_SMASH ? page_smash : page_comp;",
     "fw_setting(SETTINGS, P_COMP) == COMP_SMASH ? page_smash\n"
     "        : fw_setting(SETTINGS, P_COMP) == COMP_SMASH + 1 ? page_ssl : page_comp;"),
    # his test pins the list; SSL is the intended ninth entry
    ("test_comp.py", '"Limit", "Smash"] and (seen', '"Limit", "Smash", "SSL"] and (seen'),
    ("test_comp.py", "Opto, Squash, Limit, Smash (same", "Opto, Squash, Limit, Smash, SSL (portkit) (same"),
]


def edit_sources(groups):
    if "pk_ssl" not in groups:
        return
    for f, old, new in SSL_EDITS:
        p = os.path.join(TREE, f)
        s = open(p).read()
        assert s.count(old) == 1, f"JOEBOX source changed: {f}: {old[:60]!r}"
        open(p, "w").write(s.replace(old, new))


def make_tree():
    shutil.rmtree(TREE, ignore_errors=True)
    os.makedirs(TREE)
    tar = subprocess.run(["git", "-C", MOD, "archive", COMMIT], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", TREE], input=tar, check=True)
    stock = open(os.path.join(ROOT, "firmware", "BLACKBOX.bin"), "rb").read()
    assert hashlib.sha256(stock).hexdigest() == STOCK_SHA256, "firmware/BLACKBOX.bin is not stock 3.1.9"
    os.makedirs(os.path.join(TREE, "firmware"), exist_ok=True)
    open(os.path.join(TREE, "firmware", "BLACKBOX-3.1.9.bin"), "wb").write(stock)
    sys.path.insert(0, JB)
    import ids
    open(os.path.join(JB, "src", "pk_ids.h"), "w").write(ids.header())
    for f in os.listdir(os.path.join(JB, "src")):
        shutil.copyfile(os.path.join(JB, "src", f), os.path.join(TREE, "src", f))
    p = os.path.join(TREE, "build.sh")
    s = open(p).read()
    old = 'BANK2_SRCS="prism confetti insert_dsp rev4"'
    assert old in s, "blackbox-mod's build.sh changed: bank 2 list not found"
    open(p, "w").write(s.replace(old, 'BANK2_SRCS="prism confetti insert_dsp rev4 pk_dsp"'))
    p = os.path.join(TREE, "src", "release.h")
    s = open(p).read()
    assert '#define RELEASE_NAME "JOEBOX 1"' in s
    open(p, "w").write(s.replace('#define RELEASE_NAME "JOEBOX 1"', f'#define RELEASE_NAME "{NAME}"'))


def build_mod(sets):
    env = dict(os.environ, RELEASE="1")
    run(["sh", "build.sh"], cwd=TREE, env=env)
    run([sys.executable, "patch.py"] + sets, cwd=TREE)
    run(["sh", os.path.join("host", "build.sh")], cwd=TREE)      # host/libdsp.dylib for his test_*.py
    return os.path.join(TREE, "out", "+".join(sets), "BLACKBOX.bin")


def apply(base, sym, mod, groups):
    data = bytearray(base)
    ranges = []
    for addr, old, new in mod.patches(base, sym, groups):
        o = addr - BASE
        assert 0 <= o and o + len(old) <= len(base), f"{addr:#x} outside the image"
        assert data[o:o + len(old)] == old, f"base bytes differ at {addr:#x}: {data[o:o + len(old)].hex()} != {old.hex()}"
        assert len(old) == len(new), f"size change at {addr:#x}"
        assert not any(a < addr + len(new) and addr < b for a, b in ranges), f"overlapping patch at {addr:#x}"
        data[o:o + len(new)] = new
        ranges.append((addr, addr + len(new)))
        print(f"pk: {addr:#010x} {old.hex()} -> {new.hex()}")
    return data, ranges


def verify(base, data, ranges, sym, mod, groups):
    zero = bytearray(base)
    assert bytes(zero) == base
    assert len(data) == len(base), "the image grew"
    for o in range(len(base)):
        if data[o] != base[o]:
            assert any(lo <= BASE + o < hi for lo, hi in ranges), f"unregistered change at {BASE + o:#x}"
    end = BASE + len(data)
    assert end <= FLASH_END, f"image ends at {end:#x}, beyond flash bank 1"
    funcs = {v & ~1 for v in sym.values()}
    for at, name in mod.branches(groups):
        t = bl_target(bytes(data[at - BASE:at - BASE + 4]), at)
        assert t is not None and CAVE_START <= t < end and t in funcs and t == sym[name] & ~1, f"BL at {at:#x}"
    for at, name in mod.pointers(groups):
        v = int.from_bytes(data[at - BASE:at - BASE + 4], "little")
        assert CAVE_START <= v < end and v == sym[name], f"pointer at {at:#x} = {v:#x}"
    print("verify: all changes registered, detours and pointers land on cave symbols, image ends below bank 2")


def main(argv):
    sel = features.default()
    if "--groups" in argv:
        sel = set(x for x in argv[argv.index("--groups") + 1].split(",") if x)
    groups = features.resolve(sel)
    sets = [s for s in MOD_SETS if s in groups]
    make_tree()
    edit_sources(groups)
    img = build_mod(sets)
    base = open(img, "rb").read()
    sym = symbols(os.path.join(TREE, "out", "cave.elf"))
    assert "pk_clip_entry" in sym and "pk_wsola" in sym, "our sources are not in the cave / bank 2"
    sys.path.insert(0, os.path.join(JB, "patches"))
    mod = importlib.import_module("pk")
    data, ranges = apply(base, sym, mod, groups)
    verify(base, data, ranges, sym, mod, groups)
    key = hashlib.sha256(",".join(sorted(groups)).encode()).hexdigest()[:10]
    dirs = [os.path.join(OUT, "builds", key), os.path.join(OUT, "release")]
    info = {"groups": sorted(groups), "joebox_sets": sets, "name": NAME, "files": {}}
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "BLACKBOX.bin"), "wb").write(data)
        shutil.copyfile(os.path.join(TREE, "out", "BBEXTRA.BIN"), os.path.join(d, "BBEXTRA.BIN"))
    shutil.copyfile(os.path.join(TREE, "out", "cave.elf"), os.path.join(OUT, "cave.elf"))
    shutil.copyfile(os.path.join(TREE, "out", "bank2.bin"), os.path.join(OUT, "bank2.bin"))
    cave = os.path.getsize(os.path.join(TREE, "out", "cave.bin"))
    for f in ("BLACKBOX.bin", "BBEXTRA.BIN"):
        b = open(os.path.join(dirs[0], f), "rb").read()
        info["files"][f] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
        print(f"{f}: {len(b)} bytes, sha256 {hashlib.sha256(b).hexdigest()}")
    info["cave_free"] = 0xE188 - cave
    info["dir"] = dirs[0]
    for d in dirs:
        json.dump(info, open(os.path.join(d, "build.json"), "w"), indent=1)
    print(f"bank 1 cave {cave} of {0xE188} bytes ({0xE188 - cave} free)")
    print("BUILD-JSON " + json.dumps(info))


if __name__ == "__main__":
    main(sys.argv[1:])
