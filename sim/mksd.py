"""SD card image for the simulation from a directory tree (FAT32 with MBR, macOS hdiutil).

  python3 sim/mksd.py <tree dir> <image> [--size 256m]

The tree is copied without extended attributes; macOS's ._* / .fseventsd files are removed.
"""
import os
import shutil
import subprocess
import sys
import tempfile


def main(a):
    size = "256m"
    if "--size" in a:
        size = a[a.index("--size") + 1]
        a = a[:a.index("--size")]
    tree, img = os.path.abspath(a[0]), os.path.abspath(a[1])
    tmp = tempfile.mkdtemp(dir=os.path.dirname(img))
    try:
        base = os.path.join(tmp, "sd")
        subprocess.run(["hdiutil", "create", "-quiet", "-size", size, "-fs", "MS-DOS FAT32", "-volname", "BITBOX",
                        "-layout", "MBRSPUD", "-type", "UDIF", base], check=True)
        subprocess.run(["hdiutil", "convert", "-quiet", base + ".dmg", "-format", "UDTO", "-o", base], check=True)
        mnt = os.path.join(tmp, "mnt")
        os.makedirs(mnt)
        subprocess.run(["hdiutil", "attach", "-quiet", "-imagekey", "diskimage-class=CRawDiskImage", "-nobrowse",
                        "-mountpoint", mnt, base + ".cdr"], check=True)
        try:
            subprocess.run(["cp", "-RX", tree + "/.", mnt], check=True)
            subprocess.run(["dot_clean", "-m", mnt], check=False)
            for root, dirs, files in os.walk(mnt):
                for f in files:
                    if f.startswith("._"):
                        os.remove(os.path.join(root, f))
            shutil.rmtree(os.path.join(mnt, ".fseventsd"), ignore_errors=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", mnt], check=True)
        shutil.move(base + ".cdr", img)
        print("wrote", img)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
