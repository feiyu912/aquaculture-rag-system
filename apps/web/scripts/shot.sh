#!/usr/bin/env bash
# Capture a screenshot of a running Next.js route at an exact viewport size.
#
#   scripts/shot.sh <path> <out.png> [width] [height] [extra-chrome-flag]
#
# Used during UI review so the layout can be checked at real desktop and
# mobile widths instead of whatever the interactive browser window happens to
# be.
set -euo pipefail

ROUTE="${1:-/chat}"
OUT="${2:-/tmp/aqua-shot.png}"
WIDTH="${3:-1440}"
HEIGHT="${4:-900}"
EXTRA="${5:-}"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$(mktemp -d)"

"$CHROME" \
  --headless=new \
  --disable-gpu \
  --no-sandbox \
  --hide-scrollbars \
  --force-device-scale-factor=2 \
  --user-data-dir="$PROFILE" \
  --window-size="${WIDTH},${HEIGHT}" \
  --virtual-time-budget=6000 \
  --screenshot="$OUT" \
  $EXTRA \
  "http://127.0.0.1:3000${ROUTE}" >/dev/null 2>&1 || true

rm -rf "$PROFILE"
echo "$OUT"
