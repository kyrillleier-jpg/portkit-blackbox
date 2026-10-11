# Bitbox micro in Renode (Probelauf)

Renode 1.17 (`~/tools/renode/Renode.app`, nicht im Repo). Nur Skripte hier; Firmware, Dumps und Bilder liegen in
`firmware/` bzw. `out/sim/` (ignoriert).

Stand (2026-10-11): Stock und gepatchtes Image booten bis zum Splash-Screen (`bitbox micro` / `portkit mod`,
Version); mit virtueller SD-Karte (`sd.resc`) mountet die App die Karte und schaltet auf den Pads-Bildschirm
(Kopfzeile "1:1 / 252M / Pads", Kacheln werden aufgebaut). Ca. 5x langsamer als Echtzeit. Kein Audio-, Touch- oder
Touchmodell. Screenshots exakt ueber die LTDC-Register (`screenshot.resc` + `screenshot.py`). Mit dem eigenen
DMA2-Modell laeuft die Audio-Engine (375 Blocks/s, ohne Klang) und damit die Tastenabfrage: Tasten lassen sich druecken.

Bedienung: `python3 sim/run.py --image pk wait 12 press TOOLS wait 1 shot tools press LEFT wait 1 shot comp`
(Aktionen: wait, press HOME|TOOLS|LEFT|RIGHT, shot <name>, hook <addr> <label>, ticks). Bilder: `out/sim/<name>.png`.

- `micro.repl`: H743-Plattform + SPI1/2/3/5, Codec PCM3168A als Dummy auf I2C1 (0x44), SAI1/2 als Python-Stub (FIFO
  "gefuellt", damit HAL_SAI_Transmit_DMA startet).
- `boot.resc`: Image bei 0x08040000, VTOR/SP/PC aus der Vektortabelle (Bootloader fehlt); zwei Renode-Workarounds fuer
  DMA2D (Konverter vor dem ersten CLUT-Laden anlegen; Interrupt getrennt, da Renode ihn auch ohne TCIE setzt).
- `sd.resc` + `sdhook.py`: virtuelle SD-Karte. Renodes SDMMC kann kein IDMA (die Firmware liest per
  HAL_SD_ReadBlocks_DMA), daher werden die fuenf FatFS-diskio-Funktionen (Tabelle 0x080BF030: init 0x08044FAC, status
  0x08045188, read 0x0804504C, write 0x080450BC, ioctl 0x08045130) per CPU-Hook aus einer Image-Datei bedient.
  Image: `hdiutil create -size 256m -fs "MS-DOS FAT32" -layout MBRSPUD`, nach `.img` (UDTO) konvertiert.
  Die SD-Init selbst ist lazy (erster Dateizugriff, Laufwerksobjekt 0x24009C80: +0x15 gemountet, +0x17 Kartenzustand).
- Touch (vermutlich): `DummyI2CSlave` an I2C1 0x5D; ohne Antwort haengt defaultTask in HAL-I2C-Timeouts.
- `tasks.py`: FreeRTOS-Tasks aus einem RAM-Dump (pxCurrentTCB 0x24013724): wo jede Task steht.
- `PortkitAudioDMA.cs`: ersetzt DMA2 (wird von Renode zur Laufzeit kompiliert). Ringpuffer-Streams bekommen auf einem
  Audiotakt (375 Hz = 128 Frames bei 48 kHz) abwechselnd HTIF / TCIF mit Interrupt; keine Sampledaten. Noetig, weil
  audioTask auf diese Interrupts wartet und die Tastenabfrage (0x08041A50) nur im Engine-Block 0x08093E48 laeuft.
- Tasten: Tabelle 0x24009DA4, aktiv low, 25 ms Entprellung: HOME = PG3, TOOLS = PD4, LINKS = PC13, RECHTS = PB13
  (Index = Tabellenposition, da Flag +0xC14 gesetzt ist). LEDs: Tabelle 0x24009E04 (PK2, PJ8, PJ5, PJ4, Ausgaenge).
- `run.py`: Ablauf-Runner (Skript bauen, Renode starten, Screenshots).
- `screenshot.resc` + `screenshot.py`: echtes Panel-Bild. Das Display haengt am **LTDC** (RGB-Schnittstelle, Handle
  0x24002E7C), 240 x 320 hochkant; SPI3 traegt nur die Init-Befehle des Panels. Zwei Ebenen, beide vollflaechig,
  ARGB1555, ueber Hintergrund 0x141414 gemischt (Alpha-Bit 0 = transparent): Ebene 1 Inhalt, Ebene 2 u. a. Kopfzeile.
  Das Skript liest Fenster, Format, Pitch und Pufferadresse (CFBAR) aus den Registern.
- `fb2png.py`: einzelne Puffer aus dem RAM (Diagnose). Die UI rendert 8 Bit indiziert (DMA2D FGMAR, 240 x 320, CLUT bei FGCMAR,
  ARGB8888), DMA2D wandelt nach OMAR (Puffer 0xC0025840 + n x 0x25840, ARGB1555 little endian) - Option `argb1555`.
  Die Puffer sind die LTDC-Ebenen (s. o.), daher wirken einzelne Puffer wie Fragmente.

Lauf (10 s virtuell, dann Puffer-Dump): `out/sim/dump.resc` als Vorlage, Aufruf
`~/tools/renode/Renode.app/Contents/MacOS/renode --console --disable-gui --plain <resc>`, danach
`python3 sim/fb2png.py l8 out/sim/l8.bin out/sim/clut.bin out/sim/screen.png`.

Audio-DMA (DMA2): Stream 1 = RAM 0x2407C000 -> SAI1 A (Ausgang), Stream 5 = SAI1 B -> 0x2407E000 (Eingang), beide
Ringpuffer; Stream 0 = ADC1 -> RAM. Renodes STM32DMA kennt weder Ringpuffer noch Half-Transfer -> audioTask wartet ewig.

UI-Koordinaten: y zaehlt von unten (Panel {1,149,318,72} des Pads-Bildschirms liegt im Bild bei y 19..91, oben).

Befund pkX (Simulation, am Geraet nicht verifiziert): der Titel "Pads 1-8" ueberlappt die Speicheranzeige ("252M").

Audio und Eingaben (2026-10-11):
- Mitschnitt / Einspeisung: `capture <name>` ... `capture-stop` (Ausgang, DMA2 Stream 1 -> out/sim/<name>.raw),
  `input <raw>` (Eingang, Stream 5); `wav.py` wandelt (TDM 8 Slots x 32 Bit, 48 kHz; Out 1/2 = Slot 0/1) und misst.
- Touch: `PortkitGT911.cs` (I2C1 0x5D), `tap x y [s]` / `touch x y` / `release` in Bildschirmkoordinaten; die UI zaehlt
  y von unten (geprueft: ohne Spiegelung trifft der Tipp das Panel oben).
- MIDI: `midi <hex>` / `note <nr> <s>` in die Empfaenger von UART4 und USART6 (deren TX sendet MIDI-Clock); die Bytes
  kommen an (RDR gelesen), loesen aber noch nichts aus (MIDI-Pad-Einstellung offen).
- SD-Inhalte: `mksd.py <ordner> <image>`; Preset-Format (geprueft): Presets/<Name>/preset.xml, `<document><session>`
  mit `<cell row column layer filename=".\datei.wav" type="sample"><params .../><slices/></cell>`; filename relativ
  zum Preset-Ordner. Ohne settings.tml laedt die Firmware das (einzige) Preset. Testsignale: `testsignals.py`.
- Settings direkt setzen: `set <id> <wert>` (Store app+0x7FD0, z. B. Kompressor 0x1A1.., Distortion 0x1A7..).
- Offen: Ein Tipp auf einen Pad spielt das Sample als exakt skalierte Kopie (-4,36 dB) direkt auf Out 1/2, an der
  Pad-Engine (0x080AFF60 nur einmal) und damit an Master-Distortion / Kompressor vorbei (vermutlich Vorhoeren; Grund
  offen). Klangbeispiele daher vorerst offline: `tests/render_master.py` (Firmware-Code in Unicorn, s. u.).
- `tests/render_master.py`: Settings-Store (echte Init), master_dist, Stock-Kompressor (Ctor 0x080B9D34, DSP
  0x080B9B04 ueber master_comp) blockweise auf einem echten Bus 0; `--examples out/sim/examples`.

pkX in der Simulation (2026-10-11): Tools -> Settings, LINKS -> Kompressor-Seite (Standardwerte -4 dB / 4 / 10 / 250 /
-4 dB), RECHTS RECHTS -> Distortion-Seite (Off / +12 dB / 20.4 kHz / 100 % / 0 dB), TOOLS -> naechster Tools-Bildschirm.
Kopfzeile der Master-Seiten: die der Settings-Seite (Version).

CV-Eingaenge: die 8 ADC-Kanaele (Mittelung 0x08046750, DMA2 Stream 0 -> 0x2407BCC0) sind die CV-Eingaenge (Geraet).

Naechste Schritte: Pad-Wiedergabe ueber die Engine (warum Vorhoeren?), Encoder, CV-Einspeisung, MIDI-Pads.
