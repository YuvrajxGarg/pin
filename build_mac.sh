#!/bin/bash
# Builds "dist/Pin.app" with the screensaver inside. Run on a Mac.
#   ./build_mac.sh             build
#   ./build_mac.sh --install   build and copy to ~/Applications
#   ./build_mac.sh --release   build and make the update zip + .sha256 and the DMG
set -e
cd "$(dirname "$0")"

PY=""
if command -v uv >/dev/null 2>&1; then
  uv python install 3.12 >/dev/null
  PY="$(uv python find 3.12)"
else
  for cand in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$cand" ] && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  done
fi
[ -n "$PY" ] || { echo "Need Python 3.9+ (brew install uv, or python.org)"; exit 1; }
echo "Building Pin $(cat VERSION) with $PY"

saver/mac/build.sh "$(cat VERSION)"

rm -rf .venv-build build dist
"$PY" -m venv .venv-build
source .venv-build/bin/activate
pip install --quiet --upgrade pip
pip install --quiet pyinstaller certifi -r requirements.txt
pyinstaller --noconfirm --log-level WARN Pin.spec
rm -rf "dist/Pin"   # the .app is the deliverable on macOS

if [ "$1" = "--release" ]; then
  (cd dist && ditto -c -k --keepParent Pin.app Pin-mac.zip && shasum -a 256 Pin-mac.zip > Pin-mac.zip.sha256)
  installer/build_mac.sh Pin
  echo "Release files: dist/Pin-mac.zip (+ .sha256), dist/Pin.dmg"
fi
if [ "$1" = "--install" ]; then
  mkdir -p ~/Applications
  rm -rf ~/Applications/Pin.app
  ditto dist/Pin.app ~/Applications/Pin.app
  echo "Installed to ~/Applications/Pin.app"
fi
echo
echo "Done: dist/Pin.app"
