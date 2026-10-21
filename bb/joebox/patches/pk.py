"""portkit's patch sites on the JOEBOX 1 image (bb/joebox/build.py), by group (bb/joebox/features.py). Sites,
registers and reasons: re/blackbox.md ("Master", "Clip", "FX3", "JOEBOX 1"). Shared with JOEBOX and chained:
0x0808d350 (comp_register), 0x08094886 (comp_defaults), 0x08066622 (clip_read_b, or stock's reader when JOEBOX's
filter patchset is left out). Pad store / settings capacities: JOEBOX's own (96)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), "patches"))
from thumb import bl  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ids  # noqa: E402

BASE = 0x08040000
STORE_ADD = 0x08093EF6
STOCK_CLIP_READ = 0x080662E4

# registration, defaults, pad parameters: whenever any portkit group is in (parameters of groups that are out are
# registered and stored but never shown or used)
BASE_CALLS = [
    (0x0808D350, "comp_register", "bb_register"),
    (0x08094886, "comp_defaults", "bb_defaults"),
    (0x08094112, STORE_ADD, "pad_store_add"),
    (0x08094346, STORE_ADD, "pad_store_add"),
]
READS = [                                                # pk_shift, pk_lfade: the clip reader's stream reads / seeks
    (0x0806636E, 0x08063634, "clip_read1_thunk"),
    (0x0806644E, 0x08063634, "clip_read1_thunk"),
    (0x080663BA, 0x08063608, "clip_read2_thunk"),
    (0x0806642C, 0x08063608, "clip_read2_thunk"),
    (0x0806541A, 0x0806375C, "clip_seek_thunk"),
    (0x0806578C, 0x0806375C, "clip_seek_thunk"),
]
SEGMENTS = [                                             # pk_playlen, pk_stretch: the clip voice's loop tests
    (0x08066E7A, "d6e99012", "clip_segments12"),
    (0x08066C46, "d6e99023", "clip_segments23"),
]
STRETCH = [
    (0x0806560C, "d4ed7f7a", "clip_seglen_thunk"),
    (0x080655FE, "d4f84022", "clip_last_thunk"),
]
FX3_SENDS = [
    (0x08059ACE, "d3ed007a", "fx3_send_a"),
    (0x080688D0, "d3ed007a", "fx3_send_b"),
]
I = ids.ident
DIST_PAGE = [I("D_TYPE"), I("D_DRIVE"), I("D_TONE"), I("D_MIX"), I("D_LEVEL")]
FX3_PAGE = [I("R_TYPE"), I("R_DECAY"), I("R_DAMP"), I("R_PREDLY"), I("R_SIZE"), I("R_LEVEL")]
CONF_PAGES = [0x080EF090, 0x080EF1F8, 0x080EF360, 0x080EF4C8, 0x080EF630, 0x080EF900, 0x080EFA68, 0x080EFBD0,
              0x080EFD38]
POS_PAGES = [0x080EF288, 0x080EF990]
POS = [0x8D, 0xD2, 0x47, 0x94]
P_SHIFT, P_PLAYLEN, P_STRETCH, P_SMODE, P_LFADE, P_FX3SEND = (I(n) for n in ("SHIFT", "PLAYLEN", "STRETCH", "SMODE",
                                                                              "LFADE", "FX3SEND"))

# the parameter table: 500 slots -> ids.TABLE_SLOTS (all eleven places in the parameter module that hold its size:
# the insert's bound, the allocation and its clearing, seven accessors' bounds, the walk over all entries)
TABLE_SITES = [(0x0808C0AA, "cmp.w r2, #{n}"), (0x0808C162, "movw r0, #{b}"), (0x0808C174, "movw r2, #{b}"),
               (0x0808E224, "cmp.w r0, #{n}"), (0x0808E250, "cmp.w r0, #{n}"), (0x0808E27C, "cmp.w r0, #{n}"),
               (0x0808E2A8, "cmp.w r0, #{n}"), (0x0808E2D4, "cmp.w r0, #{n}"), (0x0808E308, "cmp.w r0, #{n}"),
               (0x0808E340, "cmp.w r0, #{n}"), (0x0808E384, "movw r5, #{b}")]


def asm(line):
    """one Thumb-2 instruction -> its bytes (arm-none-eabi-as)"""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        open(os.path.join(t, "a.s"), "w").write(f".syntax unified\n.thumb\n{line}\n")
        subprocess.run(["arm-none-eabi-as", "-mcpu=cortex-m7", "-o", os.path.join(t, "a.o"), os.path.join(t, "a.s")],
                       check=True)
        subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".text", os.path.join(t, "a.o"),
                        os.path.join(t, "a.bin")], check=True)
        return open(os.path.join(t, "a.bin"), "rb").read()


def _h(img, at):
    return struct.unpack_from("<H", img, at - BASE)[0]


def plan(groups):
    """(calls, thunks, pointers) for these groups: calls (site, old, ours), thunks (site, old bytes, ours)"""
    pk = {g for g in groups if g.startswith("pk_")}
    calls, thunks, ptrs = [], [], []
    global longs
    longs = []
    if not pk:
        return calls, thunks, ptrs
    calls += BASE_CALLS
    if pk & {"pk_shift", "pk_lfade"}:
        calls += READS
    if pk & {"pk_playlen", "pk_stretch"}:
        thunks += SEGMENTS
    if "pk_stretch" in pk:
        thunks += STRETCH
        if "filter" in groups:
            calls.append((0x08066622, "clip_read_b", "pk_clip_entry"))
        else:
            calls.append((0x08066622, STOCK_CLIP_READ, "pk_clip_entry_stock"))
    if "pk_sync32" in pk:
        calls.append((0x0808D104, 0x0808C0D8, "sync_register"))
        ptrs.append((0x08067BB4, 0x080EC82C, "sync_beats"))
    if "pk_dist" in pk:
        thunks.append((0x08053528, "95f8603d", "dist_thunk"))
    if pk & {"pk_fx3", "pk_fxrec"}:
        calls.append((0x08053516, 0x0804DA6C, "fx3_master"))        # FX sum (FX rec) and FX3
    if "pk_fx3" in pk:
        thunks += FX3_SENDS
    if "pk_hpout3" in pk:
        calls.append((0x0808D51C, 0x0808C12C, "out3_register"))     # Out 3 Vol registered up to 101 % (= mirror)
        calls.append((0x080A92B0, 0x080C89F4, "out3_text_thunk"))   # list row percent text: 101 % reads "Mirror HP"
        calls.append((0x080B0642, 0x080C89F4, "out3_text2_thunk"))  # ... and the Tools list's rows
    if "pk_recsends" in pk:
        calls.append((0x0809D5FA, 0x08094A1C, "rec_reinit"))         # recording: pad rebuilt, sends kept
    if "pk_fxrec" in pk:
        calls.append((0x0808D198, 0x0808C0D8, "rec_input_register")) # Rec Input (0x9a) + FX
        thunks.append((0x08062660, "032b03d0", "rec_mon_thunk"))      # cmp r3, #3; beq: Resam / FX skip the input
        longs.append((0x08062120, "032b00f02c83", "rec_src_thunk"))   # cmp r3, #3; beq.w tap: + FX source
        longs.append((0x0809B26A, "032818bf0028", "rec_stereo_thunk"))  # record start: FX is stereo too
    if pk & {"pk_dist", "pk_fx3"}:
        ptrs.append((0x080EEE90, 0x080CB060, "pk_tab"))
    return calls, thunks, ptrs


longs = []           # 6-byte sites: BL + nop (filled by plan)


def branches(groups):
    calls, thunks, _ = plan(groups)
    return ([(at, name) for at, _, name in calls] + [(at, name) for at, _, name in thunks]
            + [(at, name) for at, _, name in longs])


def pointers(groups):
    return [(at, name) for at, _, name in plan(groups)[2]]


def patches(img, sym, groups):
    calls, thunks, ptrs = plan(groups)
    out = []
    if any(g.startswith("pk_") for g in groups):
        for at, ins in TABLE_SITES:
            old = asm(ins.format(n=0x1F4, b=0x1F4 * 28))
            new = asm(ins.format(n=ids.TABLE_SLOTS, b=ids.TABLE_SLOTS * 28))
            assert len(old) == len(new) == 4, ins
            out.append((at, old, new))
    for at, old, name in calls:
        target = sym[old] if isinstance(old, str) else old
        out.append((at, bl(at, target), bl(at, sym[name])))
    for at, old, name in thunks:
        out.append((at, bytes.fromhex(old), bl(at, sym[name])))
    for at, old, name in longs:
        out.append((at, bytes.fromhex(old), bl(at, sym[name]) + bytes.fromhex("00bf")))
    for at, old, name in ptrs:
        out.append((at, struct.pack("<I", old), struct.pack("<I", sym[name])))
    page4 = (DIST_PAGE if "pk_dist" in groups else []) + (FX3_PAGE if "pk_fx3" in groups else [])
    if page4:
        assert len(page4) <= 11, "a Tools page holds 11 rows (re/blackbox.md)"
        out.append((0x080EEE38, bytes(2 * len(page4)), struct.pack(f"<{len(page4)}H", *page4)))
        out.append((0x080996D2, bytes.fromhex("032e"), bytes.fromhex("042e")))     # list builder, Tools: page <= 4
        out.append((0x08098D5A, bytes.fromhex("032e"), bytes.fromhex("042e")))     # row builder, Tools: page <= 4
    if "pk_fx3" in groups:
        for start in CONF_PAGES:
            end = start
            while _h(img, end):
                end += 2
            assert end - start <= 2 * 33, f"Conf page {start:#x} full"
            out.append((end, b"\0\0\0\0", struct.pack("<HH", P_FX3SEND, 0)))
    pos = [p for g, p in (("pk_shift", P_SHIFT), ("pk_playlen", P_PLAYLEN), ("pk_stretch", P_STRETCH),
                          ("pk_stretch", P_SMODE), ("pk_lfade", P_LFADE)) if g in groups]
    if pos:
        for t in POS_PAGES:
            out.append((t, struct.pack(f"<{len(POS) + len(pos) + 1}H", *POS, *[0] * (len(pos) + 1)),
                        struct.pack(f"<{len(POS) + len(pos) + 1}H", *POS, *pos, 0)))
    return out
