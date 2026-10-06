#!/bin/bash
# scan_similar.sh - find similar photos (resized copies, bursts) with Czkawka.
# Downloads the Czkawka command-line tool into tools/ the first time (no Homebrew needed).
#
# Usage:
#   ./scan_similar.sh "/path/to/Photos"            # strictness High (default)
#   ./scan_similar.sh "/path/to/Photos" VeryHigh   # stricter: mostly resized copies only
#
# The report goes to ~/Desktop/similar_photos.txt. Then run review_similar.py on it.

set -euo pipefail

PHOTOS="${1:-}"
STRICTNESS="${2:-High}"   # VeryHigh, High, Medium, Small, VerySmall
REPORT="$HOME/Desktop/similar_photos.txt"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOL="$HERE/tools/czkawka_cli"
VERSION="9.0.0"   # last Czkawka release that has an Intel Mac build

if [ -z "$PHOTOS" ] || [ ! -d "$PHOTOS" ]; then
  echo "Usage: ./scan_similar.sh \"/path/to/Photos\" [VeryHigh|High|Medium]"
  echo "Folder not found: ${PHOTOS:-<none given>}"
  exit 1
fi

if [ ! -x "$TOOL" ]; then
  case "$(uname -m)" in
    arm64) ASSET="mac_czkawka_cli_arm" ;;   # Apple Silicon
    *)     ASSET="mac_czkawka_cli" ;;       # Intel
  esac
  echo "Downloading Czkawka $VERSION ($ASSET)..."
  mkdir -p "$HERE/tools"
  curl -fL -o "$TOOL" "https://github.com/qarmin/czkawka/releases/download/$VERSION/$ASSET"
  chmod +x "$TOOL"
fi

# Folders inside the photo folder that are never scanned
EXCLUDE=()
for name in "_duplicates"; do
  if [ -d "$PHOTOS/$name" ]; then EXCLUDE+=(-e "$PHOTOS/$name"); fi
done

"$TOOL" image -d "$PHOTOS" "${EXCLUDE[@]+"${EXCLUDE[@]}"}" -s "$STRICTNESS" -f "$REPORT"

echo
echo "Report: $REPORT"
echo "Next:   python3 review_similar.py \"$REPORT\" \"$PHOTOS\""
