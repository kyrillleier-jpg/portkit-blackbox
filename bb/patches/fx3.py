"""FX3: a third send effect (bb/src/fx3.c, reverb.c, fx3_thunk.S): FX3 Send per pad (Conf pages), the reverb and its
settings on the Tools tab "Extra" after the distortion. Needs `master` and `clip` (registration, pad defaults).
Sites: re/blackbox.md "FX3"."""
import struct

from bbthumb import SYM, bl

HOOKS = [
    (0x08053516, 0x0804DA6C, "fx3_master"),   # block function: bus 0 += bus 0xb (FX2 return), then += FX3
]

THUNKS = [
    (0x08059ACE, "d3ed007a", "fx3_send_a"),   # vldr s15, [r3]: sample pads' FX2 gain; scratch [sp, #0x18], pad r4
    (0x080688D0, "d3ed007a", "fx3_send_b"),   # clip pads'; scratch [sp, #0x14], pad r4
]

# global settings store capacity 64 -> 80 (`movs r1, #0x40` in the settings init 0x0809481c): 44 stock and mod + 5
# distortion + 15 FX3 = 64
CAPACITY = [(0x08094820, "4021", "5021")]

# Tools page 4 after the five distortion ids (master.py): FX3 Type, Decay, Damping, Pre-Delay, Size, Level. At most 11
# entries per Tools page: the list builder 0x080996b0 writes ids (+2 ..) and values (+0x14 ..) into a structure whose
# tab count (+0x44) and tab names (+0x4d) follow; 20 entries overwrote them (tab stuck, simulation). 11 = blackbox-mod's
# Main page. The other FX3 settings (Diffusion .. Lo Cut) keep their defaults; settings.tml sets them (pkfx3diff, ..).
FX3_PAGE = [0x1B8, 0x1B9, 0x1BA, 0x1BB, 0x1BC, 0x1C6]
PAGE4_AT = 0x080EEE38 + 5 * 2

# Conf page of every pad mode (list ends; the halfword after is 0): + FX3 Send
CONF_ENDS = [0x080EF0A0, 0x080EF208, 0x080EF370, 0x080EF4DC, 0x080EF640, 0x080EF912, 0x080EFA7A, 0x080EFBE2,
             0x080EFD4C]
P_FX3SEND = 0x1F2

PATCHES = (
    [(at, bl(at, stock), bl(at, SYM[name])) for at, stock, name in HOOKS]
    + [(at, bytes.fromhex(old), bl(at, SYM[name])) for at, old, name in THUNKS]
    + [(at, bytes.fromhex(old), bytes.fromhex(new)) for at, old, new in CAPACITY]
    + [(PAGE4_AT, bytes(2 * len(FX3_PAGE)), struct.pack(f"<{len(FX3_PAGE)}H", *FX3_PAGE))]
    + [(at, b"\0\0\0\0", struct.pack("<HH", P_FX3SEND, 0)) for at in CONF_ENDS]
)
