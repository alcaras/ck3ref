#!/usr/bin/env bash
# Sync CK3 data from the local game install into repo-local reference/.
#
# The install is found by ck3.game_dir() (the default Steam location on
# macOS / Windows / Linux); set CK3REF_DIR to override. Builds never read the
# install directly in batch — they read reference/, which is a verified copy:
# rsync until a pass copies nothing, then compare file counts on both sides.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CK3REF_DIR="$(cd "$ROOT/scripts/lib" && python3 -c 'import ck3; print(ck3.game_dir())')"
DEST="$ROOT/reference"

# All data subtrees the site reads.
SUBTREES=(
  game/common
  game/localization/english
  game/dlc_metadata
  game/history
  game/events
  game/map_data
  jomini/common
)

if [ ! -d "$CK3REF_DIR/game/common" ]; then
  echo "✗ not a CK3 install (no game/common): $CK3REF_DIR" >&2
  exit 1
fi
echo "  source: $CK3REF_DIR"

mkdir -p "$DEST"

for sub in "${SUBTREES[@]}"; do
  mkdir -p "$DEST/$sub"
  # Repeat until a pass transfers zero files.
  for attempt in 1 2 3 4 5; do
    out=$(rsync -a --delete --out-format='%n' "$CK3REF_DIR/$sub/" "$DEST/$sub/")
    copied=$(printf '%s' "$out" | grep -cv '/$' || true)
    if [ "$copied" -eq 0 ]; then break; fi
    echo "  $sub: pass $attempt copied $copied files"
  done
  src_n=$(find "$CK3REF_DIR/$sub" -type f | wc -l | tr -d ' ')
  dst_n=$(find "$DEST/$sub" -type f | wc -l | tr -d ' ')
  if [ "$src_n" != "$dst_n" ]; then
    echo "✗ manifest mismatch for $sub: source $src_n files, dest $dst_n" >&2
    exit 1
  fi
  echo "✓ $sub — $dst_n files"
done

# The launcher's version string, so detect_version.py needs no env var.
if [ -f "$CK3REF_DIR/launcher/launcher-settings.json" ]; then
  cp "$CK3REF_DIR/launcher/launcher-settings.json" "$DEST/launcher-settings.json"
fi

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$DEST/.synced-at"
echo "✓ sync complete → $DEST"
