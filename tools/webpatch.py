"""Turn a built image into a patch for the browser patcher (docs/index.html), in blackbox-mod's patch format
(docs/blackbox-mod-*.json there), so its apply.py can apply ours too.

The patch holds only what this project adds or changes: the bytes that differ from stock (with their offsets), the
bytes appended after the stock image, and whole extra card files that are this project's own code (BBEXTRA.BIN).
No byte of the stock firmware: the stock image is identified by SHA-256 only, and the page checks the result's
SHA-256 against the build it was made from.

Extra guard (check_no_stock): no 32-byte window of the patch's data may occur anywhere in the stock image (stock
code or tables copied into the cave would show up here). Skipped: windows of one repeated byte (padding) and windows
that are nothing but 32-bit addresses inside the stock image (pointer tables to stock strings, e.g. JOEBOX's
cond_names: addresses, not firmware content).

Used by tools/make_web.py.
"""
import hashlib
import re
import struct

WIN = 32


def diff(stock, built):
    assert len(built) >= len(stock), "built image shorter than stock"
    writes, i = [], 0
    while i < len(stock):
        if stock[i] == built[i]:
            i += 1
            continue
        j = i
        while j < len(stock) and stock[j] != built[j]:
            j += 1
        writes.append({"offset": i, "bytes": built[i:j].hex()})
        i = j
    return writes, built[len(stock):]


def _pointer_runs(data, size, base):
    """[start, end) byte ranges of >= 8 aligned words that all hold addresses inside the stock image"""
    runs, k = [], 0
    while k + 4 <= len(data):
        j = k
        while j + 4 <= len(data) and base <= struct.unpack_from("<I", data, j)[0] < base + size:
            j += 4
        if j - k >= 32:
            runs.append((k, j))
        k = j + 4 if j > k else k + 4
    return runs


def check_no_stock(stock, chunks, base=0x08040000):
    """chunks: [(label, bytes)]. Returns [(label, offset in chunk, stock offset)] of windows found in stock;
    windows inside pointer tables are not scanned."""
    index = {}
    for k in range(0, len(stock) - WIN + 1):
        w = stock[k:k + WIN]
        if w.count(w[0]) != WIN:
            index.setdefault(hash(w), []).append(k)
    hits = []
    for label, data in chunks:
        cuts = [0]
        for a, b in _pointer_runs(data, len(stock), base):
            cuts += [a, b]
        cuts.append(len(data))
        for lo, hi in zip(cuts[0::2], cuts[1::2]):
            k = lo
            while k <= hi - WIN:
                w = data[k:k + WIN]
                if w.count(w[0]) != WIN:
                    s = next((s for s in index.get(hash(w), ()) if stock[s:s + WIN] == w), None)
                    if s is not None:
                        hits.append((label, k, s))
                        k += WIN
                        continue
                k += 1
    return hits


def make(name, version, stock_version, stock, built, extras=(), features=(), notes=None, allow=()):
    """extras: [(file name, bytes)] written next to the image.
    allow: [(start, end, reason)] byte ranges of the appended data whose match with stock is known and explained
    (values written out in the mod's own source that equal a stock table); every other match stops the build."""
    writes, append = diff(stock, built)
    chunks = [("append", append)] + [(f"write@{w['offset']:#x}", bytes.fromhex(w["bytes"])) for w in writes]
    chunks += [(n, b) for n, b in extras]
    hits = [h for h in check_no_stock(stock, chunks)
            if not (h[0] == "append" and any(a <= h[1] and h[1] + WIN <= b for a, b, _ in allow))]
    if hits:
        raise SystemExit("stock bytes in the patch (label, offset, stock offset): " + ", ".join(
            f"{l} {o:#x} = stock {s:#x}" for l, o, s in hits[:20]) + ". Nothing written.")
    patch = {
        "name": name,
        "version": version,
        "slug": re.sub(r"[^a-z0-9.]+", "-", version.lower()).strip("-"),
        "stock_version": stock_version,
        "stock_size": len(stock),
        "stock_sha256": hashlib.sha256(stock).hexdigest(),
        "output_size": len(built),
        "output_sha256": hashlib.sha256(built).hexdigest(),
        "writes": writes,
        "append": append.hex(),
    }
    if extras:
        patch["extra"] = [{"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest(), "bytes": b.hex()}
                          for n, b in extras]
    if features:
        patch["features"] = list(features)
    if notes:
        patch["notes"] = notes
    return patch


def apply(patch, stock):
    """The same steps as the page and blackbox-mod's apply.py; returns {file name: bytes}."""
    if hashlib.sha256(stock).hexdigest() != patch["stock_sha256"]:
        raise ValueError("not the stock firmware")
    data = bytearray(stock)
    for w in patch["writes"]:
        b = bytes.fromhex(w["bytes"])
        data[w["offset"]:w["offset"] + len(b)] = b
    data += bytes.fromhex(patch["append"])
    if hashlib.sha256(data).hexdigest() != patch["output_sha256"]:
        raise ValueError("result check failed")
    out = {"image": bytes(data)}
    for x in patch.get("extra", []):
        b = bytes.fromhex(x["bytes"])
        assert hashlib.sha256(b).hexdigest() == x["sha256"] and len(b) == x["size"]
        out[x["name"]] = b
    return out
