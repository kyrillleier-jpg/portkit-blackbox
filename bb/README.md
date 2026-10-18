# portkit fuer die Blackbox (3.1.9, auf blackbox-mod 3.1.n)

Portierung der portkit-Funktionen der Bitbox micro auf die originale 1010music Blackbox, aufgesetzt auf
[blackbox-mod](https://github.com/j3threejay/blackbox-mod) (MIT, Justin Joe). Adressen und Belege: `re/blackbox.md`.

## Stand: 3.1.n+pk3

- **Master-Distortion** (wie Micro pkX): Tools → neuer Tab **Extra**: Dist Type (Off / Soft / Hard / Fold / Tube),
  Drive (0..36 dB), Tone (0..100 %, 100 % = offen), Mix, Level. Auf Out 1/2 nach den FX-Rueckwegen, vor dem
  Master-Kompressor des Mods; laeuft auch mit Kompressor Off. Gespeichert in settings.tml (pkdtype, pkddrive, …).
- **Clip-Funktionen** (wie Micro pkQ-pkZD), Clip-Pad → Pos-Seite: **Shift ms** (-100..100), **Play Len** (Full,
  1/4 .. 32 Takte), **Stretch %** (-100..100), **Str Mode** (Auto / Jump / Smooth = WSOLA), **Loop Fade** (0..50 ms,
  fuer Clips; Sample-Pads haben das Stock-Loop-Fade). **Sync 1/32** als achter Eintrag der Sync-Liste.
- **FX3** (dritter Send, wie Micro pkW): eigener Reverb (Plate / Room / Hall / Chamber). Pad → Conf-Seite:
  **FX3 Send**. Tools → Extra: FX3 Type, Decay, Damp, PreDly, Size, Level (Diffusion, Bass, Crossover, Mod Rate/Depth,
  Early, Width, Hi/Lo Cut nur ueber settings.tml: pkfx3diff … pkfx3locut). Der FX3-Rueckweg geht wie FX1/FX2 vor
  Distortion und Kompressor auf Out 1/2.
- Version auf Splash und Tools: **3.1.n+pk3**.
- Alles vom Mod bleibt (Fidelity, 24-dB-Filter, Saturation, Kompressor-Modelle, Room, Munchi, Solo, Chords, …).

Offen: Play Len kuerzer als Quant Size laesst in der Simulation Luecken (siehe
re/blackbox.md).

## Bauen

```
python3 bb/build.py            # blackbox-mod aus den Quellen + unser Cave dahinter
python3 bb/patch.py master clip fx3     # -> out/bb/master+clip+fx3/BLACKBOX.bin
python3 -I tests/test_bb_master.py
python3 -I tests/test_bb_clip.py
python3 -I tests/test_bb_fx3.py
```

`bb/build.py` baut blackbox-mod mit dessen build.sh / patch.py (Patchset-Liste des Releases; dessen patch.py prueft den
Stock-Hash). Mit unserem Toolchain ist der Mod-Cave nicht bytegleich mit dem veroeffentlichten 3.1.n-JSON (26892 statt
26760 Bytes), die Quellen sind dieselben. Unser Cave beginnt 8-ausgerichtet hinter dem Mod-Image (0x080F8788) und
endet vor 0x08100000 (Flash-Bank 1). `bb/patch.py` prueft jede Stelle gegen die Bytes des Mod-Images, Null-Repack,
registrierte Bereiche, Detour- und Zeigerziele; ohne gruene Pruefung wird nichts geschrieben.

## RAM

SRAM4 0x38000000-0x380002FF Distortion; 0x38000400-0x38000DFF WSOLA-Grains (64 Slots x 40 Byte); 0x38000E00-0x380010AF
FX3- / Reverb- / Plate-Zustand. D2-SRAM 0x30000000-0x300443FF: FX3-Puffer (Takte werden beim Boot eingeschaltet). SRAM4 und D2-SRAM sind laut Canary-Karte von Firmware und Mod
unbenutzt (`re/blackbox.md` "RAM").

## Simulation

`python3 -I sim/run.py --image bbpk --repl blackbox.repl [--sd out/sim/sdbb.img] wait 14 press B7 wait 1.5 tap 290 222 0.6 shot dist`
(Tasten B0-B12, Touch, Settings per `store 0x24028d18 <id> <wert>`, Audio per `capture`).

## Flashen

Nur nach eigener Entscheidung. Vorher Stock-`BLACKBOX.bin` sichern. Recovery: BACK + INFO beim Einschalten.
