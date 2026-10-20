# portkit for the 1010music Blackbox (JB1+pk)

Community patch for the original **Blackbox, firmware 3.1.9**: the portkit features from the bitbox micro, merged into
Justin Joe's [JOEBOX 1](https://github.com/j3threejay/blackbox-mod) (blackbox-mod rc4). Everything from JOEBOX stays.
**No firmware and no JOEBOX sources are included.** The build takes your own stock `BLACKBOX.bin` (hash-checked) and
your own clone of blackbox-mod, compiles both with our code and checks every patch site.

> Unofficial, not affiliated with or supported by 1010music or the JOEBOX author. Running modified firmware is at your
> own risk and may affect your warranty. Keep the stock `BLACKBOX.bin`.

The patched image identifies itself: version **JB1+pk** on the splash and the Tools page.

## Features added by portkit

Status: everything below is verified in emulation (Unicorn tests, Renode simulation). The first JB1+pk build was
tested on a unit (basic function); the later additions (SSL, recording, enlarged parameter table) are not yet.

| Feature | Where |
|---|---|
| **Master distortion**: Soft / Hard / Fold / Tube, 2x oversampling, Drive, Tone, Mix, Level | Tools → Extra |
| **FX3**: third send per pad with its own reverb (Plate / Room / Hall / Chamber), Decay, Damp, PreDly, Size, Level | Pad → Conf → FX3 Send; Tools → Extra |
| **Clip Shift** (−100..100 ms), **Play Len** (Full, 1/4..32 bars), **Stretch %** (±100), **Str Mode** Auto / Jump / Smooth (WSOLA, pitch kept), **Loop Fade** (0..50 ms) | Clip pad → Pos |
| **Sync 1/32** | Clip pad → Pos → Sync |
| **SSL compressor** as ninth compressor model: Thresh, Ratio 2/4/10, Attack, Release (incl. Auto), Gain, Mix | Tools → Compressor: SSL, INFO = controls |
| **Sends survive recording**: FX1/FX2/FX3 sends of the pad are kept when it is re-created during a recording | recording to a pad |
| **Rec Input: FX** records only the effect returns (FX1 + FX2 + FX3), stereo | record screen → Rec Input |

Signal order on Out 1: pads (with JOEBOX inserts) → FX1/FX2 returns → FX3 → distortion → JOEBOX Master FX →
compressor → clipper.

## Choose your features: the builder dashboard

Every deviation from stock (JOEBOX's and ours, 49 rows) is listed in `bb/joebox/features.py`, grouped by what can be
switched together. A local web page builds any selection:

```sh
.venv/bin/python -I bb/joebox/dashboard.py      # -> http://127.0.0.1:8765
```

Tick features, **Bauen** (build) runs the build, the smoke test and the parameter manifest (and the full test suite
when everything is selected), then offers both files for download. Groups marked *fest* (fixed) are JOEBOX parts the
rest depends on (memory at boot, the bank 2 loader, hook chains). The dashboard runs on your machine only, because it
needs the firmware and the toolchain. The UI is German.

## Presets across builds

Presets (`preset.xml`, per pad) and `settings.tml` (global) store values by parameter **name**, so they survive
rebuilds. All extended lists are extended at the end. When you switch to a build without a feature, a saved value can
point past the end of a list (e.g. Sync 1/32, Compressor SSL, Rec Input FX):

```sh
.venv/bin/python -I bb/joebox/convert.py /Volumes/YOUR_SD           # report only
.venv/bin/python -I bb/joebox/convert.py /Volumes/YOUR_SD --apply   # zip backup first, then fix those values
```

It sets the nearest stock entry (1/32 → 1/16, SSL → Glue, FX → Resam, Fidelity modes → Normal) and changes nothing
else in the files. Also available in the dashboard. Note: JOEBOX's Note Conditions reorder their list; presets using
them are reported, not changed.

## Patch in the browser

`docs/index.html` is a one-page patcher: open it (or the GitHub Pages site of this repo), drop your stock
`BLACKBOX.bin` 3.1.9, download the result. Everything runs in the browser, nothing is uploaded. The page holds only this
project's bytes (no 1010music firmware), checks the stock file's SHA-256 before and the result's SHA-256 after, so it
can only produce the tested build. The patch is also in `docs/patches/*.json` (blackbox-mod's format; its `apply.py`
applies it too).

Regenerate after a change: `python3 -I tools/make_web.py` (needs a clean commit; builds, runs the tests, checks that no
32-byte run of the stock image ends up in the patch, then writes `docs/`).

## Requirements

- macOS or Linux, Python 3, `arm-none-eabi-gcc`, `git`
- Stock Blackbox firmware 3.1.9 as `firmware/BLACKBOX.bin`
  (SHA-256 `281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d`)
- Optional, for the simulation: [Renode](https://renode.io)

## Build from the command line

```sh
./setup.sh                                          # clones blackbox-mod, venv (capstone, unicorn, numpy, scipy), hash check
.venv/bin/python -I bb/joebox/build.py              # all features; or --groups pk_dist,pk_fx3,...
.venv/bin/python -I tests/smoke_jb.py
.venv/bin/python -I tests/test_jb.py                # full test (all groups)
```

With `PORTKIT_MICRO=<built portkit-micro checkout>`, `test_jb.py` also compares the distortion and SSL output
with the bitbox micro's (bit-identical); without it those comparisons are skipped.

Output: `out/bb/jb/release/BLACKBOX.bin` + `BBEXTRA.BIN` + `build.json` (SHA-256 of both). The build exports the
pinned JOEBOX commit (66329ad), runs JOEBOX's own build and patcher, then applies ours with checks: expected bytes at
every site, all changes inside registered ranges, every call and pointer lands on a known symbol, image ends before
0x08100000. JOEBOX's own 30 test suites run on the merged tree (`out/bb/jb/tree/test_*.py`).

Details (memory layout, hooks, ids, what changed against the first port): `bb/joebox/README.md`.

## Flashing

1. Back up the stock `BLACKBOX.bin`.
2. Copy **both** `BLACKBOX.bin` and `BBEXTRA.BIN` into the SD card root. They are a matched pair: a `BBEXTRA.BIN`
   from the public JOEBOX release does not fit.
3. Hold BACK + INFO while powering on. The unit restarts once while JOEBOX's loader writes flash bank 2.

Without a matching `BBEXTRA.BIN` the load readout shows `!`; the bank 2 effects (distortion, FX3, SSL, Smooth
stretch, Loop Fade, JOEBOX's Prism / Confetti / inserts) then pass audio through unchanged.

## Layout

| Path | What |
|---|---|
| `bb/joebox/` | the JB1+pk build: `build.py`, `features.py`, `ids.py`, `patches/pk.py`, `src/` (bank 1 hooks, bank 2 DSP), dashboard, converter |
| `bb/` (rest) | first port on blackbox-mod 3.1.n, superseded, see `bb/README.md` |
| `tests/` | Unicorn harness (`bb_emu.py`) and tests, parameter manifest |
| `sim/` | Renode simulation (Blackbox and bitbox micro platforms); see `sim/README.md` |
| `tools/` | reverse-engineering helpers (disassembly, xrefs, callers, cross-image function matching) |
| `patches/thumb.py` | Thumb-2 helpers shared by the patchers |
| `re/blackbox.md` | addresses, evidence and status (German) |
| `docs/firmware-mod.md` | the general workflow behind this project |

Sister project for the bitbox micro: **portkit-micro**.

## Licence

MIT for this project's code, see `LICENSE`. JOEBOX / blackbox-mod: MIT, Justin Joe, see `THIRD_PARTY.md`.
The 1010music firmware is not part of this project and not covered by any licence here. Share build instructions,
not built images.
