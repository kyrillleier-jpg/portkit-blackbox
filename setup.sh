#!/bin/sh
# Richtet das Projekt ein: Repos klonen, Python-Module installieren, Firmware-Hashes pruefen.
set -e
cd "$(dirname "$0")"

mkdir -p repos firmware re out
[ -d repos/blackbox-mod ] || git clone --depth 1 https://github.com/j3threejay/blackbox-mod.git repos/blackbox-mod
[ -d repos/bitbox-micro-fw-patch ] || git clone --depth 1 https://github.com/modularpatcher/bitbox-micro-fw-patch.git repos/bitbox-micro-fw-patch

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install capstone unicorn


check() {
  f="$1"; want="$2"
  if [ ! -f "$f" ]; then echo "FEHLT:  $f"; return; fi
  got=$(shasum -a 256 "$f" 2>/dev/null | cut -d' ' -f1 || sha256sum "$f" | cut -d' ' -f1)
  if [ "$got" = "$want" ]; then echo "OK:     $f"; else echo "FALSCH: $f ($got)"; fi
}
check firmware/MICRO.BIN    54ecc3e5c09b9aed7ad8e2d9d1c9f8ee63e06a8351c857304c3ff21fcb9c4365
check firmware/BLACKBOX.bin 281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d

echo
echo "Compiler (noetig erst zum Bauen der Patches):"
if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
  arm-none-eabi-gcc --version | head -1
else
  echo "  arm-none-eabi-gcc fehlt. macOS: brew install --cask gcc-arm-embedded"
  echo "                           Debian/Ubuntu: sudo apt install gcc-arm-none-eabi"
fi
echo
echo "Fertig. Starte jetzt 'claude' in diesem Ordner."
