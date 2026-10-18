"""Clip functions (bb/src/clip.c, bb/src/stretch.c): Shift, Play Len, Stretch + Stretch Mode (WSOLA), Loop Fade for
clips, Sync 1/32. Registration rides on bb_register (master.py); sites: re/blackbox.md "Clip"."""
import struct

from bbthumb import SYM, bl

P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE = 0x1ED, 0x1EE, 0x1EF, 0x1F0, 0x1F1
STORE_ADD = 0x08093EF6

HOOKS = [
    # pad record init 0x08093f20, both pad blocks: "add FX2 Send (0xda)" -> it, then the new parameters
    (0x08094112, STORE_ADD, "pad_store_add"),
    (0x08094346, STORE_ADD, "pad_store_add"),
    # Sync registration -> 8 entries (+ "1/32")
    (0x0808D104, 0x0808C0D8, "sync_register"),
    # smooth stretch: the slot reader's call of the clip reader
    (0x08066622, 0x080662E4, "clip_render"),
    # clip reader 0x080662e4 (pad r5) and the segment starts 0x08065290 / 0x08065550 (pad r4): shifted reads / seeks
    (0x0806636E, 0x08063634, "clip_read1_thunk"),
    (0x0806644E, 0x08063634, "clip_read1_thunk"),
    (0x080663BA, 0x08063608, "clip_read2_thunk"),
    (0x0806642C, 0x08063608, "clip_read2_thunk"),
    (0x0806541A, 0x0806375C, "clip_seek_thunk"),
    (0x0806578C, 0x0806375C, "clip_seek_thunk"),
]

THUNKS = [
    (0x08066E7A, "d6e99012", "clip_segments12"),   # ldrd r1, r2, [r6, #0x240]  (play length)
    (0x08066C46, "d6e99023", "clip_segments23"),   # ldrd r2, r3, [r6, #0x240]  (play length)
    (0x0806560C, "d4ed7f7a", "clip_seglen_thunk"), # vldr s15, [r4, #0x1fc]     (stretch: segment positions)
    (0x080655FE, "d4f84022", "clip_last_thunk"),   # ldr.w r2, [r4, #0x240]     (stretch: last segment)
]

# Sync's beats table (0x080ec82c, 7 entries) -> sync_beats (8) in the clip parameter handler's literal (0x08067ad6);
# the other user 0x080964c0 (preset reader, as 0x080808d8 on the micro) keeps the stock 7
WORDS = [(0x08067BB4, 0x080EC82C, "sync_beats")]

# pad record capacity 64 -> 72: `movs r1, #0x40` before the store allocation 0x08093e6a in the record init 0x08093f20
# and the record reset 0x080949e4 (clip record: 59 stock + 5 new = 64; the micro needed headroom on the device)
CAPACITY = [(0x08093F26, "4021", "4821"), (0x080949F0, "4021", "4821")]

# clip Pos page (page 1 of 5 x 36 ids, 2 leading halfwords per page): Loop Mode, Beat Count, Quant Size, Sync -> + ours
POS_PAGES = [0x080EF288, 0x080EF990]
POS = [0x8D, 0xD2, 0x47, 0x94]
NEW = [P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE]

PATCHES = (
    [(at, bl(at, stock), bl(at, SYM[name])) for at, stock, name in HOOKS]
    + [(at, bytes.fromhex(old), bl(at, SYM[name])) for at, old, name in THUNKS]
    + [(at, struct.pack("<I", old), struct.pack("<I", SYM[name])) for at, old, name in WORDS]
    + [(at, bytes.fromhex(old), bytes.fromhex(new)) for at, old, new in CAPACITY]
    + [(t, struct.pack("<10H", *POS, *[0] * 6), struct.pack("<10H", *POS, *NEW, 0)) for t in POS_PAGES]
)
