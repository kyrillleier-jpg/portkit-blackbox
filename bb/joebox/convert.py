"""Presets and settings.tml against a JB1+pk build: what the target firmware cannot show, and the fix.

  python3 -I bb/joebox/convert.py <SD-Root | Presets-Ordner | Datei> [--to params.json] [--apply] [--json]

Without --apply it only reports. With --apply it first zips every file it will change (out/bb/jb/convert/), then
rewrites only the changed attribute values; every other byte of the file stays as it was (the firmware's files are
not strict XML, a parser round trip would change them).

The firmware saves values as integers under the parameter's XML name (preset.xml: <params name="value" .../> per
cell; checked against presets saved by a 3.1.x Blackbox). Every list portkit and JOEBOX extend is extended at the
END, so an index that is inside the target's list means the same entry in every build; only an index past the end
needs a decision, and only when the all-features build has that entry:
  - FALLBACK below (the nearest stock entry), else entry 0.
portkit's own numbers (pk*) outside the target's min..max are clamped; stock and JOEBOX values are never judged by
their registered range (it is not the range of the saved value: samlen is in samples, eqtype is registered 0..0). Parameters the target does not register are reported and left in
the file (their value is lost only when the firmware saves that preset again: nicht verifiziert).
Not touched: evtcond (JOEBOX's Note Conditions reorder that list; it is saved per note event), modsource src/dest
strings.
--to: the target build's manifest (tests/manifest_jb.py writes it next to each build), default the last build.
Names in the report come from out/bb/jb/params_full.json (the all-features build), when present.

settings.tml: same rule for every attribute whose name is a parameter (format of that file: nicht verifiziert).
"""
import argparse
import json
import os
import re
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JBOUT = os.path.join(ROOT, "out", "bb", "jb")

# xml name: {entry name a lower build lacks: entry to use instead}
FALLBACK = {
    "synctype": {"1/32": "1/16"},
    "globcomp": {"SSL": "Glue"},
    "recinput": {"FX": "Resam", "USB": "L+R"},
    "insinput": {"USB": "Off"},
    "interpqual": {k: "Normal" for k in ("SP1200", "SP-12", "S950", "MPC60", "SP Raw", "S950 Lo", "SP 45",
                                         "16k", "12k", "10k", "8k", "6k", "4k", "2k")},
}
SKIP = {"evtcond"}
ATTR = re.compile(r'(\s)([A-Za-z0-9_]+)="(-?[0-9]+)"')
PARAMS_TAG = re.compile(r"<params\b[^>]*>")
ANY_TAG = re.compile(r"<[A-Za-z][^>]*>")


def load(p):
    return json.load(open(p))["params"] if p and os.path.exists(p) else {}


def files(path):
    if os.path.isfile(path):
        return [path]
    out = []
    st = os.path.join(path, "settings.tml")
    if os.path.isfile(st):
        out.append(st)
    pre = os.path.join(path, "Presets") if os.path.isdir(os.path.join(path, "Presets")) else path
    for d in sorted(os.listdir(pre)):
        f = os.path.join(pre, d, "preset.xml")
        if os.path.isfile(f):
            out.append(f)
    return out


def fix(xml, v, t, src):
    """(new value or None, note). Only what differs between builds: a stock parameter's registered range is not
    the range of its saved values (samlen/loopend are in samples, eqtype is registered 0..0), so stock values are
    never judged by it."""
    if t["type"] == 5:
        n = t["count"]
        if 0 <= v < n or not src or src.get("type") != 5 or not (n <= v < src["count"]):
            return None, None                     # valid here, or not an entry some build adds: left alone
        name = src["names"][v] if v < len(src.get("names", [])) else None
        want = FALLBACK.get(xml, {}).get(name)
        new = t["names"].index(want) if want in t.get("names", []) else 0
        what = f"'{name}'" if name else f"Index {v}"
        return new, f"{what} gibt es hier nicht -> '{t['names'][new] if t.get('names') else new}'"
    if not xml.startswith("pk"):
        return None, None
    lo, hi = t["min"], t["max"]
    if lo <= v <= hi:
        return None, None
    new = min(max(v, lo), hi)
    return new, f"{v} außerhalb {lo}..{hi} -> {new}"


def scan(path, target, full):
    raw = open(path, "rb").read()
    text = raw.decode("latin-1")                  # 1:1 bytes <-> chars, so the rewrite keeps every other byte
    tags = ANY_TAG if os.path.basename(path).lower() == "settings.tml" else PARAMS_TAG
    changes, missing, notes = [], {}, []
    edits = []
    for m in tags.finditer(text):
        for a in ATTR.finditer(m.group(0)):
            xml, v = a.group(2), int(a.group(3))
            if xml in SKIP:
                continue
            t = target.get(xml)
            if t is None:
                if xml in full or xml.startswith("pk"):
                    missing[xml] = missing.get(xml, 0) + 1
                continue
            new, note = fix(xml, v, t, full.get(xml))
            if new is not None:
                changes.append({"param": xml, "label": t["label"], "from": v, "to": new, "note": note})
                s = m.start() + a.start(3)
                edits.append((s, s + len(a.group(3)), str(new)))
    if "evtcond" in text or 'cond="' in text:
        notes.append("enthält Note Conditions: nicht geprüft (JOEBOX ordnet diese Liste anders)")
    out = text
    for s, e, new in reversed(edits):
        out = out[:s] + new + out[e:]
    return {"file": path, "changes": changes, "missing": missing, "notes": notes}, out.encode("latin-1"), raw


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--to", default=os.path.join(JBOUT, "release", "params.json"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    target = load(a.to)
    if not target:
        sys.exit(f"kein Manifest: {a.to} (erst bauen: tests/manifest_jb.py)")
    full = load(os.path.join(JBOUT, "params_full.json"))
    groups = json.load(open(a.to)).get("groups", [])
    reps, new = [], {}
    for f in files(a.path):
        r, data, raw = scan(f, target, full)
        reps.append(r)
        if data != raw:
            new[f] = (data, raw)
    backup = None
    if a.apply and new:
        os.makedirs(os.path.join(JBOUT, "convert"), exist_ok=True)
        backup = os.path.join(JBOUT, "convert", time.strftime("backup-%Y%m%d-%H%M%S.zip"))
        base = os.path.dirname(os.path.abspath(a.path)) if os.path.isfile(a.path) else os.path.abspath(a.path)
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
            for f, (_, raw) in new.items():
                z.writestr(os.path.relpath(os.path.abspath(f), base), raw)
        for f, (data, raw) in new.items():
            if open(f, "rb").read() != raw:
                sys.exit(f"{f} hat sich während des Laufs geändert, nichts geschrieben")
        for f, (data, _) in new.items():
            open(f, "wb").write(data)
    summary = {"target_groups": groups, "files": len(reps), "changed_files": len(new),
               "changes": sum(len(r["changes"]) for r in reps), "applied": bool(a.apply and new), "backup": backup,
               "reports": reps}
    if a.json:
        print("CONVERT-JSON " + json.dumps(summary))
    for r in reps:
        if not (r["changes"] or r["missing"] or r["notes"]):
            continue
        print(f"== {r['file']}")
        for c in r["changes"]:
            print(f"   {c['param']} ({c['label']}): {c['note']}")
        for k, n in sorted(r["missing"].items()):
            print(f"   {k}: von dieser Firmware nicht registriert ({n}x), bleibt in der Datei")
        for n in r["notes"]:
            print(f"   {n}")
    verb = "geändert" if a.apply else "würden geändert"
    print(f"{summary['files']} Dateien geprüft, {summary['changes']} Werte in {summary['changed_files']} Dateien {verb}"
          + (f"; Sicherung: {backup}" if backup else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
