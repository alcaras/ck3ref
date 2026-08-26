#!/usr/bin/env python3
"""Build src/data/cultures.json from common/culture/cultures/.

Schema documented by the game in _cultures.info. Pillar references (heritage,
language, ethos, martial custom) and tradition references are cross-checked
against pillars.json / traditions.json so the page can link into /pillars and
/traditions anchors. Every field present in the data is either emitted,
consciously skipped (SKIP_FIELDS), or reported as unhandled.
"""

import colorsys
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "ethnicities": "portrait DNA pool weights, not player-facing",
    "coa_gfx": "coat-of-arms art-style selection keys",
    "building_gfx": "building model art-style selection keys",
    "clothing_gfx": "portrait attire art-style selection keys",
    "unit_gfx": "map unit-model art-style selection keys",
    "house_coa_frame": "CoA frame art plumbing",
    "house_coa_mask_offset": "CoA frame art plumbing",
    "house_coa_mask_scale": "CoA frame art plumbing",
    "name_list": "character/place naming pool; loc just repeats the culture adjective",
    "name_order_convention": "name/dynasty display-order aesthetic, cosmetic",
    "history_loc_override": "custom history flavor key; start-map history is future work",
}

HANDLED_FIELDS = {
    "color", "created", "parents", "traditions", "dlc_tradition",
    "ethos", "heritage", "language", "martial_custom", "head_determination",
}


# --- color resolution -------------------------------------------------------

_named_colors: dict | None = None


def named_colors():
    global _named_colors
    if _named_colors is None:
        _named_colors = {}
        for p in sorted((ck3.COMMON / "named_colors").glob("*.txt")):
            blk = ck3.parse_file(p)
            top = blk.get("colors") or blk
            for k, _op, v in top:
                if k is not None:
                    _named_colors[k] = v
    return _named_colors


def to_hex(color):
    """color value (Block rgb triple, Tagged hsv/rgb, or named-color key) -> #rrggbb."""
    if isinstance(color, str):
        return to_hex(named_colors().get(color))
    if isinstance(color, Tagged):
        vals = [v for v in color.block.values() if isinstance(v, (int, float))]
        if color.tag == "hsv" and len(vals) == 3:
            rgb = colorsys.hsv_to_rgb(*vals)
            return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)
        color = color.block
    if isinstance(color, Block):
        vals = [v for v in color.values() if isinstance(v, (int, float))]
        if len(vals) == 3:
            # ints above 1 mean a 0-255 triple; otherwise 0-1 floats
            if any(v > 1 for v in vals):
                return "#" + "".join(f"{round(v):02x}" for v in vals)
            return "#" + "".join(f"{round(v * 255):02x}" for v in vals)
    return None


def main():
    pillars = {p["id"]: p for p in json.loads(
        (ck3.ROOT / "src/data/pillars.json").read_text(encoding="utf-8"))}
    traditions = {t["id"]: t for t in json.loads(
        (ck3.ROOT / "src/data/traditions.json").read_text(encoding="utf-8"))["traditions"]}

    entries = ck3.parse_dir(ck3.COMMON / "culture" / "cultures")
    unhandled = Counter()
    missing_refs = []
    out = []

    def pillar_ref(key):
        if key is None:
            return None
        p = pillars.get(key)
        if p is None:
            missing_refs.append(("pillar", key))
            return {"key": key, "name": key.replace("_", " ").title()}
        return {"key": key, "name": p["name"]}

    def tradition_ref(key, **extra):
        t = traditions.get(key)
        if t is None:
            missing_refs.append(("tradition", key))
            return {"key": key, "name": key.replace("_", " ").title(), **extra}
        return {"key": key, "name": t["name"], **extra}

    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)

        trads = []
        tb = blk.get("traditions")
        if isinstance(tb, Block):
            for t in tb.values():
                if isinstance(t, str):
                    trads.append(tradition_ref(t))
        # DLC-conditional traditions: `trait` with the flag's DLC, plus the
        # optional `fallback` the culture uses without it.
        for dt in blk.get_all("dlc_tradition"):
            if not isinstance(dt, Block):
                continue
            flag = dt.get("requires_dlc_flag")
            flag_dlc = ck3.FEATURE_TO_DLC.get(flag, flag)
            trait = dt.get("trait")
            if isinstance(trait, str):
                trads.append(tradition_ref(trait, dlc=flag_dlc))
            fb = dt.get("fallback")
            if isinstance(fb, str):
                trads.append(tradition_ref(fb, withoutDlc=flag_dlc))

        parents = []
        pb = blk.get("parents")
        if isinstance(pb, Block):
            parents = [p for p in pb.values() if isinstance(p, str)]

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name = ck3.loc(key)
        hd_key = blk.get("head_determination")
        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "heritage": pillar_ref(blk.get("heritage")),
            "language": pillar_ref(blk.get("language")),
            "ethos": pillar_ref(blk.get("ethos")),
            "martialCustom": pillar_ref(blk.get("martial_custom")),
            "headDetermination": (
                {"key": hd_key, "name": ck3.render_text(ck3.loc(hd_key) or hd_key)}
                if isinstance(hd_key, str) else None),
            "traditions": trads,
            "parents": parents,
            "created": blk.get("created"),
            "color": to_hex(blk.get("color")),
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: ((r["heritage"] or {}).get("name", ""), r["name"] or r["id"]))
    ck3.write_json("cultures.json", out)

    if unhandled:
        print("⚠ unhandled culture fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    if missing_refs:
        print(f"⚠ {len(missing_refs)} unresolved pillar/tradition refs: {missing_refs[:10]}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} cultures without localized names: {missing_names[:10]}")
    missing_colors = [r["id"] for r in out if not r["color"]]
    if missing_colors:
        print(f"⚠ {len(missing_colors)} cultures without resolvable color: {missing_colors[:10]}")
    ids = {r["id"] for r in out}
    orphans = [(r["id"], p) for r in out for p in r["parents"] if p not in ids]
    if orphans:
        print(f"⚠ {len(orphans)} parent refs to unknown cultures: {orphans[:10]}")


if __name__ == "__main__":
    main()
