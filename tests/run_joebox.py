"""JOEBOX's own test suites (out/bb/jb/tree/test_*.py) on the last build, in parallel.

  python3 -I tests/run_joebox.py [-j N] [name ...]     -> out/bb/jb/tree/out/<suite>.log, a summary

The suites are independent (each emulates the image on its own); the slow ones (Munchi, Confetti, FX2 run seconds of
audio through the emulated firmware) start first, so the wall time is about the slowest suite instead of the sum.
Names (e.g. usbdev solo) run only those. Exit status 1 if any suite fails.
"""
import concurrent.futures
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.join(ROOT, "out", "bb", "jb", "tree")
SLOW = ["test_munchi.py", "test_confetti.py", "test_fx2.py"]      # measured: ~200 s, ~110 s, ~55 s


def run(suite):
    t0 = time.time()
    with open(os.path.join(TREE, "out", suite + ".log"), "w") as log:
        rc = subprocess.run([sys.executable, suite], cwd=TREE, stdout=log, stderr=subprocess.STDOUT).returncode
    first = ""
    if rc:
        for line in open(os.path.join(TREE, "out", suite + ".log")):
            if "FAIL" in line or "Error" in line:
                first = line.strip()[:160]
                break
    return suite, rc, time.time() - t0, first


def main(argv):
    jobs = os.cpu_count() or 4
    if "-j" in argv:
        jobs = int(argv[argv.index("-j") + 1])
        argv = argv[:argv.index("-j")] + argv[argv.index("-j") + 2:]
    suites = sorted(os.path.basename(p) for p in glob.glob(os.path.join(TREE, "test_*.py")))
    if argv:
        suites = [s for s in suites if s[5:-3] in argv or s in argv]
    suites.sort(key=lambda s: SLOW.index(s) if s in SLOW else len(SLOW))
    os.makedirs(os.path.join(TREE, "out"), exist_ok=True)
    t0, failed = time.time(), 0
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        for suite, rc, dt, first in pool.map(run, suites):
            if rc:
                failed += 1
                print(f"FAIL {suite} ({dt:.0f} s): {first}")
    print(f"{len(suites)} suites, {failed} failed, {time.time() - t0:.0f} s with {jobs} at a time")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
