"""Test signals for the simulation (48 kHz, 16-bit stereo WAV): a drum loop (kick / snare / hats, 120 BPM, 2 bars)
for the compressor, a sustained synth chord (saw pad) for the distortion.

  python3 sim/testsignals.py <dir>      -> <dir>/drums.wav, <dir>/chord.wav
"""
import math
import os
import random
import struct
import sys
import wave

SR = 48000


def write(path, left, right=None):
    right = right or left
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<hh", int(max(-1, min(1, a)) * 32000), int(max(-1, min(1, b)) * 32000))
                               for a, b in zip(left, right)))


def drums(bars=2, bpm=120):
    beat = 60 / bpm
    n = int(SR * beat * 4 * bars)
    out = [0.0] * n
    rnd = random.Random(1)

    def add(t0, gen, dur):
        s0 = int(t0 * SR)
        for k in range(int(dur * SR)):
            if s0 + k < n:
                out[s0 + k] += gen(k / SR)

    kick = lambda t: math.sin(2 * math.pi * (50 * t + 60 * (1 - math.exp(-t * 30)) / 30)) * math.exp(-t * 7) * 0.9
    snare = lambda t: (rnd.uniform(-1, 1) * 0.6 + math.sin(2 * math.pi * 190 * t) * 0.4) * math.exp(-t * 18) * 0.7
    hat = lambda t: rnd.uniform(-1, 1) * math.exp(-t * 60) * 0.25
    for b in range(bars * 4):
        t = b * beat
        if b % 4 in (0, 2) or b % 8 == 7:
            add(t + (beat / 2 if b % 8 == 7 else 0), kick, 0.5)
        if b % 4 in (1, 3):
            add(t, snare, 0.3)
        for h in range(2):
            add(t + h * beat / 2, hat, 0.08)
    return out


def chord(seconds=4.0):
    freqs = [110.0, 164.8, 220.0, 261.6, 329.6]          # A minor, open
    n = int(SR * seconds)
    out = []
    for k in range(n):
        t = k / SR
        env = min(1, t * 8) * min(1, (seconds - t) * 4)
        v = sum(((f * t * (1 + 0.002 * i)) % 1.0) * 2 - 1 for i, f in enumerate(freqs)) / len(freqs)
        out.append(v * env * 0.5)
    lp = 0.0                                              # soften the saws a little
    res = []
    for v in out:
        lp += 0.25 * (v - lp)
        res.append(lp)
    return res


if __name__ == "__main__":
    d = sys.argv[1]
    os.makedirs(d, exist_ok=True)
    write(os.path.join(d, "drums.wav"), drums())
    write(os.path.join(d, "chord.wav"), chord())
    print("wrote", d)
