#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "Usage: $0 <version> [arch]" >&2
  exit 2
fi

VERSION="$1"
ARCH="${2:-$(uname -m)}"
PRODUCT="PythonDancer"
BASENAME="${PRODUCT}-${VERSION}-macOS-${ARCH}"

rm -rf build dist "${BASENAME}.zip" "${BASENAME}.dmg" "${BASENAME}.sha256"

python -m PyInstaller --clean --noconfirm macos.spec

APP="dist/${PRODUCT}.app"
BIN="${APP}/Contents/MacOS/${PRODUCT}"

if [[ ! -d "${APP}" || ! -x "${BIN}" ]]; then
  echo "macOS app bundle was not created correctly" >&2
  exit 1
fi

# PyInstaller performs ad-hoc signing for Mach-O binaries as needed; apply a
# final deep ad-hoc signature to the complete app bundle for unsigned releases.
codesign --force --deep --sign - "${APP}"
codesign --verify --deep --strict --verbose=2 "${APP}"

ACTUAL_ARCH="$(uname -m)"
if [[ "${ACTUAL_ARCH}" != "${ARCH}" ]]; then
  echo "Expected runner architecture ${ARCH}, got ${ACTUAL_ARCH}" >&2
  exit 1
fi

file "${BIN}"

# Confirm FFmpeg actually made it into the frozen bundle.
FFMPEG_PATH="$(find "${APP}" -type f -name ffmpeg -print -quit)"
if [[ -z "${FFMPEG_PATH}" ]]; then
  echo "Bundled ffmpeg was not found in ${APP}" >&2
  exit 1
fi
"${FFMPEG_PATH}" -version | head -n 1

# Argparse --help exits before Tk is opened; this is a useful frozen-binary
# smoke test on headless CI runners.
"${BIN}" --help >/tmp/python-dancer-help.txt 2>&1

grep -q "six-axis choreography" /tmp/python-dancer-help.txt

# ditto preserves the application bundle metadata/resource forks.
ditto -c -k --sequesterRsrc --keepParent "${APP}" "${BASENAME}.zip"

hdiutil create \
  -volname "${PRODUCT} ${VERSION}" \
  -srcfolder "${APP}" \
  -ov \
  -format UDZO \
  "${BASENAME}.dmg"

shasum -a 256 "${BASENAME}.zip" "${BASENAME}.dmg" > "${BASENAME}.sha256"

printf 'Created:\n  %s\n  %s\n  %s\n' \
  "${BASENAME}.zip" "${BASENAME}.dmg" "${BASENAME}.sha256"
