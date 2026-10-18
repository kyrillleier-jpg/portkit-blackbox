"""Local dashboard for the JB1+pk build: every feature against stock, switches, build, checks, download.

  python3 bb/joebox/dashboard.py [port]       -> http://127.0.0.1:8765

Runs only on this machine (127.0.0.1): the build needs the stock firmware and the toolchain here, and neither the
firmware nor a patched image may leave it. One job at a time; the log streams into the page.
  POST /api/build {"groups": [...]}   bb/joebox/build.py --groups ..., then tests/smoke_jb.py
                                       (and tests/test_jb.py when everything is in)
  POST /api/sim                        Renode: boot the last build, screenshots of Pads, Tools, Extra
  POST /api/convert {"path", "apply"}  bb/joebox/convert.py: presets / settings.tml against the last build
  GET  /download/BLACKBOX.bin|BBEXTRA.BIN|zip
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(JB))
sys.path.insert(0, JB)
import features  # noqa: E402

PY = os.path.join(ROOT, ".venv", "bin", "python")
REL = os.path.join(ROOT, "out", "bb", "jb", "release")
SHOTS = os.path.join(ROOT, "out", "sim")
JOB = {"state": "idle", "kind": None, "log": [], "result": None, "started": None}
LOCK = threading.Lock()


def run_steps(kind, steps, after=None):
    JOB.update(state="running", kind=kind, log=[], result=None, started=time.time())
    ok = True
    for title, cmd in steps:
        JOB["log"].append(f"## {title}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("BUILD-JSON "):
                JOB["result"] = json.loads(line[11:])
                continue
            if line.startswith("CONVERT-JSON "):
                JOB["result"] = json.loads(line[13:])
                continue
            JOB["log"].append(line)
            JOB["log"] = JOB["log"][-4000:]
        if p.wait() != 0:
            JOB["log"].append(f"!! {title}: Fehler (Exit {p.returncode})")
            ok = False
            break
    if ok and after:
        after()
    JOB["state"] = "done" if ok else "failed"


def start(kind, steps, after=None):
    with LOCK:
        if JOB["state"] == "running":
            return False
        threading.Thread(target=run_steps, args=(kind, steps, after), daemon=True).start()
        return True


def sim_steps():
    info = json.load(open(os.path.join(REL, "build.json")))
    acts = ["wait", "14", "shot", "dash_pads", "press", "B7", "wait", "1.5", "shot", "dash_tools"]
    if set(info["groups"]) & {"pk_dist", "pk_fx3"}:
        acts += ["tap", "290", "222", "0.6", "wait", "1.5", "shot", "dash_extra"]
    return [("Renode: Boot und Screenshots",
             [PY, "-I", "sim/run.py", "--image", os.path.join(REL, "BLACKBOX.bin"), "--bank2",
              os.path.join(ROOT, "out", "bb", "jb", "bank2.bin"), "--repl", "blackbox.repl",
              "--sd", os.path.join(SHOTS, "sdbbclip.img"), "mips", "480"] + acts)]


def sim_result():
    JOB["result"] = {"shots": [n for n in ("dash_pads", "dash_tools", "dash_extra")
                               if os.path.exists(os.path.join(SHOTS, n + ".png"))]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, open(os.path.join(JB, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path == "/api/features":
            last = None
            if os.path.exists(os.path.join(REL, "build.json")):
                last = json.load(open(os.path.join(REL, "build.json")))
            return self.send(200, {
                "groups": {g: {"label": v[0], "origin": v[1], "core": v[2], "requires": v[3]}
                           for g, v in features.GROUPS.items()},
                "features": [{"group": f[0], "name": f[1], "where": f[2], "what": f[3]} for f in features.FEATURES],
                "last": last})
        if self.path == "/api/job":
            return self.send(200, {k: JOB[k] for k in ("state", "kind", "result", "started")} | {"log": JOB["log"][-400:]})
        if self.path.startswith("/shot/"):
            name = os.path.basename(self.path[6:])
            p = os.path.join(SHOTS, name)
            if name.startswith("dash_") and name.endswith(".png") and os.path.exists(p):
                return self.send(200, open(p, "rb").read(), "image/png")
            return self.send(404, {"error": "no such shot"})
        if self.path.startswith("/download/"):
            what = self.path[10:]
            if what in ("BLACKBOX.bin", "BBEXTRA.BIN"):
                p = os.path.join(REL, what)
                if os.path.exists(p):
                    return self.send(200, open(p, "rb").read(), "application/octet-stream",
                                     [("Content-Disposition", f'attachment; filename="{what}"')])
            if what == "zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in ("BLACKBOX.bin", "BBEXTRA.BIN", "build.json"):
                        z.write(os.path.join(REL, f), f)
                return self.send(200, buf.getvalue(), "application/zip",
                                 [("Content-Disposition", 'attachment; filename="JB1+pk.zip"')])
            return self.send(404, {"error": "no such file"})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/build":
            sel = [g for g in body.get("groups", []) if g in features.GROUPS]
            groups = features.resolve(sel)
            steps = [("Build", [PY, "-I", "bb/joebox/build.py", "--groups", ",".join(sorted(sel))]),
                     ("Smoke-Test (Unicorn)", [PY, "-I", "tests/smoke_jb.py"]),
                     ("Parameter-Manifest", [PY, "-I", "tests/manifest_jb.py"])]
            if groups == features.resolve(features.default()):
                steps.append(("Volltest (Unicorn, alle Features)", [PY, "-I", "tests/test_jb.py"]))
            ok = start("build", steps)
            return self.send(200 if ok else 409, {"started": ok})
        if self.path == "/api/sim":
            if not os.path.exists(os.path.join(REL, "build.json")):
                return self.send(409, {"started": False, "error": "erst bauen"})
            for n_ in ("dash_pads", "dash_tools", "dash_extra"):
                p = os.path.join(SHOTS, n_ + ".png")
                if os.path.exists(p):
                    os.remove(p)
            ok = start("sim", sim_steps(), sim_result)
            return self.send(200 if ok else 409, {"started": ok})
        if self.path == "/api/convert":
            path = os.path.expanduser(str(body.get("path") or "").strip())
            if not os.path.exists(path):
                return self.send(400, {"started": False, "error": f"nicht gefunden: {path}"})
            if not os.path.exists(os.path.join(REL, "params.json")):
                return self.send(409, {"started": False, "error": "erst bauen (kein Manifest)"})
            cmd = [PY, "-I", "bb/joebox/convert.py", path, "--json"] + (["--apply"] if body.get("apply") else [])
            ok = start("convert", [("Presets " + ("anpassen" if body.get("apply") else "prüfen"), cmd)])
            return self.send(200 if ok else 409, {"started": ok})
        return self.send(404, {"error": "not found"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"JB1+pk dashboard: http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
