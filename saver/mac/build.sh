#!/bin/bash
# Builds Pin.saver (universal arm64 + x86_64, ad-hoc signed) with just the
# Command Line Tools; no Xcode needed. The app bundles it and installs it.
#   saver/mac/build.sh [version]     -> saver/mac/build/Pin.saver
set -euo pipefail
cd "$(dirname "$0")"

NAME=Pin
VERSION=${1:-$(cat ../../VERSION)}
BUILD=build
SDK=$(xcrun --show-sdk-path)
TOOLCHAIN_SWIFT_LIBS="$(dirname "$(dirname "$(xcrun -f swiftc)")")/lib/swift/macosx"

rm -rf "$BUILD"
mkdir -p "$BUILD"

BINS=()
for arch in arm64 x86_64; do
  swiftc -O -wmo -parse-as-library \
    -target "${arch}-apple-macos12.0" -sdk "$SDK" \
    -emit-object -o "$BUILD/$NAME-$arch.o" Sources/*.swift
  # The swiftCompatibility static libs for a macOS 12 target live in the toolchain.
  if clang -bundle -target "${arch}-apple-macos12.0" -isysroot "$SDK" \
    -o "$BUILD/$NAME-$arch" "$BUILD/$NAME-$arch.o" \
    -framework ScreenSaver -framework AppKit -framework Foundation \
    -L "$SDK/usr/lib/swift" -L /usr/lib/swift -L "$TOOLCHAIN_SWIFT_LIBS"; then
    BINS+=("$BUILD/$NAME-$arch")
  elif [ "$arch" = x86_64 ]; then
    # Some toolchains ship arm64-only compatibility libs; Pin itself is arm64 anyway.
    echo "warning: no x86_64 slice on this machine, building arm64 only"
  else
    exit 1
  fi
done
lipo -create "${BINS[@]}" -output "$BUILD/$NAME"

# Assemble and sign in a local temp folder: AppleDouble ._ files from an exFAT
# drive break codesign.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
SAVER="$STAGE/$NAME.saver"
mkdir -p "$SAVER/Contents/MacOS"
sed "s/__VERSION__/$VERSION/g" Info.plist > "$SAVER/Contents/Info.plist"
cp "$BUILD/$NAME" "$SAVER/Contents/MacOS/$NAME"
codesign --force --sign - "$SAVER"
ditto --norsrc --noextattr "$SAVER" "$BUILD/$NAME.saver"
echo "Built saver/mac/$BUILD/$NAME.saver ($VERSION)"
