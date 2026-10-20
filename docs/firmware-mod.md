---
name: firmware-mod
description: Workflow for modding a raw embedded firmware image (Cortex-M, no source) by appending own C code and detouring call sites - from hashing the input and finding functions via strings, through patch building with byte checks, Unicorn tests and Renode simulation, to preset compatibility and release. Use when reverse engineering, patching, porting features between firmware images, or extending a device's parameters/UI (e.g. 1010music Bitbox/Blackbox, portkit).
---

# Modding a firmware image

Distilled from portkit (1010music Bitbox micro 2.3.4 and Blackbox 3.1.9, merged with JOEBOX / blackbox-mod).
The method is general for raw Cortex-M images; examples point at this repo's tools.

## 0. Ground rules (do not skip)

- **Never distribute vendor data.** Firmware, patched images, disassembly listings, manuals: not committed, not sent.
  `.gitignore` covers `firmware/`, `out/`, `*.bin`. What is shared: patch sources, address lists, build scripts.
  Patch scripts may hold short expected-byte strings per site; that is an address list, not a listing.
- **Hash the input** (SHA-256) before every build and refuse anything else. Copy originals, never modify them.
- **Mark the image**: splash/version string must show it is modified (`JB1+pk`, `2.3.4-pkZD`). Bump it every build
  the user may flash, so a report from the device names the exact build.
- **No flashing without the owner's explicit go.** Before: stock image backed up, verification green
  (null repack = unpatched rebuild is byte-identical, every changed byte inside a registered range, every detour
  returns, image fits where the installer accepts it).
- **Don't invent.** Unknown address/struct/behaviour -> look it up or mark it `open` / `nicht verifiziert`.
- **Status ladder** per finding: `vermutet` (read in disassembly) -> `durch Emulation bestaetigt` (Unicorn/Renode)
  -> `hardware-verified` (only when the owner heard/saw it on the device; emulation never counts).

## 1. Orient in the image

1. Confirm it is raw code: vector table at the start (initial SP, reset vector odd = Thumb), load base from the
   reset vector's range (here 0x08040000; the bootloader is not in the file). Note the SP: it tells the RAM layout,
   which differs between devices even with a shared codebase.
2. **Strings -> literal-pool refs -> functions.** Find a UI string (`Interp:`, xml names like `globcomp`), find
   PC-relative loads of its address (`tools/xref.py`), take the enclosing function (`tools/funcof.py`,
   `tools/fstarts.py`), disassemble (`tools/dis.py`, capstone, Thumb-2).
3. Find the **central tables** early - they unlock everything else:
   - parameter table / registration function (here: id, type, label, list names/count or min/max, xml name;
     `tools/params.py`, `tools/emu_params.py` runs the init in Unicorn and dumps every registration);
   - store get/set for per-object settings (`tools/emu_store.py`);
   - screen/widget constructors (`tools/emu_layout.py`, `tools/rects.py`);
   - the audio block function and the bus/buffer structs.
4. Document every function in `re/symbols.md`-style tables: address, name, evidence, status.
5. **Porting between related images** (shared framework): compare by normalised instruction windows, not bytes -
   `tools/fmatch.py` (address -> candidates by votes), `tools/fuzzymatch.py` (whole function), `tools/falign.py`
   (addresses inside matched functions), `tools/side.py` (side by side). Strings shared verbatim are the anchors.
   All RAM addresses must be found again in the target.

## 2. Plan the patch

- **Where code goes:** a cave appended after the stock image (or a free region). Check the installer/bootloader
  limit (Blackbox: image must end below 0x08100000; overflow DSP went to flash bank 2 via JOEBOX's loader, paired by
  checksum, gated by a `live()` check - bank 2 must never call into bank 1's cave).
- **RAM for state:** measure, don't guess. Canary method: fill the candidate region with a pattern in the simulator,
  boot + load + record + play, see what the firmware touched. Register every fixed address and test that regions
  don't overlap and stay in the gap (`tests/test_ram.py`). Lesson: a "free" area above the stack turned out to be
  SD/file buffers (pkZB).
- **Hook types**, each checked against expected stock bytes before writing:
  - `BL` retarget (call site -> our function with the same signature, ours calls the original);
  - detour thunk (overwrite 4-6 bytes with `BL thunk`, thunk re-does the displaced instructions, sets the flags the
    following code expects, returns; may adjust `lr` to skip code);
  - pointer replace (vtable / table entries / string pointers);
  - constant edits (table sizes, compare immediates - e.g. `cmp r6,#3` -> `#4` for one more tab).
- **Flags matter**: when a thunk replaces `cmp; beq`, it must leave the same Z/N/C for the code after it. Test the
  flags explicitly.
- **Hook chains with another mod**: if both mods hook the same site, chain them (ours calls theirs) and record the
  order. Never silently drop the other mod's hook.

## 3. Write the code

- C for logic/DSP, small asm thunks for register-level glue.
  `arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os`,
  link at the cave address, call firmware functions through fixed addresses (`#define fw_x ((fn_t)FN(0x0804d880))`).
- Thunks preserve everything the caller expects: `push {r0-r3,ip,lr}`, `vpush {s0-s15}` around C calls from the
  audio path.
- **Integer widths:** values like dB*1000 overflow int16 (a -28.5 dB bug came from that). Use int32 for ranges.
- Keep per-parameter data **table driven** (one array of defs -> registration, defaults, pages) so ids, defaults and
  UI cannot drift apart.

## 4. Parameter ids and saved data

- **Saved data is keyed by name, not id** (here: `preset.xml` `<params name="int"/>` per pad, `settings.tml`
  global). Choose stable xml names (`pkshift`), never change them; ids may move between builds. Generate one header
  from one id file (`bb/joebox/ids.py` -> `pk_ids.h`).
- If the id table is full, **grow it** (find every place the size is baked in - here 11 sites, sizes and
  `size*28` products) and put own ids above everything stock and other mods use. Verify by running the full
  registration in Unicorn and checking for collisions.
- Check how engine handlers treat id ranges (some forward only ids <= N to the engine; above that is ignored, which is
  what you want for UI-only/own parameters).
- **Extend lists only at the end.** Then a saved index means the same entry in every build that has it; only
  "index past the end" needs handling. (Counter-example seen: a mod reordering a list puts saved values off by one.)
- Capacity limits: per-object stores have fixed slot counts; adding parameters can overflow them - raise and test.
- **Preset converter** (`bb/joebox/convert.py`): manifest of the target build (all registered params by xml name:
  `tests/manifest_jb.py`) + an all-features manifest for names; dry run by default; `--apply` zips the files first
  and rewrites only the changed attribute values in place (device files are often not strict XML - trailing NUL,
  BOM - so never round-trip through a parser).
  **Never clamp stock values to the registered min/max**: registered ranges are not the stored ranges
  (sample lengths in samples, types registered 0..0). Only touch what differs between builds.

## 5. Build and verify (automate all of it)

Build script order: hash input -> compile -> place -> apply hooks with expected-byte checks -> verify -> write
outputs + `build.json` (hashes, groups) + parameter manifest. Verification:
- every changed byte inside a registered range; every BL/pointer lands on a known symbol;
- image end below the installer limit; free cave bytes reported (watch it - one build ended with 336 bytes);
- null repack: no features -> byte-identical to stock (or to the base mod).

**Feature switches**: describe every deviation from stock as a row (feature, where on the device, what it does)
grouped by what can actually be switched together; mark groups others depend on as fixed ("core"). A local
dashboard (`bb/joebox/dashboard.py`, 127.0.0.1 only, since it needs the firmware) builds any selection, runs the
smoke test, writes the manifest and offers downloads.

## 6. Test

- **Unicorn** (`tests/bb_emu.py`, `tests/test_*.py`): map the image(s), stub firmware functions you don't want,
  call registration/DSP/thunks directly. Test: registration lists and counts, defaults, page id lists, every hook
  site's target, thunk flags for all input values, DSP against a reference implementation (bit-compare when porting
  the same DSP), CPU cost per audio block (`tests/perf.py`).
- **Test-harness pitfalls we hit:** allocations too small for adjacent structs (bus array entries of 20 bytes -
  allocate both); state left over from earlier tests (a reverb tail leaking into a later sum - reset state);
  renamed symbols after refactors. When a test fails, first prove whether the code or the test is wrong.
- **Other mod's suites** run on the merged tree; when they fail, read the log first - five "failures" were a host
  library the export step deleted. Adjust their tests only for intended changes, scripted and documented.
- **Renode** whole-system simulation (`sim/run.py`): boot, screenshots, key presses, touch, SD image
  (`sim/mksd.py`), PC trace diffs to find code paths (watchpoints on data buffers found nothing; diffing executed
  PCs between two modes found the tap). Set realistic CPU speed (`mips 480`): at Renode's default 100 MIPS missed
  audio blocks are an artefact, not a finding. Simulated SD writes may not land - recording output can stay
  unverifiable there.
- Learn the device's real UI flow from the owner (which key records, preconditions like "REC only while playing")
  instead of guessing button mappings.

## 7. Release and hand-off

- Outputs only from the build dir; `build.json` with SHA-256 per file; tell the owner exactly which files go where
  (e.g. both `BLACKBOX.bin` + `BBEXTRA.BIN` in the SD root, recovery key combo).
- List what is emulation-verified vs. what needs ears on the device; ask for targeted listening tests.
- Docs per build: feature table with status, RE notes with evidence, README with build commands.
- Commit only on request; split unrelated work into separate commits; check staged files for vendor data first.
  The repo plus the stock firmware (re-downloadable, hash in CLAUDE.md) must be enough to rebuild everything.
