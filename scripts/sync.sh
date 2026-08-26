#!/usr/bin/env bash
# Sync CK3 data from the mirror (Dropbox) into repo-local reference/.
#
# The mirror lives on a Dropbox FUSE mount that has been observed to drop files
# SILENTLY during batch reads (anywhere from 1-in-10k to 86% of a directory,
# always with clean exit codes). Defense: rsync repeatedly until a pass copies
# nothing, then compare file counts on both sides. Never build against the
# mount directly.
#
# Set CK3REF_DIR to the mirror location; defaults to the Dropbox path layout.
set -euo pipefail

CK3REF_DIR="${CK3REF_DIR:-$HOME/Library/CloudStorage/Dropbox/cc/ck3ref}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/reference"

# All data subtrees the site reads.
SUBTREES=(
  game/common
  game/localization/english
  game/dlc_metadata
  game/history
  game/events
  jomini/common
)

if [ ! -d "$CK3REF_DIR/game/common" ]; then
  echo "✗ CK3REF_DIR does not look like the ck3ref mirror: $CK3REF_DIR" >&2
  exit 1
fi

mkdir -p "$DEST"

for sub in "${SUBTREES[@]}"; do
  mkdir -p "$DEST/$sub"
  # Repeat until a pass transfers zero files (FUSE dropout defense).
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

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$DEST/.synced-at"
echo "✓ sync complete → $DEST"
