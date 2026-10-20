"""Build, test and publish the browser patcher: docs/index.html (GitHub Pages) + docs/patches/<slug>.json.

  python3 -I tools/make_web.py [--skip-tests] [--allow-dirty]

1. bb/joebox/build.py with every group (the combination the full test covers), tests/smoke_jb.py, tests/test_jb.py.
2. tools/webpatch.py: patch = only our bytes (no stock byte; checked), with the result's SHA-256.
3. The page (tools/patcher.html) with the patch inlined: works from GitHub Pages and as a downloaded file.
The JSON is blackbox-mod's patch format, so its apply.py applies it too.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "bb", "joebox"))
import features  # noqa: E402
import webpatch  # noqa: E402

PY = sys.executable
REL = os.path.join(ROOT, "out", "bb", "jb", "release")
STOCK = os.path.join(ROOT, "firmware", "BLACKBOX.bin")
ELF = os.path.join(ROOT, "out", "bb", "jb", "tree", "out", "cave.elf")
REPO = "https://github.com/kyrillleier-jpg/portkit-blackbox"
# matches with stock that are explained (see tools/webpatch.py): symbol -> reason
ALLOW = {"rate_beats": "JOEBOX lfo.c: LFO sync lengths (128 .. 1/16 beats, with triplets) written out in its source; same musical values "
                       "as the stock table"}

CONFIG = {
    "lead": "The portkit features from the bitbox micro, merged into Justin Joe's JOEBOX&nbsp;1, for the original "
            "1010music Blackbox. Patch your own stock firmware right here; nothing is uploaded.",
    "stockName": "BLACKBOX.bin",
    "stockHint": "The unmodified 3.1.9 from 1010music (the <code>BLACKBOX.bin</code> inside the download zip).",
    "stockSource": "Download the 3.1.9 firmware from 1010music and use the <code>BLACKBOX.bin</code> inside the zip.",
    "outName": "BLACKBOX.bin",
    "install": [
        "Keep your stock <code>BLACKBOX.bin</code> as a backup.",
        "Copy <b>both</b> files, <code>BLACKBOX.bin</code> and <code>BBEXTRA.BIN</code>, to the root of the microSD "
        "card. They are a matched pair; the <code>BBEXTRA.BIN</code> of the public JOEBOX release does not fit.",
        "Hold <b>BACK + INFO</b> while powering on to install. The unit restarts once while it writes the second "
        "flash bank.",
        "The splash and the Tools page show <b>JB1+pk</b>. A <code>!</code> in front of the load readout means "
        "<code>BBEXTRA.BIN</code> is missing or does not match.",
        "To go back: the same steps with the stock <code>BLACKBOX.bin</code>.",
    ],
    "footer": f'<a href="{REPO}">portkit-blackbox</a> · MIT · contains JOEBOX 1 by Justin Joe (MIT, '
              f'<a href="{REPO}/blob/main/THIRD_PARTY.md">notices</a>) · not affiliated with 1010music',
}


def run(title, cmd):
    print(f"## {title}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def symbol_ranges(names):
    nm = subprocess.run(["arm-none-eabi-nm", "-S", ELF], capture_output=True, text=True, check=True).stdout
    out = {}
    for line in nm.splitlines():
        p = line.split()
        if len(p) == 4 and p[3] in names:
            out[p[3]] = (int(p[0], 16), int(p[0], 16) + int(p[1], 16))
    missing = set(names) - set(out)
    assert not missing, f"allowlisted symbols not in the build: {missing}"
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args(argv)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        sys.exit("uncommitted changes: commit first (the page names the commit it was built from), or --allow-dirty")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    run("Build (all groups)", [PY, "-I", "bb/joebox/build.py"])
    if not a.skip_tests:
        run("Smoke test", [PY, "-I", "tests/smoke_jb.py"])
        run("Full test", [PY, "-I", "tests/test_jb.py"])
    info = json.load(open(os.path.join(REL, "build.json")))
    assert set(info["groups"]) == features.resolve(features.default()), "release is not the all-features build"

    stock = open(STOCK, "rb").read()
    built = open(os.path.join(REL, "BLACKBOX.bin"), "rb").read()
    extra = open(os.path.join(REL, "BBEXTRA.BIN"), "rb").read()
    base = 0x08040000 + len(stock)
    allow = [(lo - base, hi - base, ALLOW[n]) for n, (lo, hi) in symbol_ranges(set(ALLOW)).items()]
    feats = [[f[1], f"{f[3]} ({f[2]})"] for f in features.FEATURES if f[0] in info["groups"]]
    patch = webpatch.make("portkit-blackbox", info["name"], "3.1.9", stock, built, [("BBEXTRA.BIN", extra)],
                          feats, allow=allow)
    patch.update(title=f"{info['name']}: everything", source_commit=commit + ("-dirty" if dirty else ""),
                 summary="All JOEBOX 1 features plus all portkit features; the combination the full test covers.",
                 allowed_matches=[r for _, _, r in allow])
    # round trip with the same steps as the page
    files = webpatch.apply(patch, stock)
    assert files["image"] == built and files["BBEXTRA.BIN"] == extra

    os.makedirs(os.path.join(ROOT, "docs", "patches"), exist_ok=True)
    jpath = os.path.join(ROOT, "docs", "patches", f"{patch['slug']}.json")
    json.dump(patch, open(jpath, "w"), indent=1)
    page = open(os.path.join(ROOT, "tools", "patcher.html")).read()
    for k, v in (("__TITLE__", f"{info['name']} patcher · Blackbox"),
                 ("__H1__", f"portkit <span>{info['name']}</span> for Blackbox"),
                 ("__CONFIG__", json.dumps(CONFIG)),
                 ("__PATCHES__", json.dumps([patch], separators=(",", ":")))):
        assert page.count(k) == 1, k
        page = page.replace(k, v)
    open(os.path.join(ROOT, "docs", "index.html"), "w").write(page)
    print(f"docs/index.html ({len(page):,} bytes), {os.path.relpath(jpath, ROOT)}: {len(patch['writes'])} writes, "
          f"{len(patch['append']) // 2} appended, BBEXTRA.BIN {len(extra)}; output sha256 {patch['output_sha256'][:16]}, "
          f"from {patch['source_commit']}")
    print("open docs/index.html in a browser to try it; commit docs/ to publish")


if __name__ == "__main__":
    main(sys.argv[1:])
