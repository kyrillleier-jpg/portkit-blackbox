"""Master distortion (bb/src/master.c): DSP on bus 0 before the master compressor, its five settings, a Tools tab
"Extra", and the version string marking the image (3.1.n -> 3.1.n+pkN). Sites: re/blackbox.md."""
import struct

from bbthumb import MOD, SYM, bl

HOOKS = [
    # shared with blackbox-mod: its BL is replaced, ours calls its function first
    (0x0808D350, MOD["comp_register"], "bb_register"),   # Compressor registration -> + Dist Type/Drive/Tone/Mix/Level
    (0x08094886, MOD["comp_defaults"], "bb_defaults"),   # global settings defaults -> + ours
]

THUNKS = [
    (0x08053528, "95f8603d", "dist_thunk"),             # ldrb.w r3, [r5, #0xd60]: compressor flag; bus 0 (r6) first
]

DIST_PAGE = struct.pack("<5H", 0x1E8, 0x1E9, 0x1EA, 0x1EB, 0x1EC)   # FX3 follows (fx3.py)

# (address, old word, cave symbol): pointers to our strings
WORDS = [
    (0x080EEE90, 0x080CB060, "tab_dist"),                # Tools tab name 4 ("" = no tab) -> "Extra"
    (0x0809AF30, 0x080CF290, "version_str"),             # the four users of the version string "3.1.n"
    (0x080AEAF4, 0x080CF290, "version_str"),
    (0x080C55E8, 0x080CF290, "version_str"),
    (0x080C72C8, 0x080CF290, "version_str"),
]

PATCHES = (
    [(at, bl(at, old), bl(at, SYM[name])) for at, old, name in HOOKS]
    + [(at, bytes.fromhex(old), bl(at, SYM[name])) for at, old, name in THUNKS]
    + [(0x080EEE38, bytes(len(DIST_PAGE)), DIST_PAGE)]  # Tools page 4 (empty in stock): the distortion's ids
    + [(0x080996D2, bytes.fromhex("032e"), bytes.fromhex("042e"))]   # list builder, code 0x40: cmp r6, #3 -> #4
    + [(0x08098D5A, bytes.fromhex("032e"), bytes.fromhex("042e"))]   # row builder, code 0x40: same limit
    + [(at, struct.pack("<I", old), struct.pack("<I", SYM[name])) for at, old, name in WORDS]
)
