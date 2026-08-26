#!/usr/bin/env python3
"""Build src/data/dlc.json — what each DLC adds, aggregated from every
generated dataset's `dlc` field, plus display metadata from dlc_metadata.
Also converts the store thumbnails from the mirror's game/dlc/ folders.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

MIRROR = Path(os.environ.get("CK3REF_DIR", Path.home() / "Library/CloudStorage/Dropbox/cc/ck3ref"))
DATA = ck3.ROOT / "src" / "data"

# dataset -> (records path, type label, page)
SOURCES = [
    ("maa.json", None, "Men-at-Arms", "men-at-arms"),
    ("traits.json", None, "Traits", "traits"),
    ("legacies.json", None, "Dynasty Legacies", "legacies"),
    ("buildings.json", None, "Buildings", "buildings"),
    ("doctrines.json", "doctrines", "Doctrines & Tenets", "doctrines"),
    ("traditions.json", "traditions", "Traditions", "traditions"),
    ("innovations.json", None, "Innovations", "innovations"),
    ("pillars.json", None, "Culture Pillars", "pillars"),
    ("cbs.json", "cbs", "Casus Belli", "casus-belli"),
    ("court_positions.json", "positions", "Court Positions", "court-positions"),
    ("concepts.json", None, "Concepts", "concepts"),
    ("holy_sites.json", None, "Holy Sites", "holy-sites"),
    ("schemes.json", "schemes", "Schemes", "schemes"),
    ("decisions.json", None, "Decisions", "decisions"),
    ("activities.json", "activities", "Activities", "activities"),
    ("legends_data.json", "types", "Legends", "legends"),
    ("struggles.json", "struggles", "Struggles", "struggles"),
    ("epidemics.json", None, "Epidemics", "epidemics"),
    ("nicknames.json", None, "Nicknames", "nicknames"),
]


def records_of(name, path):
    p = DATA / name
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    if path:
        d = d.get(path, [])
    return d if isinstance(d, list) else []


def main():
    meta = {}
    md = ck3.REF / "game" / "dlc_metadata" / "00_dlc_metadata.txt"
    if md.exists():
        blk = ck3.parse_file(md)
        for key, _op, v in blk:
            if key and hasattr(v, "get"):
                name = ck3.render_text(ck3.loc(v.get("key") or "") or v.get("key") or key)
                meta[name] = {"type": v.get("type"), "order": len(meta)}

    dlcs = {}
    for fname, rpath, label, page in SOURCES:
        for rec in records_of(fname, rpath):
            d = rec.get("dlc")
            if not d:
                continue
            entry = dlcs.setdefault(d, {"name": d, "content": {}})
            bucket = entry["content"].setdefault(label, {"page": page, "items": []})
            nm = rec.get("name")
            if nm and nm not in bucket["items"]:
                bucket["items"].append(nm)

    out = []
    for name, entry in dlcs.items():
        m = meta.get(name, {})
        total = sum(len(b["items"]) for b in entry["content"].values())
        out.append({
            "name": name, "type": m.get("type"), "order": m.get("order", 999),
            "total": total,
            "content": {k: v for k, v in sorted(entry["content"].items())},
        })
    out.sort(key=lambda d: (d["order"], d["name"]))
    ck3.write_json("dlc.json", out)

    # thumbnails
    try:
        from PIL import Image
        outdir = ck3.ROOT / "public/img/dlc"
        n = 0
        for dlcdir in sorted((MIRROR / "game/dlc").iterdir()):
            thumb = dlcdir / "thumbnail.png"
            dlcfile = next(dlcdir.glob("*.dlc"), None)
            if not (thumb.exists() and dlcfile):
                continue
            b = ck3.parse_file(dlcfile)
            disp = b.get("name")
            if not isinstance(disp, str):
                continue
            slug = disp.lower().replace(" ", "-").replace("&", "and")
            dst = outdir / f"{slug}.webp"
            if not dst.exists():
                outdir.mkdir(parents=True, exist_ok=True)
                Image.open(thumb).convert("RGB").save(dst, "WEBP", quality=85)
            n += 1
        print(f"  ({n} DLC thumbnails)")
    except Exception as e:  # thumbnails are a nicety, never fail the build
        print(f"  (thumbnails skipped: {e})")


if __name__ == "__main__":
    main()
