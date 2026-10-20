"""Every way the JB1+pk build differs from stock Blackbox 3.1.9, and what can be switched off.

One row per feature (FEATURES). A row belongs to a GROUP; groups are what the build switches:
  - JOEBOX's patchsets (blackbox-mod's patches/*.py). Several features share one patchset, so they come and go
    together. Patchsets other parts depend on (memory at boot, the bank 2 loader, hook chains) are fixed: "core".
  - portkit's own groups, finer: each one is a set of patch sites in bb/joebox/patches/pk.py.
Used by bb/joebox/build.py (--groups) and the dashboard (bb/joebox/dashboard.py).
"""

# group: (label, origin, core, requires)
GROUPS = {
    # --- JOEBOX 1 (blackbox-mod, Justin Joe) ---
    "cave":     ("Grundgerüst (Code-Cave, Versionstext)", "JOEBOX", True, []),
    "master":   ("Master FX, Inserts, Live-Input, Bank-2-Loader", "JOEBOX", True, ["comp", "munchi"]),
    "comp":     ("Kompressor-Gruppe", "JOEBOX", True, []),
    "munchi":   ("Delay-Typen", "JOEBOX", True, []),
    "cpu":      ("Lastanzeige und USB", "JOEBOX", True, []),
    "fault":    ("Crash-Rekorder", "JOEBOX", True, []),
    "filter":   ("Fidelity und Pad-Filter", "JOEBOX", False, []),
    "duck":     ("Modulation (Ducker, LFO 2/3, ENV, KEY)", "JOEBOX", False, []),
    "od":       ("Saturation", "JOEBOX", False, []),
    "fx2":      ("Reverb-Typ Room", "JOEBOX", False, []),
    "solo":     ("Solo / MUTE / SOLO", "JOEBOX", False, []),
    "slice":    ("Slicer-Regler", "JOEBOX", False, []),
    "chord":    ("Akkorde auf dem Keys-Screen", "JOEBOX", False, []),
    "cond":     ("Note Conditions und Rotate", "JOEBOX", False, []),
    "seqfix":   ("Sequencer-Fix", "JOEBOX", False, []),
    # --- portkit ---
    "pk_dist":    ("Master-Distortion", "portkit", False, []),
    "pk_fx3":     ("FX3 (dritter Send)", "portkit", False, []),
    "pk_shift":   ("Clip Shift", "portkit", False, []),
    "pk_lfade":   ("Clip Loop Fade", "portkit", False, []),
    "pk_playlen": ("Clip Play Len", "portkit", False, []),
    "pk_stretch": ("Clip Stretch (Jump / Smooth)", "portkit", False, []),
    "pk_sync32":  ("Sync 1/32", "portkit", False, []),
    "pk_ssl":     ("SSL-Kompressor", "portkit", False, []),
    "pk_recsends": ("Sends bleiben bei Aufnahme", "portkit", False, []),
    "pk_fxrec":   ("Aufnahmequelle FX", "portkit", False, []),
    "pk_usbin":   ("Aufnahmequelle USB", "portkit", False, ["pk_fxrec"]),
    "pk_macro":   ("Performance-Makros", "portkit", False, ["duck", "solo"]),
}

# (group, feature, where on the unit, what it does)
FEATURES = [
    ("cave", "Version JB1+pk", "Splash, Tools", "Kennzeichnet das modifizierte Image; Lastanzeige links daneben"),
    ("master", "Master FX: VHS", "Tools > Master FX, INFO = Regler", "Band/VHS: Wow, Flutter, Sättigung, Dropouts, Rauschen"),
    ("master", "Master FX: Prism", "Tools > Master FX, INFO = 2 Reglerseiten", "Vier Blöcke Drive/Motion/Space/Texture, 20 Effekte (Bank 2)"),
    ("master", "Insert pro Pad", "Pad > Conf > Insert, INFO = Regler", "Phaser (Pebble, Ninety, Vibe, Deep, Steps), Flanger (Electra, Jet, Tape, Metal), Gate (Bank 2)"),
    ("master", "Live-Input auf einem Pad", "Pad > Conf > Input", "Off / In 1 / In 2 / In 1+2: Eingang läuft durch Insert, Sends, Pegel, Pan, Mute des Pads"),
    ("master", "Kompressor-/Master-FX-Seiten", "Tools, INFO auf der Zeile", "Reglerseiten für Kompressor und Master FX"),
    ("master", "Bank-2-Loader", "erster Boot", "Schreibt BBEXTRA.BIN in Flash-Bank 2, startet einmal neu"),
    ("comp", "Kompressor-Modelle", "Tools > Compressor", "Stock, Glue, Punch, Opto, Squash, Limit, Smash (3 Bänder)"),
    ("comp", "Comp Thresh", "Kompressor-Seite", "Schwelle der Modelle -24..+12 dB"),
    ("comp", "Master-Clipper", "Kompressor-Seite", "Off / Clean / Diode nach dem Kompressor, Clip, Shape, 2x Oversampling"),
    ("comp", "Kompressor immer aktiv", "intern", "Kompressorstufe läuft auch bei Off (damit Master FX geht)"),
    ("comp", "Record Pre-roll", "Tools > Rec > Pre-roll", "1/2/4/8 Takte Loop vor dem Aufnahmestart"),
    ("comp", "Saturation-Beschriftung", "Pad", "Overdrive heißt Saturation"),
    ("munchi", "Delay-Typ Munchi", "FX1 > Type", "Granular-Delay nach CHOMPI TEMPO, Clock/Width/Duck/Freeze"),
    ("munchi", "Delay-Typ Motion", "FX1 > Type", "Stock-Delay mit Tremolo/Filter/Duck/Swell auf den Wiederholungen"),
    ("munchi", "Delay-Typ Relapse", "FX1 > Type", "Memory-Echo"),
    ("munchi", "Delay-Typ Confetti", "FX1 > Type", "Granularer Micro-Looper (Bank 2)"),
    ("cpu", "Lastanzeige", "Tools-Leiste", "Durchschnitt/Spitze der Audio-CPU, ! = Bank 2 fehlt"),
    ("cpu", "USB-MIDI am Netzteilanschluss", "USB am Rechner", "Class-compliant MIDI-Gerät"),
    ("cpu", "USB-Audio", "USB am Rechner", "Drei Stereo-Ausgänge als 6 Kanäle 24 bit / 48 kHz"),
    ("fault", "Crash-Rekorder / Watchdog", "intern", "Fehlerdaten im Backup-SRAM, sauberer Neustart"),
    ("filter", "Fidelity", "Pad > Conf > Fidelity", "Crunch 16k..2k und Maschinenmodi SP1200, SP-12, S950, S950 Lo, MPC60, SP Raw, SP 45, S1000"),
    ("filter", "24-dB-Filter", "Pad > Main > Filter/Res", "State-Variable-Filter 24 dB/Okt., Drive ab Res-Mitte"),
    ("filter", "Fidelity auf Clip/Slicer", "Clip- und Slicer-Pads", "Maschinenmodi auch dort"),
    ("filter", "Conf-Zeilen Insert/Input", "Pad > Conf", "Zeigt die Insert- und Input-Zeilen (ohne sie sind Inserts/Input nicht erreichbar)"),
    ("duck", "Pad-1-Ducker", "Pad > LFO > Source", "Quellen EXP1, EXP2, PUMP, LINR lösen bei Pad 1 aus"),
    ("duck", "LFO 2 und LFO 3", "Pad > LFO+", "12 Wellen, Sync 32 Takte..1/32, Free/Retrig/Once, Offset"),
    ("duck", "ENV und KEY als Quelle", "Pad > Modulation Source", "Pad-Hüllkurve, Keytracking"),
    ("od", "Saturation", "Pad > Main", "Weiche Sättigung statt Hard Clip"),
    ("fx2", "Reverb-Typ Room", "FX2 > Type", "8-Linien-FDN mit Size/Mod/Early/Width"),
    ("solo", "Solo im Mixer", "MIX: Mixer > Mute > Solo", "Pads solo schalten"),
    ("solo", "MUTE / SOLO auf dem Pads-Screen", "Pads, Regler unten rechts", "Pads direkt muten / solo"),
    ("slice", "Slicer-Regler", "Waveform-Screen", "Start / End der Slice, Zoom"),
    ("chord", "Akkorde", "Keys-Screen, Regler oben rechts", "15 Akkordformen, werden aufgenommen"),
    ("cond", "Note Conditions", "Piano Roll > PLAY", "1:2 .. 8:8"),
    ("cond", "Sequenz rotieren", "Piano Roll > Event-Editor, Regler oben rechts", "Ganze Ebene schrittweise verschieben"),
    ("seqfix", "Sequencer-Fix", "Sequencer", "Noten kurz vor dem Abspielkopf spielen im selben Durchlauf"),
    ("pk_dist", "Master-Distortion", "Tools > Extra", "Soft/Hard/Fold/Tube, 2x Oversampling, Drive, Tone, Mix, Level (Bank 2)"),
    ("pk_fx3", "FX3 Send", "Pad > Conf > FX3 Send", "Dritter Send pro Pad"),
    ("pk_fx3", "FX3 Reverb", "Tools > Extra", "Plate/Room/Hall/Chamber, Decay, Damp, PreDly, Size, Level (Bank 2)"),
    ("pk_shift", "Shift", "Clip > Pos > Shift ms", "Audio gegen den Loop um -100..+100 ms drehen"),
    ("pk_lfade", "Loop Fade (Clips)", "Clip > Pos > Loop Fade", "0..50 ms Blende an den Loop-Nähten (Bank 2)"),
    ("pk_playlen", "Play Len", "Clip > Pos > Play Len", "Full oder 1/4..32 Takte"),
    ("pk_stretch", "Stretch", "Clip > Pos > Stretch %", "Tempo -100..+100 % durch Segment-Sprünge (Jump)"),
    ("pk_stretch", "Str Mode / Smooth", "Clip > Pos > Str Mode", "Auto / Jump / Smooth = WSOLA ohne Tonhöhenänderung (Bank 2)"),
    ("pk_sync32", "Sync 1/32", "Clip > Pos > Sync", "Achter Sync-Eintrag"),
    ("pk_ssl", "Kompressor-Modell SSL", "Tools > Compressor: SSL, INFO = Regler", "SSL-Buskompressor: Thresh, Ratio 2/4/10, Attack 0,1..30 ms, Release 0,1..1,2 s / Auto, Gain, Mix (Bank 2)"),
    ("pk_recsends", "Sends bleiben bei Aufnahme", "Aufnahme auf ein Pad", "FX1/FX2/FX3 Send des Pads werden beim Neuanlegen während der Aufnahme nicht zurückgesetzt"),
    ("pk_fxrec", "Rec Input: FX", "Record-Bildschirm > Rec Input", "Nimmt nur die Effekt-Rückwege auf (FX1 + FX2 + FX3), stereo (Bank 2)"),
    ("pk_macro", "Performance-Makros MAC1–MAC4", "Pads-Bildschirm, rechts (statt Velocity-Slider; der liegt jetzt auf der 4. Reglerposition)", "Vier Umschalt-Knöpfe; als Quellen MAC1–MAC4 in der Modulation: ein Makro steuert über die Mod-Slots beliebig viele Parameter auf ihren Amount, 30 ms Gleiten (Bank 2)"),
    ("pk_usbin", "Live-Input USB auf einem Pad", "Pad > Conf > Input: USB", "Der Ton vom Computer läuft dauerhaft durch ein Pad: Insert, Pegel, Pan, Sends, Mixer, Master FX (Bank 2)"),
    ("pk_usbin", "Rec Input: USB", "Record-Bildschirm > Rec Input; Computer an der Netzbuchse", "Nimmt Audio vom Computer auf: zweites USB-Audio-Gerät „Blackbox“ (Ausgang des Computers), stereo, 24 bit / 48 kHz (Bank 2)"),
]

JOEBOX_SETS = ["solo", "slice", "duck", "chord", "cond", "filter", "cpu", "od", "comp", "seqfix", "fx2", "munchi",
               "master", "fault", "cave"]                 # blackbox-mod's release order
PK_GROUPS = [g for g in GROUPS if g.startswith("pk_")]


def resolve(selected):
    """the groups a build gets: the selection plus every core group plus what they require"""
    out = set(g for g in selected if g in GROUPS) | {g for g, v in GROUPS.items() if v[2]}
    changed = True
    while changed:
        changed = False
        for g in list(out):
            for r in GROUPS[g][3]:
                if r not in out:
                    out.add(r)
                    changed = True
    return out


def default():
    return set(GROUPS)
