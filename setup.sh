#!/bin/sh
# Sets up the project: reference repos, Python venv, firmware hash check, compiler check.
set -e
cd "$(dirname "$0")"

mkdir -p repos firmware re out
# blackbox-mod (JOEBOX): the builds export a pinned commit from this clone, so it needs full history
[ -d repos/blackbox-mod ] || git clone https://github.com/j3threejay/blackbox-mod.git repos/blackbox-mod
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install capstone unicorn numpy scipy

check() {
  f="$1"; want="$2"
  if [ ! -f "$f" ]; then echo "MISSING: $f"; return; fi
  got=$(shasum -a 256 "$f" 2>/dev/null | cut -d' ' -f1 || sha256sum "$f" | cut -d' ' -f1)
  if [ "$got" = "$want" ]; then echo "OK:      $f"; else echo "WRONG:   $f ($got)"; fi
}
check firmware/BLACKBOX.bin 281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d

echo
echo "Compiler:"
if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
  arm-none-eabi-gcc --version | head -1
else
  echo "  arm-none-eabi-gcc missing. macOS: brew install --cask gcc-arm-embedded"
  echo "                             Debian/Ubuntu: sudo apt install gcc-arm-none-eabi"
fi
