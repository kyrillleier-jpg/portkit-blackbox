# Legacy build: portkit on blackbox-mod 3.1.n (3.1.n+pk3)

**Superseded by `bb/joebox/` (JB1+pk).** Kept for reference: it is the first port of the bitbox micro features to the
Blackbox, on top of [blackbox-mod](https://github.com/j3threejay/blackbox-mod) 3.1.n (MIT, Justin Joe).
Addresses and evidence: `re/blackbox.md`.

It builds against whatever is checked out in `repos/blackbox-mod` and does not pin a commit; with the current JOEBOX
checkout it is not expected to build (not verified). Use `bb/joebox/`.

## What it contained (3.1.n+pk3)

- **Master distortion**: Tools → new tab **Extra**: Dist Type (Off / Soft / Hard / Fold / Tube), Drive (0..36 dB),
  Tone, Mix, Level. On Out 1/2 after the FX returns, before the mod's master compressor. Saved in settings.tml
  (pkdtype, pkddrive, …).
- **Clip functions**, clip pad → Pos page: Shift ms (−100..100), Play Len (Full, 1/4..32 bars), Stretch %
  (−100..100), Str Mode (Auto / Jump / Smooth = WSOLA), Loop Fade (0..50 ms). Sync 1/32 as eighth Sync entry.
- **FX3** (third send): own reverb (Plate / Room / Hall / Chamber); pad → Conf: FX3 Send; Tools → Extra: Type,
  Decay, Damp, PreDly, Size, Level.
- Version on splash and Tools: **3.1.n+pk3**.

## Build

```
python3 bb/build.py                    # blackbox-mod from source + our cave behind it
python3 bb/patch.py master clip fx3    # -> out/bb/master+clip+fx3/BLACKBOX.bin
python3 -I tests/test_bb_master.py
python3 -I tests/test_bb_clip.py
python3 -I tests/test_bb_fx3.py
```

Our cave starts 8-aligned after the mod image (0x080F8788) and ends before 0x08100000 (flash bank 1). `bb/patch.py`
checks every site against the mod image's bytes, zero repack, registered ranges, detour and pointer targets.

## RAM

SRAM4 0x38000000–0x380002FF distortion; 0x38000400–0x38000DFF WSOLA grains (64 × 40 bytes); 0x38000E00–0x380010AF
FX3 / reverb / plate state. D2 SRAM 0x30000000–0x300443FF: FX3 buffers. Both unused by firmware and mod according to
the canary map (`re/blackbox.md`, "RAM").
