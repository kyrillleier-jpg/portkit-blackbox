# portkit + JOEBOX 1 (Blackbox 3.1.9)

portkit's Blackbox features merged into [blackbox-mod](https://github.com/j3threejay/blackbox-mod) **JOEBOX 1** (rc4,
commit 66329ad, MIT, Justin Joe). Everything from JOEBOX 1 stays (live input, per-pad inserts, LFO 2/3, ENV/KEY,
Master FX VHS/Prism, delay types Motion/Relapse/Confetti, Smash, clipper, pre-roll, rotate, MUTE/SOLO, USB audio/MIDI,
load readout, …). Added by portkit (same as 3.1.n+pk3, see `bb/README.md`):

- **Master distortion**: Tools → tab **Extra**: Dist Type, Drive, Tone, Mix, Level.
- **FX3** (third send, own reverb Plate/Room/Hall/Chamber): pad → Conf → **FX3 Send**; Tools → Extra: FX3 Type,
  Decay, Damp, PreDly, Size, Level. Diffusion, Bass, Crossover, Mod, Early, Width, Hi/Lo Cut are fixed at the 3.1.n
  defaults (no room for more parameter ids).
- **Clip functions**: clip pad → Pos: Shift ms, Play Len, Stretch %, Str Mode (Auto/Jump/Smooth = WSOLA), Loop Fade;
  Sync 1/32.
- **SSL compressor**: Tools → Compressor: **SSL** (ninth model), INFO = Thresh, Ratio 2/4/10, Attack, Release
  (incl. Auto), Gain, Mix, Clipper. Same DSP as the micro's (bit-compared in test_jb.py).
- **Recording**: the pad record rebuilt while recording keeps its FX1/FX2/FX3 sends; **Rec Input: FX** records only
  the effect returns (FX1 + FX2 + FX3), stereo.
- **Rec Input: USB** (group `pk_usbin`): JOEBOX's USB device gets a second audio interface, computer → Blackbox,
  stereo 24 bit / 48 kHz (endpoint 3, isochronous OUT, adaptive); the record source takes it rate-matched (PI loop,
  Hermite interpolation, 8 ms buffer). Build-time edits of JOEBOX's `usbdev.c` and `test_usbdev.py`: `USBIN_EDITS`
  in `build.py`. Details: `re/blackbox.md` "Rec Input: USB". Not tested on a unit yet.
- Version on splash and Tools: **JB1+pk** (JOEBOX allows eight characters).
- Every feature group can be switched off: `bb/joebox/features.py`, `build.py --groups`, the dashboard
  (`python3 bb/joebox/dashboard.py` → http://127.0.0.1:8765).

Signal order on Out 1: pads (with JOEBOX inserts) → FX1/FX2 returns → **FX3** → **Distortion** → JOEBOX Master FX →
compressor → clipper.

## Two files

Like JOEBOX 1 this is `BLACKBOX.bin` + `BBEXTRA.BIN`; both go into the card root, BACK + INFO at power-on, the unit
restarts once while JOEBOX's loader writes flash bank 2. The pair is matched (JOEBOX's pairing sum): a `BBEXTRA.BIN`
from the public JOEBOX 1 does **not** fit this `BLACKBOX.bin`. Without a matching bank 2, JOEBOX shows `!` in front of
the load, its Prism / Confetti / inserts are off, and portkit's Distortion, FX3, Smooth stretch and Loop Fade pass
the audio through untouched (Shift, Play Len, Jump stretch and Sync 1/32 still work: they are in bank 1).

## Build

```
python3 bb/joebox/build.py [--groups a,b]   # -> out/bb/jb/release/BLACKBOX.bin + BBEXTRA.BIN
python3 -I tests/smoke_jb.py                 # any selection
python3 -I tests/manifest_jb.py              # -> params.json: every parameter the build registers, by xml name
python3 -I tests/test_jb.py                  # all groups
```

`build.py` exports the pinned JOEBOX commit, adds `bb/joebox/src` (bank 1: `pk_main.c`, `pk_thunk.S`; bank 2:
`pk_dsp.c`, added to JOEBOX's `BANK2_SRCS`), runs JOEBOX's own `build.sh` (RELEASE=1) and `patch.py`, then applies
`bb/joebox/patches/pk.py` with the usual checks. JOEBOX's 30 test suites pass on the merged tree
(`out/bb/jb/tree/test_*.py`, needs numpy and scipy; `build.py` also builds his `host/libdsp.dylib`; with SSL his
`test_comp.py` is told about the ninth model).

Space: bank 1 (the part the 1010music installer checks, must end before 0x08100000) has 336 bytes left (all groups); that is why
the DSP lives in bank 2.

## Parameter ids, presets, other builds

- The parameter table is grown from 500 to 600 slots (11 sites in the parameter module, `TABLE_SITES` in
  `patches/pk.py`); portkit's ids start at 0x200, above everything stock and JOEBOX register. `ids.py` is the only
  place they are decided (generates `src/pk_ids.h`).
- Presets (`preset.xml`, per pad) and `settings.tml` (global) store integers **by xml name** (checked on presets
  saved by a 3.1.x unit). Ids can move between builds; the xml names (`pkshift`, `pksslthresh`, …) never change.
- Every list portkit or JOEBOX extend is extended at the end (Sync 1/32, Compressor SSL, Rec Input FX, Fidelity
  modes, FX2 Room), so a saved index means the same entry in every build that has it.
- A build without a feature: its parameters are not registered; the firmware ignores them on load (they stay in the
  file until that preset is saved again: nicht verifiziert). A list index past the end:
  `python3 -I bb/joebox/convert.py <SD-Root>` reports it, `--apply` sets the nearest stock entry (1/32 → 1/16,
  SSL → Glue, FX → Resam, Fidelity modes → Normal) after zipping the files it changes; only those values are
  rewritten, every other byte stays. Also in the dashboard (panel "Presets an diesen Build anpassen").
- Not handled: JOEBOX's Note Conditions (`evtcond`) put ALWAYS at index 99 instead of 0; the converter only
  reports presets with conditions.

## What changed against 3.1.n+pk3

- Parameter ids: see above. **Saved settings and presets from pk3 keep their xml names** (pkddrive, pkshift, …)
  and are read back under the new ids.
- Capacities: JOEBOX's own (96 for settings and pad records).
- Shared hooks chained: comp_register / comp_defaults; the clip reader call (JOEBOX's machine Fidelity modes on clip
  pads): Smooth stretch takes the call, everything else goes to JOEBOX. A clip in Smooth mode therefore plays without
  the machine Fidelity modes; Shift does not apply in a machine Fidelity mode (JOEBOX reads the file itself there).
