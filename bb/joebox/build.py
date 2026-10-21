"""portkit merged into JOEBOX 1 (blackbox-mod, MIT, Justin Joe): one build, two files for the card.

  python3 bb/joebox/build.py [--groups a,b,..]   -> out/bb/jb/release/BLACKBOX.bin + BBEXTRA.BIN

--groups: the switchable groups to build in (bb/joebox/features.py); core groups always are. Default: all.
--diag: JOEBOX's diagnostic build (FAULT_SHOW): a crash or watchdog reset shows its record on the screen and holds;
  version "JBpkDIAG", output in out/bb/jb/release-diag (with cave.elf to read the addresses).
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


# Rec Input: USB (pk_usbin). JOEBOX's USB device (src/usbdev.c) gets a second audio streaming interface: the computer
# sends 2 x 24 bit at 48 kHz on endpoint 3 (isochronous OUT, adaptive), bank 1's usbin_* hooks take it (pk_main.c).
# MIDI streaming moves from interface 2 to 3. bcdDevice 1.01, so a host that cached the old descriptors reads them again.
USBIN_EDITS = [
    ("src/usbdev.c", "uint8_t *master_block(void);     /* master.c: the SDRAM block taken at boot, or 0 */\n",
     "uint8_t *master_block(void);     /* master.c: the SDRAM block taken at boot, or 0 */\n"
     "void usbin_reset(void);          /* portkit pk_main.c: audio from the computer on endpoint 3 */\n"
     "void usbin_open(int on);\nint usbin_alt(void);\nvoid usbin_rx(unsigned bytes);\nvoid usbin_done(void);\n"),
    ("src/usbdev.c", "    0x00, 0x01, 1, 2, 0, 1,\n", "    0x01, 0x01, 1, 2, 0, 1,      /* bcdDevice 1.01: portkit's audio from the computer */\n"),
    ("src/usbdev.c", "static const uint8_t CONFIG[175] = {\n    9, 2, 175, 0, 3, 1, 0, 0x80, 250,\n",
     "static const uint8_t CONFIG[249] = {\n    9, 2, 249, 0, 4, 1, 0, 0x80, 250,\n"),
    ("src/usbdev.c", "    10, 0x24, 1, 0x00, 0x01, 31, 0, 2, 1, 2,     /* control header: streaming interfaces 1 and 2 */\n",
     "    11, 0x24, 1, 0x00, 0x01, 53, 0, 3, 1, 2, 3,  /* control header: streaming interfaces 1, 2 (portkit) and 3 */\n"),
    ("src/usbdev.c", "    9, 0x24, 3, 2, 0x01, 0x01, 0, 1, 0,          /* terminal 2: USB streaming, fed by 1 */\n",
     "    9, 0x24, 3, 2, 0x01, 0x01, 0, 1, 0,          /* terminal 2: USB streaming, fed by 1 */\n"
     "    12, 0x24, 2, 3, 0x01, 0x01, 0, 2, 0x03, 0, 0, 0,   /* portkit: terminal 3: USB streaming in, stereo */\n"
     "    9, 0x24, 3, 4, 0x03, 0x06, 0, 3, 0,          /* portkit: terminal 4: line connector, fed by 3 */\n"),
    ("src/usbdev.c", "    7, 0x25, 1, 0, 0, 0, 0,\n    9, 4, 2, 0, 2, 1, 3, 0, 0,                   /* MIDI streaming */\n",
     "    7, 0x25, 1, 0, 0, 0, 0,\n"
     "    9, 4, 2, 0, 0, 1, 2, 0, 0,                   /* portkit: audio from the computer, alt 0: closed */\n"
     "    9, 4, 2, 1, 1, 1, 2, 0, 0,                   /* alt 1: one endpoint */\n"
     "    7, 0x24, 1, 3, 1, 1, 0,                      /* to terminal 3, PCM */\n"
     "    11, 0x24, 2, 1, 2, 3, 24, 1, 0x80, 0xbb, 0x00,   /* stereo, 3-byte samples, 24 bits, 48000 only */\n"
     "    9, 5, 0x03, 0x09, 0x26, 0x01, 1, 0, 0,       /* isochronous OUT, adaptive, up to 294 bytes every frame */\n"
     "    7, 0x25, 1, 0, 0, 0, 0,\n"
     "    9, 4, 3, 0, 2, 1, 3, 0, 0,                   /* MIDI streaming */\n"),
    ("src/usbdev.c", "        uint32_t st = GRXSTSP, bytes = (st >> 4) & 0x7ffu, kind = (st >> 17) & 0xfu, ep = st & 0xfu;\n",
     "        uint32_t st = GRXSTSP, bytes = (st >> 4) & 0x7ffu, kind = (st >> 17) & 0xfu, ep = st & 0xfu;\n"
     "        if (ep == 3 && (kind == 2 || kind == 3)) {         /* portkit: audio from the computer */\n"
     "            if (kind == 2)\n                usbin_rx(bytes);\n            else\n                usbin_done();\n"
     "            continue;\n        }\n"),
    ("src/usbdev.c", "    if (ints & RXFLVL)\n        receive();\n",
     "    if (ints & RXFLVL)\n        receive();\n"
     "    if (GINTSTS & (1u << 21)) {                              /* portkit: endpoint 3 missed its frame: arm again */\n"
     "        GINTSTS = 1u << 21;\n        usbin_done();\n    }\n"),
    ("src/usbdev.c", "        if (type == 0x01 && S->setup[4] == 1)                /* the audio stream opens (alt 1) or closes */\n"
                     "            audio_open(lo == 1);\n",
     "        if (type == 0x01 && S->setup[4] == 1)                /* the audio stream opens (alt 1) or closes */\n"
     "            audio_open(lo == 1);\n"
     "        else if (type == 0x01 && S->setup[4] == 2)           /* portkit: audio from the computer */\n"
     "            usbin_open(lo == 1);\n"),
    ("src/usbdev.c", "        buf[0] = S->setup[4] == 1 ? S->alt : 0;\n",
     "        buf[0] = S->setup[4] == 1 ? S->alt : S->setup[4] == 2 ? (uint8_t)usbin_alt() : 0;\n"),
    ("src/usbdev.c", "        S->config = (uint8_t)lo;\n        audio_open(0);\n",
     "        S->config = (uint8_t)lo;\n        audio_open(0);\n        usbin_open(0);\n"),
    ("src/usbdev.c", "        S->config = 0;\n        audio_open(0);\n",
     "        S->config = 0;\n        audio_open(0);\n        usbin_open(0);\n"),
    ("src/usbdev.c", "    GRXFSIZ = 0x80;\n    DIEPTXF0 = (0x40u << 16) | 0x80u;\n    DIEPTXF1 = (0x40u << 16) | 0xc0u;\n"
                     "    DIEPTXF2 = (0x100u << 16) | 0x100u;                      /* 1024 bytes: one audio packet is at most 882 */\n"
                     "    S->alt = 0;\n",
     "    GRXFSIZ = 0x100;                                         /* portkit: room for an audio packet from the computer */\n"
     "    DIEPTXF0 = (0x40u << 16) | 0x100u;\n    DIEPTXF1 = (0x40u << 16) | 0x140u;\n"
     "    DIEPTXF2 = (0x100u << 16) | 0x180u;                      /* 1024 bytes: one audio packet is at most 882 */\n"
     "    S->alt = 0;\n    usbin_reset();\n"),
    # his test of the device: the descriptor grows by the new interface, MIDI is interface 3, SRAM4 holds our state
    ("test_usbdev.py", "e.uc.mem_map(0x38800000, 0x1000)\n", "e.uc.mem_map(0x38800000, 0x1000)\ne.uc.mem_map(0x38000000, 0x10000)   # portkit: SRAM4 (USB in)\n"),
    ("test_usbdev.py", 'check("configuration descriptor header (9 bytes asked): total length 175, three interfaces", d and len(d) == 9 and d[2] == 175 and d[4] == 3, d)',
     'check("configuration descriptor header (9 bytes asked): total length 249, four interfaces (portkit)", d and len(d) == 9 and d[2] == 249 and d[4] == 4, d)'),
    ("test_usbdev.py", 'check("whole configuration: 175 bytes over three packets (64 + 64 + 47), one per block", d and len(d) == 175 and core.chunks == [64, 64, 47], (d and len(d), core.chunks))',
     'check("whole configuration: 249 bytes over four packets (64 + 64 + 64 + 57), one per block", d and len(d) == 249 and core.chunks == [64, 64, 64, 57], (d and len(d), core.chunks))'),
    ("test_usbdev.py", "      used == 175 and len(ms) == 1 and ms[0][2] == 2 and ms[0][4] == 2\n"
                       "      and [(x[2], x[3], x[4] | x[5] << 8) for x in eps] == [(0x82, 5, 882), (1, 2, 64), (0x81, 2, 64)], parts)",
     "      used == 249 and len(ms) == 1 and ms[0][2] == 3 and ms[0][4] == 2\n"
     "      and [(x[2], x[3], x[4] | x[5] << 8) for x in eps] == [(0x82, 5, 882), (3, 9, 294), (1, 2, 64), (0x81, 2, 64)], parts)"),
    ("test_usbdev.py", "ac = [x for x in parts if x[1] == 0x24 and x[2] == 1 and len(x) == 10][0]",
     "ac = [x for x in parts if x[1] == 0x24 and x[2] == 1 and len(x) == 11][0]"),
    ("test_usbdev.py", 'check("audio control header: its length field covers itself + both terminals (31), and it lists interfaces 1 and 2",\n'
                       "      ac[5] == sum(len(x) for x in parts[ac_i:ac_i + 3]) == 31 and list(ac[7:10]) == [2, 1, 2], ac)",
     'check("audio control header: its length field covers itself + four terminals (53), and it lists interfaces 1, 2, 3",\n'
     "      ac[5] == sum(len(x) for x in parts[ac_i:ac_i + 5]) == 53 and list(ac[7:11]) == [3, 1, 2, 3], ac)"),
    ("test_usbdev.py", "      alts == [(1, 0, 0), (1, 1, 1)] and 49 * 6 * 3 == 882, alts)",
     "      alts == [(1, 0, 0), (1, 1, 1), (2, 0, 0), (2, 1, 1)] and 49 * 6 * 3 == 882, alts)"),
    # a pad's live input: "USB" as a fifth source (appended: saved values keep their meaning)
    ("src/insert.h", "enum { IN_OFF, IN_LEFT, IN_RIGHT, IN_STEREO, IN_SOURCES };",
     "enum { IN_OFF, IN_LEFT, IN_RIGHT, IN_STEREO, IN_USB, IN_SOURCES };   /* IN_USB: portkit */"),
    ("src/insert.c", 'static const char *const in_names[IN_SOURCES] = {"Off", "In 1", "In 2", "In 1+2"};',
     'static const char *const in_names[IN_SOURCES] = {"Off", "In 1", "In 2", "In 1+2", "USB"};\n'
     "void usbin_add(float *l, float *r, int n);       /* portkit pk_main.c: the computer's stream (Rec Input USB's) */"),
    ("src/insert.c", "static void add_input(const struct ins_set *p, float *l, float *r, int n)\n{\n",
     "static void add_input(const struct ins_set *p, float *l, float *r, int n)\n{\n"
     "    if (p->input == IN_USB) {                                /* portkit: from the computer, not the ADC */\n"
     "        usbin_add(l, r, n);\n        return;\n    }\n"),
    ("test_insert.py", 'check("registered: Insert (Off, Phaser, Flanger, Gate), Input (Off, In 1, In 2, In 1+2), a Model list per effect",',
     'check("registered: Insert (Off, Phaser, Flanger, Gate), Input (Off, In 1, In 2, In 1+2, USB: portkit), a Model list per effect",'),
    ("test_insert.py", '(0x1C7, "Input:", ["Off", "In 1", "In 2", "In 1+2"]),',
     '(0x1C7, "Input:", ["Off", "In 1", "In 2", "In 1+2", "USB"]),'),
    ("test_usbdev.py", "r = control(struct.pack(\"<BBHHH\", 0x01, 11, 0, 2, 0))\n",
     "r = control(struct.pack(\"<BBHHH\", 0x01, 11, 0, 3, 0))         # portkit: MIDI is interface 3\n"),
]


# Performance macros MAC1..MAC4 (pk_macro, needs JOEBOX's duck and solo). duck.c: four more modulation sources (engine
# mod5..mod8, codes 0x13..0x16; the Source list 16 -> 20 in its four places) and their values each block; solo.c: the
# Pads screen's lower-right knob gets a fourth position: 0 = the macro buttons (where the Velocity slider was), 1 =
# clipboard, 2 = MUTE / SOLO, 3 = the Velocity slider.
MACRO_EDITS = [
    ("src/duck.c", "void insert_tick(void);          /* insert.c: one pad's insert settings per block */\n",
     "void insert_tick(void);          /* insert.c: one pad's insert settings per block */\n"
     "void macro_tick(uint8_t *engine, float dt);   /* portkit pk_main.c: performance macros MAC1..MAC4 */\n"),
    ("src/duck.c", "    lfo_tick(now);\n", "    macro_tick(engine, dt);\n    lfo_tick(now);\n"),
    ("src/duck.c", "const char *const duck_source_names[16] = {", "const char *const duck_source_names[20] = {"),
    ("src/duck.c", '    "EXP1", "EXP2", "PUMP", "LINR",\n',
     '    "EXP1", "EXP2", "PUMP", "LINR",\n    "MAC1", "MAC2", "MAC3", "MAC4",              /* portkit: performance macros */\n'),
    ("src/duck.c", "const uint16_t duck_source_codes[16] = {", "const uint16_t duck_source_codes[20] = {"),
    ("src/duck.c", "    0x12, 0x11, 0x10, 0xf,                       /* mod4, mod3, mod2, mod1 */\n",
     "    0x12, 0x11, 0x10, 0xf,                       /* mod4, mod3, mod2, mod1 */\n"
     "    0x13, 0x14, 0x15, 0x16,                      /* portkit: mod5..mod8 = MAC1..MAC4 */\n"),
    ("patches/duck.py", 'bytes.fromhex("10210091")),', 'bytes.fromhex("14210091")),  # portkit: 20 (MAC1..4)'),
    ("patches/duck.py", 'bytes.fromhex("102b")),', 'bytes.fromhex("142b")),  # portkit: 20'),
    ("patches/duck.py", 'bytes.fromhex("1020")),', 'bytes.fromhex("1420")),  # portkit: 20'),
    ("patches/solo.py", 'bytes.fromhex("0321")),', 'bytes.fromhex("0421")),  # portkit: 4 positions (+ macros)'),
    ("src/solo.c", "#define ID_BLANK 0x1f3\n",
     "#define ID_BLANK 0x1f3\n#define ID_MAC1  0x1f4  /* portkit: 0x1f4..0x1f7 = MAC1..MAC4 */\n"
     "void macro_click(uint8_t *view, unsigned k);   /* portkit pk_main.c */\nvoid macro_lights(uint8_t *view);\n"
     "void pads_panels(uint8_t *view);\n"),
    ("src/solo.c", "    unsigned id = msg[6];\n",
     "    unsigned id = msg[6];\n"
     "    if (id >= ID_MAC1 && id < ID_MAC1 + 4) {                /* portkit: a macro button */\n"
     "        if (msg[0] == 2)\n            macro_click(view, id - ID_MAC1);\n        return 0;\n    }\n"),
    ("src/solo.c", "    fw_pads_msg(view, msg);\n",
     "    fw_pads_msg(view, msg);\n"
     "    if (msg && msg[0] == 0x67)                               /* portkit: the screen is shown: its panel as set */\n"
     "        pads_panels(view);\n"),
    ("src/solo.c", "    if (pos > 0)\n", "    if (pos != 3)                                            /* portkit: 3 = the slider */\n"),
    ("src/solo.c", "            fw_label(b, pos == 2 ? mute[k] : clip[k]);\n"
                   "            *(uint32_t *)(b + BTN_ID) = pos == 2 ? mute_id[k] : clip_id[k];\n",
     "            static const char *const mac[4] = {\"MAC4\", \"MAC3\", \"MAC2\", \"MAC1\"};   /* portkit: btn_at[0] is the\n"
     "                                                     bottom one on the glass (Renode), so MAC1 goes on top */\n"
     "            fw_label(b, pos == 0 ? mac[k] : pos == 2 ? mute[k] : clip[k]);\n"
     "            *(uint32_t *)(b + BTN_ID) = pos == 0 ? ID_MAC1 + 3u - (unsigned)k : pos == 2 ? mute_id[k] : clip_id[k];\n"),
    # his tests: 20 sources, four knob positions (0 = macros, 3 = the slider), SRAM4 for the macro state
    ("test_duck.py", 'check("the three list-length patches say 16", img[0x0808CB3E - BASE] == 0x10 and img[0x080B67CC - BASE] == 0x10 and img[0x080B7994 - BASE] == 0x10)',
     'check("the three list-length patches say 20 (portkit: + MAC1..MAC4)", img[0x0808CB3E - BASE] == 0x14 and img[0x080B67CC - BASE] == 0x14 and img[0x080B7994 - BASE] == 0x14)'),
    ("test_duck.py", "e.uc.mem_map(0x38800000, 0x1000)                         # backup SRAM + its clock: lfo.c looks for its memory there\n",
     "e.uc.mem_map(0x38800000, 0x1000)                         # backup SRAM + its clock: lfo.c looks for its memory there\n"
     "e.uc.mem_map(0x38000000, 0x10000)                        # portkit: SRAM4 (macro state)\n"),
    ("test_duck.py", 'check("the three list counts are 16", img[0x0808CB3E - BASE:0x0808CB40 - BASE] == bytes.fromhex("1021") and img[0x080B67CC - BASE:0x080B67CE - BASE] == bytes.fromhex("102b")\n'
                     '      and img[0x080B7994 - BASE:0x080B7996 - BASE] == bytes.fromhex("1020"))',
     'check("the three list counts are 20 (portkit)", img[0x0808CB3E - BASE:0x0808CB40 - BASE] == bytes.fromhex("1421") and img[0x080B67CC - BASE:0x080B67CE - BASE] == bytes.fromhex("142b")\n'
     '      and img[0x080B7994 - BASE:0x080B7996 - BASE] == bytes.fromhex("1420"))'),
    ("test_solo.py", "uc.mem_map(0x24000000, 0x80000)\n", "uc.mem_map(0x24000000, 0x80000)\nuc.mem_map(0x38000000, 0x10000)   # portkit: SRAM4 (macro state)\n"),
    ("test_solo.py", 'check("the column stepper has three positions", IMG[0x080B4704 - BASE:0x080B4706 - BASE] == bytes.fromhex("0321"))',
     'check("the column stepper has four positions (portkit: + macros)", IMG[0x080B4704 - BASE:0x080B4706 - BASE] == bytes.fromhex("0421"))'),
    ("test_solo.py", 'check("position 0: Velocity slider shown, buttons hidden, nothing relabelled", c == [("hide", SLIDER, 0), ("hide", BUTTONS, 1)], c)\n'
                     'check("...and no button left lit", lit == {0x214: 0, 0x174: 0}, lit)',
     'check("position 0 (portkit): buttons read MAC4..MAC1 in panel order (MAC1 on top), ids 0x1f7..0x1f4, slider hidden, panel shown",\n'
     '      [x[2] for x in c if x[0] == "label"] == ["MAC4", "MAC3", "MAC2", "MAC1"] and ids() == [0x1F7, 0x1F6, 0x1F5, 0x1F4]\n'
     '      and [x for x in c if x[0] == "hide"] == [("hide", SLIDER, 1), ("hide", BUTTONS, 0)], (c, ids()))\n'
     'check("...and no button left lit", lit and all(v == 0 for v in lit.values()), lit)\n'
     'c = r6_call(3)\n'
     'check("position 3 (portkit): Velocity slider shown, buttons hidden, nothing relabelled", c == [("hide", SLIDER, 0), ("hide", BUTTONS, 1)], c)'),
    ("src/solo.c", "    pads_lights(view);\n    (*(hide_fn *)(*(uint8_t **)slider + 0x2c))(slider, pos != 0);\n"
                   "    (*(hide_fn *)(*(uint8_t **)buttons + 0x2c))(buttons, pos == 0);\n",
     "    pads_lights(view);\n    if (pos == 0)\n        macro_lights(view);                                  /* portkit */\n"
     "    (*(hide_fn *)(*(uint8_t **)slider + 0x2c))(slider, pos != 3);\n"
     "    (*(hide_fn *)(*(uint8_t **)buttons + 0x2c))(buttons, pos == 3);\n"),
]


def edit_sources(groups):
    open(os.path.join(TREE, "src", "pk_groups.h"), "w").write(
        "/* generated by bb/joebox/build.py: the portkit groups of this build */\n"
        f"#define PK_HAS_USBIN {int('pk_usbin' in groups)}\n")
    edits = ((SSL_EDITS if "pk_ssl" in groups else []) + (USBIN_EDITS if "pk_usbin" in groups else [])
             + (MACRO_EDITS if "pk_macro" in groups else []))
    for f, old, new in edits:
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


def build_mod(sets, diag=False):
    env = dict(os.environ, RELEASE="1")
    if diag:                                    # JOEBOX fault.c: a crash / watchdog reset draws its record and holds
        env["FAULT_SHOW"] = "1"
        p = os.path.join(TREE, "src", "cpu.c")
        c = open(p).read()
        assert c.count('const char fw_version[] = "JOE DIAG";') == 1
        open(p, "w").write(c.replace('const char fw_version[] = "JOE DIAG";', 'const char fw_version[] = "JBpkDIAG";'))
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
    diag = "--diag" in argv
    sets = [s for s in MOD_SETS if s in groups]
    make_tree()
    edit_sources(groups)
    img = build_mod(sets, diag)
    base = open(img, "rb").read()
    sym = symbols(os.path.join(TREE, "out", "cave.elf"))
    assert "pk_clip_entry" in sym and "pk_wsola" in sym, "our sources are not in the cave / bank 2"
    sys.path.insert(0, os.path.join(JB, "patches"))
    mod = importlib.import_module("pk")
    data, ranges = apply(base, sym, mod, groups)
    verify(base, data, ranges, sym, mod, groups)
    key = hashlib.sha256(",".join(sorted(groups)).encode()).hexdigest()[:10]
    tag = "-diag" if diag else ""
    dirs = [os.path.join(OUT, "builds", key + tag), os.path.join(OUT, "release" + tag)]
    info = {"groups": sorted(groups), "joebox_sets": sets, "name": "JBpkDIAG" if diag else NAME, "files": {}}
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "BLACKBOX.bin"), "wb").write(data)
        shutil.copyfile(os.path.join(TREE, "out", "BBEXTRA.BIN"), os.path.join(d, "BBEXTRA.BIN"))
        shutil.copyfile(os.path.join(TREE, "out", "cave.elf"), os.path.join(d, "cave.elf"))   # to read crash PCs
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
