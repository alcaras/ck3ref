#!/usr/bin/env python3
"""Convert the DDS icons referenced by emitted data to WebP in public/img/.

Data-driven: CATEGORIES maps each dataset to its gfx icon folder. Reads
straight from the mirror's game/gfx tree (CK3REF_DIR) — single-file reads are
safe on the FUSE mount; only batch enumeration is not. Skips conversions whose
output is already newer than the source.
"""

import json
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

MIRROR = Path(os.environ.get("CK3REF_DIR", Path.home() / "Library/CloudStorage/Dropbox/cc/ck3ref"))
ICONS = MIRROR / "game/gfx/interface/icons"

# (json file, gfx subfolder, output subdir, icon field, id field)
CATEGORIES = [
    ("maa.json", "regimenttypes", "maa", "icon", "id"),
    ("traits.json", "traits", "traits", "icon", "id"),
]


def convert(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.open(src).convert("RGBA").save(dst, "WEBP", lossless=False, quality=90)
    return True


def main():
    for json_file, gfx_sub, out_sub, icon_field, id_field in CATEGORIES:
        path = ck3.ROOT / "src/data" / json_file
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(records, dict):
            records = list(records.values())
        missing = []
        done = 0
        for rec in records:
            icon = rec.get(icon_field) or rec.get(id_field)
            dst = ck3.ROOT / "public/img" / out_sub / f"{rec[id_field]}.webp"
            if convert(ICONS / gfx_sub / f"{icon}.dds", dst):
                done += 1
            elif convert(ICONS / gfx_sub / "_default.dds", dst):
                done += 1
                missing.append(rec[id_field])
            else:
                missing.append(rec[id_field] + " (no fallback!)")
        print(f"✓ art: {done}/{len(records)} {out_sub} icons → public/img/{out_sub}/")
        if missing:
            print(f"⚠ {len(missing)} fell back or failed: {missing[:8]}"
                  " (mirror may still be Dropbox-syncing; re-run make art)")


if __name__ == "__main__":
    main()
