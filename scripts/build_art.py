#!/usr/bin/env python3
"""Convert the DDS icons referenced by emitted data to WebP in public/img/.

Reads straight from the mirror's game/gfx tree (CK3REF_DIR) — single-file
reads are safe on the FUSE mount; only batch enumeration is not. Icons are
converted only for entries that exist in generated JSON, and skipped when the
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


def convert(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.open(src).convert("RGBA").save(dst, "WEBP", lossless=False, quality=90)
    return True


def main():
    maa = json.loads((ck3.ROOT / "src/data/maa.json").read_text(encoding="utf-8"))
    missing = []
    done = 0
    for rec in maa:
        src = ICONS / "regimenttypes" / f"{rec['icon']}.dds"
        dst = ck3.ROOT / "public/img/maa" / f"{rec['id']}.webp"
        if convert(src, dst):
            done += 1
        else:
            fallback = ICONS / "regimenttypes" / "_default.dds"
            if convert(fallback, dst):
                done += 1
                missing.append(rec["id"])
            else:
                missing.append(rec["id"] + " (no fallback!)")
    print(f"✓ art: {done}/{len(maa)} MAA icons → public/img/maa/")
    if missing:
        print(f"⚠ {len(missing)} icons fell back or failed: {missing[:8]}"
              " (mirror may still be Dropbox-syncing; re-run make art)")


if __name__ == "__main__":
    main()
