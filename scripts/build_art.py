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
ILLUS = MIRROR / "game/gfx/interface/illustrations"

# Wide panoramic art (not icons): downscaled to a web-sane width.
# (source subfolder, output subdir, max width px)
ILLUSTRATIONS = [
    ("legacy_tracks", "legacy-banners", 1200),
]

# (json file, records path, gfx subfolder, output subdir, icon field, id field,
#  quiet) — quiet=True: absence is expected (game has no art for some entries),
#  skip silently with no _default fallback.
CATEGORIES = [
    ("maa.json", None, "regimenttypes", "maa", "icon", "id", False),
    ("traits.json", None, "traits", "traits", "icon", "id", False),
    ("legacies.json", None, "dynasty", "legacies", "icon", "id", False),
    ("buildings.json", None, "building_types", "buildings", "icon", "icon", False),
    ("faiths.json", "faiths", "faith", "faith", "icon", "id", False),
    ("doctrines.json", "doctrines", "faith_doctrines", "faith_doctrines", "icon", "id", True),
    ("innovations.json", None, "culture_innovations", "innovations", "icon", "id", False),
    ("pillars.json", None, "culture_pillars", "pillars", "icon", "id", True),
    ("traditions.json", "traditions", "culture_tradition/4-items", "traditions", "icon", "id", True),
    ("cbs.json", "cbs", "casus_bellis", "cb", "icon", "id", True),
    ("court_positions.json", "positions", "court_position_types", "court", "icon", "id", False),
    ("council.json", "tasks", "council_task_types", "council-tasks", "icon", "id", True),
    ("governments.json", None, "government_types", "governments", "icon", "id", False),
    ("holdings.json", None, "holding_types_tab", "holdings", "icon", "id", False),
    ("great_projects.json", None, "", "great-projects", "icon", "id", True),
    ("activities.json", "activities", "activities", "activities", "icon", "id", False),
    ("activities.json", "intents", "activity_intents", "intents", "icon", "id", True),
    ("activities.json", "travelOptions", "travel_options", "travel-options", "icon", "id", True),
    ("activities.json", "pois", "point_of_interest_types", "poi", "icon", "id", True),
    ("schemes.json", "schemes", "scheme_types", "schemes", "icon", "id", False),
    ("schemes.json", "countermeasures", "scheme_countermeasure_types", "countermeasures", "icon", "id", False),
    ("situations.json", None, "situation_types", "situations", "icon", "id", False),
    ("epidemics.json", None, "epidemics", "epidemics", "icon", "id", False),
    ("legends.json", "types", "legend_types", "legends-types", "icon", "id", False),
    ("artifacts.json", "named", "artifact", "artifacts", "icon", "icon", False),
    ("interactions.json", None, "character_interactions", "interactions", "icon", "id", True),
    ("domiciles.json", "buildings", "", "domiciles", "icon", "id", True),
]


def convert(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.open(src).convert("RGBA").save(dst, "WEBP", lossless=False, quality=90)
    return True


def convert_wide(src: Path, dst: Path, maxw: int) -> bool:
    if not src.exists():
        return False
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    if im.width > maxw:
        im = im.resize((maxw, max(1, round(im.height * maxw / im.width))))
    im.save(dst, "WEBP", quality=82)
    return True


def main():
    for sub, out_sub, maxw in ILLUSTRATIONS:
        src_dir = ILLUS / sub
        if not src_dir.exists():
            continue
        n = 0
        for f in sorted(src_dir.glob("*.dds")):
            if convert_wide(f, ck3.ROOT / "public/img" / out_sub / f"{f.stem}.webp", maxw):
                n += 1
        print(f"✓ art: {n} {out_sub} illustrations → public/img/{out_sub}/")

    for json_file, rec_path, gfx_sub, out_sub, icon_field, id_field, quiet in CATEGORIES:
        path = ck3.ROOT / "src/data" / json_file
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        if rec_path:
            records = records[rec_path]
        seen = set()
        missing = []
        done = 0
        for rec in records:
            icon = rec.get(icon_field) or rec.get(id_field)
            out_id = rec[id_field]
            if out_id in seen:
                continue
            seen.add(out_id)
            dst = ck3.ROOT / "public/img" / out_sub / f"{out_id}.webp"
            if convert(ICONS / gfx_sub / f"{icon}.dds", dst):
                done += 1
            elif quiet:
                continue
            elif convert(ICONS / gfx_sub / "_default.dds", dst):
                done += 1
                missing.append(out_id)
            else:
                missing.append(out_id + " (no fallback!)")
        print(f"✓ art: {done}/{len(seen)} {out_sub} icons → public/img/{out_sub}/")
        if missing and not quiet:
            print(f"⚠ {len(missing)} fell back or failed: {missing[:8]}"
                  " (mirror may still be Dropbox-syncing; re-run make art)")


if __name__ == "__main__":
    main()
