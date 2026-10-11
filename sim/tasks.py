"""FreeRTOS tasks in a RAM dump of the simulated Bitbox micro: name, priority, state list, and where each one is
blocked (PC / LR from its saved context). TCB layout (FreeRTOS 10, CM7 with FPU): +0 pxTopOfStack, +4 state list
item (+0x10 container), +0x18 event list item (+0x28 container), +0x2c priority, +0x34 name[16].

  python3 sim/tasks.py out/sim   (axi.bin 0x24000000, dtcm.bin 0x20000000, sram.bin 0x30000000)
"""
import os
import struct
import sys

CUR = 0x24013724                      # pxCurrentTCB (PendSV 0x08058534, literal 0x08058594)
NAMES = (b"defaultTask", b"audioTask", b"IDLE", b"USBH_Thread", b"Tmr Svc")


def main(d):
    regs = [(0x24000000, open(os.path.join(d, "axi.bin"), "rb").read()),
            (0x20000000, open(os.path.join(d, "dtcm.bin"), "rb").read()),
            (0x30000000, open(os.path.join(d, "sram.bin"), "rb").read())]

    def rd(a):
        for base, b in regs:
            if base <= a < base + len(b) - 3:
                return struct.unpack_from("<I", b, a - base)[0]
        return None

    cur = rd(CUR)
    for base, b in regs:
        for nm in NAMES:
            i = b.find(nm + b"\0")
            while i >= 0:
                tcb = base + i - 0x34
                top = rd(tcb)
                if top and (0x20000000 <= top < 0x24080000 or 0x30000000 <= top < 0x30048000):
                    lr_exc = rd(top + 32)
                    hw = top + 36 + (64 if lr_exc is not None and not (lr_exc & 0x10) else 0)
                    pc, lr = rd(hw + 24), rd(hw + 20)
                    print(f"{nm.decode():12s} tcb {tcb:#x} prio {rd(tcb + 0x2c)} state-list {rd(tcb + 0x14):#x} "
                          f"event-list {rd(tcb + 0x28) or 0:#x} {'RUNNING' if tcb == cur else ''}"
                          f" pc {pc:#x} lr {lr:#x}" if pc is not None else "")
                i = b.find(nm + b"\0", i + 1)


if __name__ == "__main__":
    main(sys.argv[1])
