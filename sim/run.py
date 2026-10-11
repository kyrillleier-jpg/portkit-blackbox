"""Run the simulated Bitbox micro through a sequence of actions and take screenshots.

  python3 sim/run.py [--image stock|pk|<path>] [--sd out/sim/sd.img] <actions...>
  actions: wait <s> | press <HOME|TOOLS|LEFT|RIGHT> | shot <name> | hook <addr> <label> | ticks | py <code>
           capture <name> | capture-stop | input <raw> | set <param id> <value> | midi <hex> | note <nr> <s>
           tap <x> <y> [<s>] | touch <x> <y> | release (screen coordinates) | dump <addr> <len> <name>
  e.g.     python3 sim/run.py --image pk wait 12 shot pads press TOOLS wait 1 shot tools press LEFT wait 1 shot comp

Screenshots go to out/sim/<name>.png (LTDC composition, sim/screenshot.py). Renode: ~/tools/renode (see README).
Buttons (table 0x24009da4, polled by 0x08041a50 from the engine block 0x08093e48, i.e. only while audio runs; active
low, 25 ms debounce; index = table position, as flag +0xc14 is set at run time - else 3 - position, checked in the
simulation): HOME = PG3, TOOLS = PD4, LEFT = PC13, RIGHT = PB13. All four are held high (released) from the start.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.join(ROOT, "sim")
OUT = os.path.join(ROOT, "out", "sim")
RENODE = os.path.expanduser("~/tools/renode/Renode.app/Contents/MacOS/renode")
IMAGES = {"stock": os.path.join(ROOT, "firmware", "MICRO.BIN"),
          "pk": os.path.join(ROOT, "out", "fidelity+pages+padpages+sound+reverb+fx3+master+cave", "MICRO.BIN")}
BUTTONS = {"HOME": ("gpioPortG", 3), "TOOLS": ("gpioPortD", 4), "LEFT": ("gpioPortC", 13), "RIGHT": ("gpioPortB", 13)}
PRESS_S = 0.1
TOUCH_FLIP_Y = os.environ.get("SIM_TOUCH_FLIP_Y", "1") == "1"   # the UI's y counts from the bottom (checked: see README)
MIDI_INS = ("uart4", "usart6")                               # their TX carries MIDI clock (0xf8): the two MIDI ports
UARTS = ("usart1", "usart2", "usart3", "uart4", "uart5", "usart6", "uart7", "uart8", "lpuart1")


def body(path):
    return [l for l in open(path).read().splitlines() if l.strip() and not l.startswith("#")]


def build(image, sd, actions):
    lines = [f"include @{os.path.join(SIM, 'PortkitAudioDMA.cs')}", f"include @{os.path.join(SIM, 'PortkitGT911.cs')}",
             f"$bin=@{image}", f"$repl=@{os.path.join(SIM, 'micro.repl')}", f"include @{os.path.join(SIM, 'boot.resc')}"]
    for port, pin in BUTTONS.values():
        lines.append(f"sysbus.{port} OnGPIO {pin} true")
    lines += [l.replace("$simdir", SIM).replace("$sdimg", sd) for l in body(os.path.join(SIM, "sd.resc"))]
    for u in UARTS:                                          # serial output of every UART -> out/sim/uart_<name>.txt
        lines.append(f"sysbus.{u} CreateFileBackend @{os.path.join(OUT, 'uart_' + u + '.txt')} true")
    shots = []
    i = 0
    while i < len(actions):
        act = actions[i]
        if act == "wait":
            lines.append(f'emulation RunFor "{float(actions[i + 1])}"')
            i += 2
        elif act == "press":
            port, pin = BUTTONS[actions[i + 1].upper()]
            lines += [f"sysbus.{port} OnGPIO {pin} false", f'emulation RunFor "{PRESS_S}"',
                      f"sysbus.{port} OnGPIO {pin} true", f'emulation RunFor "{PRESS_S}"']
            i += 2
        elif act == "hook":                                  # hook <addr> <label>: log each time it runs
            lines.append(f'cpu AddHook {actions[i + 1]} "self.Log(LogLevel.Warning, \'HOOK {actions[i + 2]} r0=0x%x r1=0x%x\' % '
                         f'(self.GetRegisterUnsafe(0).RawValue, self.GetRegisterUnsafe(1).RawValue))"')
            i += 3
        elif act == "ticks":                                 # audio clock ticks so far (log)
            lines.append('python "print(\'AUDIO TICKS\', self.Machine[\'sysbus.audioDma\'].Ticks)"')
            i += 1
        elif act == "capture":                               # capture <name>: output (DMA2 stream 1) -> out/sim/<name>.raw
            lines.append(f'python "self.Machine[\'sysbus.audioDma\'].CaptureTo(1, \'{os.path.join(OUT, actions[i + 1] + ".raw")}\')"')
            i += 2
        elif act == "capture-stop":
            lines.append('python "self.Machine[\'sysbus.audioDma\'].CaptureStop()"')
            i += 1
        elif act == "input":                                 # input <raw file>: into DMA2 stream 5 (SAI1 B), looped
            lines.append(f'python "self.Machine[\'sysbus.audioDma\'].InputFrom(5, \'{os.path.abspath(actions[i + 1])}\')"')
            i += 2
        elif act == "set":                                   # set <id> <value>: settings store (app +0x7fd0) entry
            lines.append(f'python "import sdhook; sdhook.store_set(self.Machine.SystemBus, 0x24013cb0 + 0x7fd0, {actions[i + 1]}, {actions[i + 2]})"')
            i += 3
        elif act == "midi":                                  # midi <hex bytes, e.g. 903c64>: into both MIDI ins
            data = bytes.fromhex(actions[i + 1])
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in data]
            i += 2
        elif act == "note":                                  # note <nr> <seconds>: note on (ch 1, vel 100) .. off
            nr, dur = int(actions[i + 1]), float(actions[i + 2])
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in (0x90, nr, 100)]
            lines.append(f'emulation RunFor "{dur}"')
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in (0x80, nr, 0)]
            i += 3
        elif act == "tap":                                   # tap <x> <y> [<s>]: screen coordinates (screenshot, top left)
            x, y = int(actions[i + 1]), int(actions[i + 2])
            dur = 0.15
            i += 3
            if i < len(actions) and actions[i].replace(".", "").isdigit():
                dur = float(actions[i])
                i += 1
            ux, uy = x, (239 - y) if TOUCH_FLIP_Y else y
            lines += [f'python "self.Machine[\'sysbus.i2c1.touch\'].Touch({ux}, {uy})"', f'emulation RunFor "{dur}"',
                      'python "self.Machine[\'sysbus.i2c1.touch\'].Release()"', 'emulation RunFor "0.15"']
        elif act == "touch":                                 # touch <x> <y>: finger down (screen coordinates), stays
            x, y = int(actions[i + 1]), int(actions[i + 2])
            uy = (239 - y) if TOUCH_FLIP_Y else y
            lines.append(f'python "self.Machine[\'sysbus.i2c1.touch\'].Touch({x}, {uy})"')
            i += 3
        elif act == "release":
            lines.append('python "self.Machine[\'sysbus.i2c1.touch\'].Release()"')
            i += 1
        elif act == "dump":                                  # dump <addr> <len> <name>: append memory to out/sim/<name>.bin
            path = os.path.join(OUT, actions[i + 3] + ".bin")
            lines.append(f'python "b=self.Machine.SystemBus; f=open(\'{path}\', \'ab\'); '
                         f'f.write(bytes(bytearray(b.ReadBytes({actions[i + 1]}, {actions[i + 2]})))); f.close()"')
            i += 4
        elif act == "py":                                    # py <monitor python>: raw monitor python line
            lines.append('python "' + actions[i + 1] + '"')
            i += 2
        elif act == "shot":
            d = os.path.join(OUT, "shot_" + actions[i + 1])
            os.makedirs(d, exist_ok=True)
            lines += [l.replace("$shot", d) for l in body(os.path.join(SIM, "screenshot.resc"))]
            shots.append((actions[i + 1], d))
            i += 2
        else:
            raise SystemExit(f"unknown action {act}")
    lines.append('python "self.Machine[\'sysbus.audioDma\'].CaptureStop()"')
    lines.append("quit")
    return lines, shots


def main(a):
    image, sd = IMAGES["stock"], os.path.join(OUT, "sd.img")
    while a and a[0].startswith("--"):
        if a[0] == "--image":
            image = IMAGES.get(a[1], a[1])
        elif a[0] == "--sd":
            sd = os.path.abspath(a[1])
        a = a[2:]
    os.makedirs(OUT, exist_ok=True)
    lines, shots = build(image, sd, a)
    resc = os.path.join(OUT, "run.resc")
    open(resc, "w").write("\n".join(lines) + "\n")
    with open(os.path.join(OUT, "run.log"), "w") as log:
        r = subprocess.run([RENODE, "--console", "--disable-gui", "--plain", resc], stdout=log, stderr=subprocess.STDOUT,
                           timeout=1800)
    print("renode exit", r.returncode)
    for name, d in shots:
        subprocess.run([sys.executable, "-I", os.path.join(SIM, "screenshot.py"), d, os.path.join(OUT, name + ".png")])


if __name__ == "__main__":
    main(sys.argv[1:])
