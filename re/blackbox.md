# Symbole: Blackbox 3.1.9 (`BLACKBOX.bin`, SHA-256 281ae303…341d) und blackbox-mod 3.1.n

Status wie in `re/symbols.md`: `vermutet` = statisch belegt; `durch Emulation bestaetigt` = Renode-Simulation oder
Unicorn-Test; `hardware-verified` nur nach Hoeren am Geraet (noch nirgends). Adressen gelten fuer Stock 3.1.9 und das
Mod-Image (der Mod aendert nur einzelne Stellen und haengt ab 0x080F1E78 an).

## Simulation (Renode, 2026-10-16)

| Adresse | Was | Beleg | Status |
|---|---|---|---|
| 0x08083020 / 0x08081BB8 | HAL_UART_Init / UART_SetConfig (LPUART1 0x58000C00 beim Boot) | Trace | durch Emulation bestaetigt |
| 0x080458DC / 0x08045AB4 / 0x08045974 / 0x080459E8 / 0x08045A5C | sd_diskio init / status / read / write / ioctl (Treibertabelle 0x080CFC1C) | Prologe wie Micro 0x08044FAC ff., Status-Signatur gleich; Boot bis Pads mit SD | durch Emulation bestaetigt |
| 0x080438DE | Tastenabfrage (13 Tasten, Tabelle 0x18 je Taste: +0 Port, +4 Pin, +0xE Zustand), aktiv low | GPIO-IDR-Lesezugriffe, Logging | durch Emulation bestaetigt |
| Tasten | B0 PI8 Pads, B1 PD4 Keys, B2 PD7 Seq-Raster, B3 PI12 Song/Loop, B4 PI14 Perf-FX, B5 PG3 Mixer, B6 PH7 File, B7 PC13 Tools, B8 PB13, B9 PJ1, B10 PH4 (Start?), B11 PC2, B12 PC3 | Screenshot je Tastendruck (`sim/run.py press Bn`) | durch Emulation bestaetigt (B8-B12 offen) |
| GT911 | I2C1 0x5D wie Micro (0x8140 / 0x814E bei 0x080422E6 / 0x08042384); Touch-y von oben (Micro: von unten) | VEL-Regler, Pad-Auswahl | durch Emulation bestaetigt |
| Display | LTDC 320x240 quer, Layer ARGB1555 | Screenshot `--rot 0` | durch Emulation bestaetigt |
| Audio | DMA2 wie Micro (`PortkitAudioDMA`), 128 Frames je Block, 375 Bloecke/s; Capture 16 Byte je Frame, Kanal 0 (int32) = Out 1 links | Capture eines Pads | durch Emulation bestaetigt |

Unbekannt: Geraet an I2C1 0x4C (Dummy antwortet). Fehler beim ersten Boot war kein Firmware-Fehler: die SD-Hooks der
Micro (0x0804504C = SD_read) lagen im Blackbox-Image mitten in HAL_UART_MspInit (Stack um 0x38 verschoben).

## RAM (Canary, 2026-10-16)

Alle SRAM-Baenke vor dem Boot mit 0xA5 gefuellt, Boot, Pad-Auswahl, zwei MIDI-Noten, Tastendruck, dann gelesen
(`bbcan_*`). Unberuehrt: ITCM 0x00000000-0x0000FFFF, **D2-SRAM 0x30000000-0x30047FFF (288 KB)**, **SRAM4
0x38000000-0x3800FFFF (64 KB)**; im AXI-SRAM 0x2402F21C-0x24037034 und 0x24070FB8-0x2407D5C0 (Luecken im Heap /
DMA, nicht verwendet). Keine Literal-Referenz der Firmware in D2-SRAM oder SRAM4 (die Treffer bei halbwortweiser Suche
sind Befehlsfragmente, 0x38000000 bei 0x0805FEB0 ist die Float-Konstante 1/32768). blackbox-mod nutzt 0x2405FF54-
0x2405FFFF und den Backup-SRAM 0x38800000-0x38800B1C. Nicht abgedeckt: Aufnahme, USB, Preset speichern.
Takt der D2-SRAMs (RCC_AHB2ENR SRAM1-3EN): noetig und nach jedem Reset neu zu setzen, siehe "Boot-Loop nach dem Bank-2-Neustart"; Renode modelliert Clock-Gating nicht. SRAM4
braucht keinen eigenen Takt-Schalter.

Belegung durch portkit: SRAM4 0x38000000-0x380002FF Distortion (`bb/src/master.c`).

## Master (Build 3.1.n+pk1)

| Adresse | Was | Beleg | Status |
|---|---|---|---|
| 0x080534CC ff. | Block-Funktion: Bus 0 = buf_of(bufs, 0) in r6, FX-Rueckwege 0xA / 0xB dazu (0x0804DA6C), Objekt +0xD8C, dann Kompressor-Flag | Disassembly | vermutet |
| 0x08053528 | `ldrb.w r3, [r5, #0xd60]` Kompressor-Flag; **Thunk dist_thunk** (Bus 0 = r6) | Hook-Zaehler 1733 in 6 s; r6 = Bus {cap 128, frames 128, L/R im DTCM} | durch Emulation bestaetigt |
| 0x08053C98 / 0x0804EDDC | Kompressor-Aufruf (Mod: comp_process) | blackbox-mod | vermutet |
| 0x0804D8E8 / 0x0804D8F4 / 0x0804D9C0 | buf_frames / buf_silent / buf_stereo (stummen Puffer nullen, Stereo erzwingen) | Disassembly, Layout wie Micro | durch Emulation bestaetigt |
| 0x0808C0A8 | Param-Tabelle eintragen (id < 0x1F4, 28 Byte je Eintrag, Zeiger 0x2401F4FC) | Disassembly; Unicorn | durch Emulation bestaetigt |
| 0x0808C0D8 / 0x0808C12C | register_list (Typ 5) / register_num (Typ, Label, min, max, xml) | Unicorn | durch Emulation bestaetigt |
| 0x08093EF6 / 0x08093E9C | Store add / get (+4 Eintraege, +0xA Anzahl, +0xC Kapazitaet) | Disassembly; Settings-Store app+0x8C90 = 0x24028D18: 47 von 64 belegt | durch Emulation bestaetigt |
| 0x080EED18 | Tools-Seiten: 5 x 36 IDs (u16), Seite 4 leer; 0x080EEE80 Tab-Namen (6 Zeiger, erster leerer beendet die Leiste) | Disassembly 0x08099790; Screenshot | durch Emulation bestaetigt |
| 0x080996D2 / 0x08098D5A | `cmp r6, #3` in Listen- und Zeilenbau fuer Code 0x40 (Tools): Seite 4 erst nach Patch auf `#4` | Screenshot Dist-Tab | durch Emulation bestaetigt |
| 0x080CF290 | Versionsstring (Mod: "3.1.n"), Nutzer 0x0809AF30, 0x080AEAF4, 0x080C55E8, 0x080C72C8 | Splash und Tools zeigen 3.1.n+pk1 | durch Emulation bestaetigt |
| Anzeige-Typen | 7 = milli-dB als dB, 8 = 0..1000 als %, 10 = Hz (eigene Kurve, nicht genutzt), 5 = Liste | Labels der Stock-Registrierungen | vermutet |
| IDs 0x1E8-0x1EC | Dist Type / Drive / Tone / Mix / Level (frei in Stock und Mod) | Registrierungs-Scan (`out/bb_params.txt`), Mod-Quellen | durch Emulation bestaetigt |

Unicorn (`tests/test_bb_master.py`): Hooks, Defaults-Kette (Stock, Mod, unsere), Registrierung, Tools-Seite, Version;
Distortion-Ausgabe aller vier Typen bitgleich mit der Micro (`master_dist` im Micro-Image). Renode: Tube +24 dB an,
Engine laeuft weiter; ein Pad (chord.wav) mit Hard +24 dB: Crest-Faktor 3,45 → 1,30 auf Out 1.

## Clip-Funktionen (Build 3.1.n+pk2)

Die Clip-Engine der Blackbox ist dieselbe wie auf der Micro (Pad-Struktur, Slots 0x30 + k x 0x70, Leser-Argumente,
Segmentlogik Befehl fuer Befehl gleich, nur verschoben und teils andere Register). Gefunden ueber die Aufrufer der
Stream-Funktionen (`tools/falign.py --callers`), die 1:1 den Micro-Aufrufern entsprechen.

| Micro | Blackbox | Was | Status |
|---|---|---|---|
| 0x080A4500 / 0x080A44C8 / 0x080A4624 / 0x080A45AC / 0x080A4650 | 0x08063634 / 0x08063608 / 0x0806375C / 0x080636F0 / 0x08063790 | Stream: read1 / read2 (nur gestreamte Dateien, +0x20) / seek / frames / stereo | durch Emulation bestaetigt |
| 0x080B55AC (Leser, Pad r4) | 0x080662E4 (Pad r5) | Clip-Leser + Resampling; Aufrufe read1 0x0806636E / 0x0806644E, read2 0x080663BA / 0x0806642C | durch Emulation bestaetigt |
| 0x080B5728 / Aufruf 0x080B58FC | 0x08066454 / Aufruf 0x08066622 | Slot-Leser, gleiche Argumente (BB begrenzt die Rate auf 8) | durch Emulation bestaetigt |
| 0x080B4644 / 0x080B490C | 0x08065290 / 0x08065550 | Segmentstarts (Pad r4), Seeks 0x0806541A / 0x0806578C | vermutet |
| 0x080B49B4 `ldr.w r3,[r4,#0x240]` | 0x080655FE `ldr.w r2,[r4,#0x240]` | letztes Segment | durch Emulation bestaetigt (Thunk) |
| 0x080B4A68 `vmul s16,s15,s16` | 0x080656BC `vmul s15,s15,s16` (lr dort live!) → gepatcht 0x0806560C `vldr s15,[r4,#0x1fc]` | Segmentposition = Index x Laenge (x Stretch) | durch Emulation bestaetigt (Thunk) |
| 0x080B5AA8 (Clip-Voice), 0x080B5F2E / 0x080B611A | 0x080667B8, 0x08066C46 `ldrd r2,r3` / 0x08066E7A `ldrd r1,r2` | Segmentzahl (+0x240 + +0x244) | durch Emulation bestaetigt (Thunk) |
| 0x08089548 / 0x08089F8C | 0x08093F20 / 0x080949E4 (Init per Typ 0x08094A1C) | Pad-Record-Init / -Reset, Kapazitaet `movs r1,#0x40` bei 0x08093F26 / 0x080949F0 | durch Emulation bestaetigt |
| 0x080896F8 / 0x08089922 (Filter 0xAA) | 0x08094112 / 0x08094346 (FX2 Send 0xDA) | Hook fuer neue Pad-Parameter | durch Emulation bestaetigt |
| 0x080C4F7C / Literal 0x080B74E4 | 0x080EC82C / Literal 0x08067BB4 (Handler 0x08067648); zweiter Nutzer 0x080964C0 bleibt | Sync-Beats-Tabelle | durch Emulation bestaetigt |
| Sync-Registrierung 0x0806AB7E | 0x0808D104 (Namen 0x080EC848) | Sync-Liste | durch Emulation bestaetigt |
| Clip-Loop-Seite | 0x080EF288, 0x080EF990 (Seite 1 "Pos"; Seiten 5 x 0x48, 2 fuehrende Halbworte) | Loop Mode 0x8D, Beat Count 0xD2, Quant Size 0x47, Sync 0x94 | durch Emulation bestaetigt |

Pad-Record Typ 3 (Clip): 59 Eintraege ab Werk + 5 neue = 64, Kapazitaet auf 72 (wie Micro). Store-Allokator 0x0804436C
(SDRAM, Zeiger 0x2400008C, Grenze 0x24000088; nach dem Boot ~2,1 MB frei). Typ 0x45 ist auf der Blackbox kein
Pad-Typ (leerer Record). Neue Pad-IDs 0x1ED-0x1F1 (Shift, Play Len, Stretch, Str Mode, Loop Fade); kein Vergleich
gegen 0x1E8-0x1F3 im Code (einziger Treffer 0x1F2 bei 0x080A8F92 ist eine Groessenpruefung).
Anzeige-Typ 1 (Ganzzahl) gibt es auch auf der Blackbox ("Shift ms: 0").

Renode (Clip-Pad chord.wav, Loop an, Transport B10): Shift +50 ms, Smooth-Stretch +50 % laufen ohne Luecken und ohne
groessere Spruenge als Stock (max. Schritt 0,016 / 0,018 vs. 0,015). Play Len 1 bar: durchgehend. Play Len 1/4 bar bei
Quant Size 1 bar: 1,26 s Klang, 0,74 s Stille je Takt (offen; dieselbe Logik wie auf der Micro, dort am Geraet nicht
geprueft).

Loop Fade: die Blackbox hat ab Werk "Loop Fade" (0xFA, Typ 8) auf der Sample-Pos-Seite, nicht fuer Clips; portkit
fuegt fuer Clips eigenes Loop Fade 0..50 ms hinzu (0x1F1).

## FX3 (Build 3.1.n+pk3)

| Adresse | Was | Beleg | Status |
|---|---|---|---|
| 0x0804DB4C / 0x0804DA6C | mix_gain(bus, src, s0) / mix(dst, src) | Disassembly der Sends | vermutet |
| 0x08060930 | Send-Kurve (Wert/1000 → Gain), 4 Aufrufer wie Micro 0x080A04C0 | `falign --callers` | durch Emulation bestaetigt |
| 0x08059ACC ff. (Sample) / 0x080688BC ff. (Clip) | Pad rendert in Scratch, dann FX1 → Bus 0xA, FX2 → Bus 0xB (je eigene `vldr s15,[gain]`-Pruefung), dann Ausgang; keine gemeinsame Sperre wie auf der Micro | Disassembly; alle Wege laufen ueber die FX2-Ladung | vermutet |
| 0x08059ACE / 0x080688D0 | `vldr s15,[r3]` FX2-Gain: **Thunks fx3_send_a / _b** (Pad r4, Scratch [sp,#0x18] / [sp,#0x14], Busarray r5 / r7) | Renode: r4 = Pad (Id +0x18), r5/r7 = Busarray (Bus 0 = +0x150E4) | durch Emulation bestaetigt |
| 0x08053516 | `bl 0x0804DA6C` Bus 0 += Bus 0xB: **fx3_master** | Hook | durch Emulation bestaetigt |
| Busse | 18 wie Micro (+0x150E4, 20 Byte); 0xC und 0xD werden auf der Blackbox benutzt (0x08053ACA, 0x08062720), 0x10 / 0x11 nicht sicher frei → FX3 sammelt in eigenem Puffer (D2-SRAM) | Konstanten-Scan, Canary | vermutet |
| 0x08074D1C / 0x08074F50 | Plate-Init (operator new 0x080443A8, memset 0x080C8D5E) / Plate-Kern | Unicorn: Zustand 44 Worte, 12 Puffer 4x2 KB, 2x4 KB, 6x32 KB (212992 Byte) | durch Emulation bestaetigt |
| 0x080443A8 | operator new: kleiner Heap (Grenze 0x1F800, Block > 0x42CC anders), haengt bei Mangel (Mod-Kommentar) | Disassembly | vermutet |
| 0x0809481C / 0x08094820 | Settings-Init, Kapazitaet 64 → 80 (44 Stock+Mod, 5 Dist, 15 FX3 = 64) | Unicorn | durch Emulation bestaetigt |
| 0x080996B0 | Listenbau Tools: IDs ab +2, Werte ab +0x14, danach Tab-Zahl +0x44 und Tab-Namen +0x4D. **Hoechstens 11 Eintraege je Tools-Seite** (20 ueberschrieben die Tabs: Tab blieb haengen) | Renode | durch Emulation bestaetigt |
| Conf-Seiten | 0x080EF090, …1F8, …360, …4C8, …630, …900, …A68, …BD0, …D38 (Listenende + FX3 Send 0x1F2; zwei Seiten jetzt 11 Eintraege, Granular geprueft) | Renode | durch Emulation bestaetigt |

IDs: FX3 Type 0x1B8, Decay 0x1B9, Damping 0x1BA, Pre-Delay 0x1BB, Size 0x1BC, Diffusion 0x1BD, Bass 0x1BE, Crossover
0x1BF, Mod Rate 0x1C0, Mod Depth 0x1C1, Early 0x1C2, Width 0x1C3, Hi Cut 0x1C4, Lo Cut 0x1C5, Level 0x1C6 (global), FX3
Send 0x1F2 (Pad). Gemieden: 0x1A0, 0x1AA, 0x1B5, 0x1CC (Konstanten im Code). Auf der Seite "Extra": Dist (5), FX3
Type, Decay, Damp, PreDly, Size, Level; die uebrigen nur ueber settings.tml.

Speicher: D2-SRAM 0x30000000-0x30033FFF Plate-Puffer, 0x30034000-0x30043FFF Pre-Delay, 0x30044000-0x300443FF
Sammelpuffer; Takte SRAM1-3 per RCC_AHB2ENR Bits 29-31 (nicht verifiziert, ob noetig; Renode modelliert keine Takte).
SRAM4 0x38000E00 FX3-Zustand, 0x38000F00 Reverb-Zustand, 0x38001000 Plate-Zustand (0xB0).

Unicorn (`tests/test_bb_fx3.py`, 18): Plate-Vorlage bitgleich zur Stock-Init, Sends, Thunk, Impuls durch alle vier Typen,
Pre-Delay. Renode: Hall, Decay 80 %, FX3 Send 100 %: RMS der letzten Sekunde 0,009 → 0,036; alles zusammen (Dist, Clip
Smooth-Stretch + Shift, FX3 Room) ohne Ausfaelle. CPU-Last nicht gemessen (`sim/prof.py` kennt nur Micro-Adressen).

## JOEBOX 1 (blackbox-mod rc4, Commit 66329ad) + portkit = "JB1+pk" (2026-10-18)

Aufbau JOEBOX: Bank 1 = Stock + Cave ab 0x080F1E78, hoechstens 0xE188 Byte (der 1010music-Installer verweigert ein
Image ueber 0x08100000); Bank 2 ab 0x08100000 = Blatt-DSP (Prism, Confetti, Inserts, rev4), vom eigenen Loader
(b2load.c) aus BBEXTRA.BIN geschrieben, gepaart ueber Kopf (Magic, Id, Laenge, Summe) und b2_expect_sum in Bank 1;
b2_live() entscheidet, ob Bank-2-Code laufen darf. Regel: Bank 2 ruft nichts im Cave (test_bank2.py).
Mit unserem Toolchain: JOEBOX-Cave 53272 Byte (Release 53128), d. h. ~4,4 KB frei.

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| ID-Belegung | JOEBOX registriert fast alles von 0x19D bis 0x1EF; frei (> 0x150): u. a. 0x17D, 0x181-0x188, 0x18A, 0x18B, 0x192-0x196, 0x19A, 0x19C, 0x1B5, 0x1C8-0x1CF, 0x1E5, 0x1F0-0x1F3 | Unicorn: komplette Registrierung 0x0808C158 im JOEBOX-Image | durch Emulation bestaetigt |
| 0x08068D4C | Clip-Pad-Engine-Handler: IDs <= 0x17A zur Engine, 0x17B-0x19A Sprungtabelle (nur 0x17B, 0x181-0x187 behandelt), > 0x19A ignoriert | Disassembly | vermutet |
| gemieden | 0x19A (Sonderfall 0x0809FD78), 0x1CC / 0x1B5 / 0x1AA (Konstanten im Code), 0x1F1-0x1F3 (JOEBOX ID_MUTE/SOLO/BLANK) | | |
| portkit-IDs | Pad 0x1C8-0x1CB, 0x1CD, 0x1CE; global 0x17D, 0x188, 0x18A, 0x18B, 0x192-0x196, 0x19C, 0x1CF | test_jb.py | durch Emulation bestaetigt |
| Kapazitaeten | Settings und Pad-Records von JOEBOX auf 96 gesetzt; belegt 79 / 88 (Clip-Record) | Unicorn | durch Emulation bestaetigt |
| geteilte Hooks | 0x0808D350 comp_register, 0x08094886 comp_defaults (verkettet), 0x08066622 clip_read_b (JOEBOX Maschinen-Fidelity auf Clip-Pads): pk_clip_entry nimmt den Aufruf nur bei Smooth, sonst unveraendert weiter | test_jb.py (Register, Stack) | durch Emulation bestaetigt |
| 0x0805352E | JOEBOX: `b.w` statt `bne` - die Kompressorstufe (Master FX, Kompressor, Clipper) laeuft immer; unser Flag-Thunk 0x08053528 liegt davor und bleibt gueltig | Disassembly | vermutet |
| Inserts | JOEBOX 0x080599EC / 0x08059A7C / 0x08068830 / 0x0806889C (eigener Mischpuffer); unsere FX3-Sends 0x08059ACE / 0x080688D0 danach, FX3 bekommt wie FX1/FX2 das Signal nach dem Insert | Disassembly, Renode | vermutet |
| Conf-Seiten | JOEBOX setzt Insert / Input ein; FX3 Send wird hinter dem jeweiligen Listenende angehaengt (zur Build-Zeit ermittelt) | Renode-Screenshot | durch Emulation bestaetigt |
| Aufteilung | Bank 1: pk_main.c + pk_thunk.S (~3,8 KB, Cave danach 720 Byte frei); Bank 2: pk_dsp.c (~15 KB, Distortion, WSOLA, Loop-Fade-Rampe, FX3-Reverb + Plate-Einrichtung). Ohne passende Bank 2 laufen diese durch (kein Effekt), Shift/Play Len/Jump/Sync 1/32 bleiben | test_jb.py | durch Emulation bestaetigt |

Renode: Image + bank2.bin (`sim/run.py --image jb --bank2 out/bb/jb/bank2.bin`), Version "JB1+pk", Lastanzeige ohne
"!" (Bank 2 gepaart), alle Seiten (Tools Extra, Pos, Conf mit Insert/Input/FX3 Send). Alle sechs Funktionen
gleichzeitig (Smooth-Stretch, Shift, FX3 Hall, Distortion, VHS, Phaser-Insert): bei Renodes Standard 100 MIPS gehen
19 von 750 Bloecken verloren (Spruenge an Blockgrenzen), bei 300 und 480 MIPS keiner. **Die Simulation laeuft ohne
Angabe mit 100 MIPS, das Geraet mit 480 MHz: verpasste Bloecke bei 100 MIPS sind kein Befund** (`mips 480` im Runner).
JOEBOX' 30 Testsuiten laufen auf dem zusammengefuehrten Baum gruen (numpy, scipy noetig).

### Erweiterung 2026-10-18: Tabelle 600, SSL, Aufnahme, Konverter

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| Parametertabelle | 500 Slots x 28 Byte; Groesse steht an 11 Stellen (0x0808C0AA, 0x0808C162, 0x0808C174, 0x0808E224 ... 0x0808E384), auf 600 gesetzt; portkit-IDs ab 0x200 | test_jb.py (Registrierung, Tabellengroesse), 30 JOEBOX-Suiten | durch Emulation bestaetigt |
| Rec Input 0x9A | Liste L+R/Left/Right/Resam, registriert 0x0808D198; Pad-Parameter (xml `recinput`, steht pro Pad im Preset) | Disassembly, Preset-Dateien | durch Emulation bestaetigt |
| 0x08062120 | Record-Knoten: `cmp r3,#3; beq.w 0x0806277E` = Resample-Abgriff (bufs+0x15864 nach r8 via 0x0804D880); FX (4) kopiert die FX-Summe (FX1+FX2+FX3, SRAM4 0x38001800/0x38001A00, Puffer-Struct 0x38001C00) | PC-Trace-Diff in Renode, test_jb.py | durch Emulation bestaetigt |
| 0x08062660 | `cmp r3,#3; beq` ueberspringt den Eingangs-Monitor; FX wie Resam | Disassembly | vermutet |
| 0x0809B26A | Aufnahmestart: stereo fuer 0 und 3, jetzt auch 4 | test_jb.py (Flags) | durch Emulation bestaetigt |
| 0x0809D5FA | `bl 0x08094A1C`: Pad-Record wird waehrend der Aufnahme neu angelegt (Sends gingen verloren); rec_reinit behaelt 0xD9/0xDA/FX3 Send | test_jb.py | durch Emulation bestaetigt |
| Tasten | B8 = REC, B9 = STOP, B10 = PLAY, B12 = INFO; REC nur bei laufendem Transport | Renode, Geraet | durch Emulation bestaetigt |
| Preset-Format | `<params name="int" .../>` je Zelle, Globales (globcomp, pk*) nicht im Preset, sondern settings.tml; Datei endet mit NUL, ist kein striktes XML; Song-Zelle traegt globtempo | 21 Presets eines 3.1.x-Geraets | belegt |
| registrierte Bereiche | min/max der Tabelle gelten NICHT fuer gespeicherte Stock-Werte (samlen/loopend in Samples, eqtype 0..0) - der Konverter klemmt nur pk* | Presets gegen Manifest | belegt |
| evtcond | JOEBOX ordnet die Liste um (ALWAYS Index 99 statt 0) | Manifest-Diff Voll/Minimal | durch Emulation bestaetigt; Auswirkung auf Stock-Presets offen |
| settings.tml | Format nicht gesehen (keine Datei im Backup) | | offen |

Aufnahme mit Rec Input FX im Renode: Aufnahme laeuft, die SD-Schreibzugriffe kommen im Sim nicht an ("SD writes 0") -
der geschriebene Clip ist dort nicht pruefbar. Offen fuer das Geraet.


### Hardware-Test JB1+pk (2026-10-20)

Alle portkit-Funktionen des Voll-Builds (Master-Distortion, FX3, Clip Shift / Play Len / Stretch / Loop Fade, Sync 1/32,
SSL-Kompressor, Rec Input FX, Sends bei Aufnahme) am Geraet getestet (Rueckmeldung): **hardware-verified**.

## Rec Input: USB (pk_usbin, 2026-10-20)

Ausgangslage: Das USB-Audio an der Netzbuchse ist komplett JOEBOX (`src/usbdev.c`, OTG_HS 0x40040000 mit eingebautem
Full-Speed-PHY an PB14/PB15); Stock nutzt diesen Controller nicht. JOEBOX: ein Strom zum Computer (EP 0x82, iso IN,
asynchron, 6 x 24 bit, 882 Byte/Frame), USB-MIDI auf EP 1. Am USB-A-Host-Anschluss findet sich in den Stock-Strings
nur MIDI, kein Audio-Klassentreiber (nur Strings geprueft, nicht verifiziert).

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| Deskriptor | zweites Audio-Streaming-Interface 2 (alt 1: EP 0x03 iso OUT, **adaptiv** 0x09, 294 Byte = 49 x 2 x 3), Terminals 3 (USB-Streaming) -> 4 (Line); AC-Header 53 Byte, Interfaces 1, 2, 3; MIDI wird Interface 3; Konfiguration 249 Byte, 4 Interfaces; bcdDevice 1.01 | JOEBOX test_usbdev.py (angepasst, gruen) | durch Emulation bestaetigt |
| adaptiv statt asynchron | ein Feedback-Endpunkt (iso IN) wuerde jede zweite Frame-Periode "incomplete iso IN" ausloesen, und JOEBOX' Handler (IISOIXFR) verwirft dann sein Audio-Paket: adaptiv laesst seinen Pfad unberuehrt; die Blackbox passt die Rate selbst an | usbdev.c usbaud_isr | Entwurfsentscheidung |
| FIFOs | RX 0x100 Worte (vorher 0x80), TX0 0x100, TX1 0x140, TX2 0x180 (je wie vorher gross); belegt 0x280 von 0x400 Worten | build.py USBIN_EDITS | durch Emulation bestaetigt |
| Bandbreite | 882 + 294 Byte periodisch pro Frame, Full Speed erlaubt ~1350 (90 %) | Rechnung | vermutet (Host-seitig nicht geprueft) |
| Empfang | RX-Status ep 3 kind 2 -> usbin_rx (Bank 1) -> pk_usbin_rx (Bank 2, nur Integer, FPU-frei geprueft) in den Ring SRAM4 0x38004000 (1024 x L/R); kind 3 bzw. GINTSTS bit 21 (incomplete iso OUT) -> neu scharf fuer die Paritaet des naechsten Frames | test_jb.py (FIFO per Lese-Hook) | durch Emulation bestaetigt |
| Oeffnen | SET_INTERFACE 2 im Task; b2_live() nur dort (der erste Aufruf kann Bank 2 scannen: nicht im Interrupt); Zustand SRAM4 0x38003F00 mit Magic "USB1", core_setup setzt ihn jeden Boot zurueck | test_jb.py | durch Emulation bestaetigt |
| Leser | 384 Frames (8 ms) Vorlauf, PI-Regelung der Leserate auf den geglaetteten Fuellstand (Kp 5e-6, Ki 2e-9, im Modell abgestimmt), kubische Hermite-Interpolation; Start erst nach 384 frischen Frames, Abriss -> Stille, nie alter Ringinhalt | test_jb.py: +-0,1 % Taktabweichung 40 s ohne Luecke/Sprung, Puffer zurueck auf 384 | durch Emulation bestaetigt |
| Aufnahme | Rec Input 5 = USB (Liste 6 Eintraege, nur mit pk_usbin; braucht pk_fxrec, damit die Indizes stabil bleiben); rec_src_thunk -> rec_usb_copy -> fw_buf_copy aus PK_USBIN_BUF; stereo; Monitor wie ein Eingang (0x080627d6 kopiert den Record-Puffer r8 auf den Monitor-Ausgang, stereo ausser bei Left / Right; Resam / FX bleiben ohne Monitor) | test_jb.py | durch Emulation bestaetigt |
| Bank 1 | ohne Platzarbeit 184 Byte zu viel: Parametertabelle gepackt (Label+XML ein String, dB in ganzen dB, Namen als Index), Settings-Lesen von master_dist / fx3_master / pk_ssl nach Bank 2; danach 184 Byte frei | Build | - |

Am Geraet (2026-10-20): funktioniert grundlegend (Rueckmeldung); Mithoeren fehlte, weil rec_mon_thunk USB wie Resam / FX uebersprang - korrigiert, am Geraet noch nicht gehoert.
Offen: weitere Punkte am Geraet. Zu pruefen: erscheint "Blackbox" als Ausgabegeraet
(macOS / Windows), kommt Audio sauber an, ob JOEBOX' Ausgang dabei weiter ohne Aussetzer laeuft (Bandbreite,
RX-FIFO, Interrupt-Last), Verhalten bei abgezogenem Kabel waehrend der Aufnahme.

### Live-Input USB auf einem Pad (2026-10-20)

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| JOEBOX Live-Input | insert.c: `ins_set.input` (Off / In 1 / In 2 / In 1+2, Pad-Parameter 0x1C7 `insinput`), insert_tick liest ihn je Pad, add_input addiert den ADC-Bus (Engine + 0x128E0 + 0x1583C) in den eigenen Mix des Pads vor dem Insert; insert_live haelt das Pad ohne Stimme am Rendern | insert.c | gelesen |
| USB als Quelle | fuenfter Eintrag "USB" (IN_USB, angehaengt), add_input -> usbin_add (Bank 1) -> pk_usbin_add (Bank 2): addiert den Block des Computer-Stroms; Mono-Pad bekommt links | test_jb.py (echter insert_tick / insert_process) | durch Emulation bestaetigt |
| ein Block fuer alle | pk_usbin_fill erzeugt hoechstens einmal pro Audio-Block (DWT-Zyklen, JOEBOX cpu.c schaltet den Zaehler ein; halber Block 500 000 Zyklen bei 399 MHz): Recorder und Pad bekommen dieselben Samples, sonst nimmt jeder jeden zweiten Block | test_jb.py | durch Emulation bestaetigt |
| Monitor | Rec Input USB: Monitor wie ein Eingang (am Geraet: Aufnahme lief, Mithoeren fehlte -> korrigiert) | Rueckmeldung, test_jb.py | Aufnahme hardware-verified, Monitor durch Emulation bestaetigt |

## Performance-Makros MAC1-MAC4 (pk_macro, 2026-10-20)

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| globale Quellen | FUN_080519E0 (Mod-Ziel an Quelle haengen) verzweigt nach Quellcode: Objekt-Offset in der Engine je Code, Wert = Objekt + 4: 0xF 0xD72C, 0x10 0xD6C8, 0x11 0xD664, 0x12 0xD600 (JOEBOX: LINR/PUMP/EXP2/EXP1 - deckt sich mit seinen Werten 0xD730 / 0xD6CC / 0xD668 / 0xD604), **0x13 0xD718, 0x14 0xD6B4, 0x15 0xD650, 0x16 0xD5EC**, 0x17 0xD614 | Disassembly (Sprungtabelle 0x08051A0A) | gelesen, gegen JOEBOX' Werte geprueft |
| Preset-Namen | Quellnamen der Firmware in Code-Reihenfolge: env1-3, lfo1-4, seq1-4, velocity (0xD), key (0xE), mod1-mod10 (0xF-0x18), pitchbend (0x19) ...: MAC1-4 werden als "mod5"-"mod8" gespeichert | Strings 0x080CCC84 ff. | gelesen |
| Liste | JOEBOX duck.c: Source-Liste 16 -> 20 (Namen, Codes, drei Zaehler in patches/duck.py) | test_duck.py (angepasst), test_jb.py | durch Emulation bestaetigt |
| Werte | macro_tick aus duck_block (jeder Block): 30 ms Gleiten auf 0/1, Zustand SRAM4 0x38003F40 (Magic, jeder Boot aus) | test_jb.py | durch Emulation bestaetigt |
| Knoepfe | JOEBOX solo.c: das rechte Feld des Pads-Bildschirms (Knopf-Panel, btn_at {0x214, 0x174, 0xD4, 0x34} = von UNTEN nach oben, Renode-Bild; sein Kommentar sagt "top to bottom") bekommt Position 0 = MAC1-4 (IDs 0x1F4-0x1F7, MAC1 oben), 1 Clipboard, 2 MUTE/SOLO, 3 Velocity-Slider; Stepper 3 -> 4; beim Zeigen (0x67) wird das Panel der Position angewendet | test_solo.py (angepasst), Renode-Screenshot | durch Emulation bestaetigt |
| Bank 1 | Logik in Bank 2 (Tick, Klick, Lichter, ohne Bank 2 kein Makro); dafuer auch fx3_send und die Smooth-Entscheidung (pk_smooth_decide) nach Bank 2: 184 Byte frei | Build | - |


## Boot-Loop nach dem Bank-2-Neustart (2026-10-21)

Am Geraet (fe16a01f und beide Bisect-Builds ohne Makros / ohne USB-in): erster Start in Ordnung (Pads-Bildschirm,
Makros), nach dem Neustart des Bank-2-Loaders Schleife in einem fruehen Zustand. Ursache: fx3_run schaltete die
D2-SRAM-Takte (RCC_AHB2ENR SRAM1-3EN) nur ein, solange FX3s Magic in SRAM4 ungueltig war. Ein Reset loescht das RCC,
nicht SRAM4 (auch kurzes Aus/An nicht zuverlaessig): mit dem Magic aus dem vorigen Lauf greift der erste Block nach dem
Neustart (Bank 2 jetzt gepaart) ungetaktet auf D2-SRAM zu - zuerst pk_fx3_add (FX3-Send eines Pads) auf den Akkumulator
0x30044000 -, Bus-Fehler, JOEBOX-Fehlerbehandlung startet neu, Magic weiter gueltig: Schleife. Renode modelliert
Takt-Gating nicht (Notiz "Takt der D2-SRAMs ... offen"), daher nur am Geraet.
Korrektur: pk_d2_clocks() vor jedem D2-Zugriff (fx3_run, pk_fx3_add). test_jb.py "warm reset": RCC geloescht, Magic
gesetzt, Speicher-Hook auf D2 - alter Build schlaegt fehl (Zugriffe ab 0x30044000 ungetaktet), neuer gruen.
Status: **hardware-verified** (b437d833 bootet nach dem Bank-2-Neustart, Rueckmeldung 2026-10-21).
Diagnose-Build (build.py --diag, JOEBOX FAULT_SHOW) passt nicht in Bank 1 (568 Byte zu viel; JOEBOX kompiliert immer
alle Quellen, Gruppen sparen keinen Code).

## Kopfhoerer auf Out 3 (pk_hpout3, 2026-10-21)

| Thema | Befund | Beleg | Status |
|---|---|---|---|
| Busse | FUN_0806002c(a, b, c, ...) wandelt drei Stereo-Busse fuer den Wandler: a = Kopfhoerer-Mix, b = Out 3, c = Out 1 (JOEBOX usbdev.c, aus Aufnahmen); JOEBOX' usbaud_tap haengt dort | usbdev.c | gelesen |
| Schalter | Out 3 Vol (0xBD, Prozent 0..1000) wird nach unserem Registrierungsblock registriert (Aufruf 0x0808D51C, Index 152 > 131): dieser Aufruf geht an out3_register, das nur fuer 0xBD max 1010 setzt; > 1000 = Spiegeln | Unicorn-Lauf der Registrierung, test_jb.py | durch Emulation bestaetigt |
| Spiegeln | usbaud_tap: fw_to_dac(a, out3_mirror() ? a : b, c, ...); der USB-Ring bekommt weiter b (USB 5-6 = echtes Out 3) | test_jb.py (Wandler-Argument) | durch Emulation bestaetigt |
| Anzeige | Prozent-Text (Typ 8) per snprintf in zwei Widget-Klassen: FUN_080a9120 (Param-Id +0x94, Wert +0x98, Aufruf 0x080A92B0) und FUN_080b0528 = Tools-Listenzeilen (Widget-Id +0x14 = Param-Id, Rohwert +0x34, Aufruf 0x080B0642; per Renode-Speicherauszug der Zeile "Out 3 Vol:" bestimmt): fuer 0xBD > 1000 "Mirror HP" | test_jb.py, Renode-Screenshot | durch Emulation bestaetigt |

