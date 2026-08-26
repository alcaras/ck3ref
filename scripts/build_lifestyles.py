#!/usr/bin/env python3
"""Build src/data/lifestyles.json — lifestyles, focuses, and the 18 perk trees.

Perk `position = { x y }` + `parent` links give the real tree geometry; the
page renders them as SVG. Perk effects combine modifier channels with the
loc text of scripted `effect` blocks (honest fallback for non-modifier perks).
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP_FIELDS = {
    "auto_selection_weight": "AI pick weight",
}
HANDLED = {
    "lifestyle", "tree", "position", "icon", "parent", "character_modifier",
    "government_character_modifier", "doctrine_character_modifier",
    "culture_character_modifier", "effect", "can_be_picked", "trait", "name",
}


def dynamic_name(blk, key):
    """Perk display name: <key>_name loc, else first loc ref in the dynamic
    `name` block (used by perks whose name varies by faith/culture)."""
    v = ck3.loc(f"{key}_name")
    if v:
        return ck3.render_text(v)
    refs = []
    nb = blk.get("name")
    if isinstance(nb, str):
        refs.append(nb)
    elif isinstance(nb, (Block, Tagged)):
        _collect_loc_refs(nb, refs)
    for r in reversed(refs):  # last entry is the untriggered fallback
        t = ck3.loc(r)
        if t:
            return ck3.render_text(t)
    return key


def _collect_loc_refs(block, out):
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block):
        return
    for k, _op, v in block:
        if k in ("desc", "text", "name") and isinstance(v, str):
            out.append(v)
        elif isinstance(v, (Block, Tagged)):
            _collect_loc_refs(v, out)


def mod_lines(block):
    lines = []
    if not isinstance(block, Block):
        return lines
    label = None
    for k, _op, v in block:
        if k in ("flag", "government_flag") and isinstance(v, str):
            label = v.replace("government_is_", "").replace("_government", "").replace("_", " ")
        elif k == "parameter" and isinstance(v, str):
            t = ck3.render_text(ck3.loc(f"culture_parameter_{v}")
                                or ck3.loc(f"character_parameter_{v}") or "")
            lines.append(t or v.replace("_", " ").capitalize())
        elif k is not None and not isinstance(v, (Block, Tagged)):
            lines.append(ck3.render_modifier(k, v))
    if label:
        lines = [f"{ln} ({label})" for ln in lines]
    return lines


def effect_text(block, out):
    """Pull loc text refs out of scripted effect blocks."""
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block):
        return
    for k, _op, v in block:
        if k in ("text", "desc") and isinstance(v, str):
            t = ck3.render_text(ck3.loc(v) or "")
            if t:
                out.append(t)
        elif isinstance(v, (Block, Tagged)):
            effect_text(v, out)


def main():
    unhandled = Counter()
    perks = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "lifestyle_perks"):
        if not isinstance(blk, Block):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        pos = blk.get("position")
        xy = [v for v in pos.values()] if isinstance(pos, Block) else [0, 0]

        effects = []
        for ch in ("character_modifier", "doctrine_character_modifier",
                   "culture_character_modifier"):
            for m in blk.get_all(ch):
                effects.extend(mod_lines(m))
        gov = []
        for m in blk.get_all("government_character_modifier"):
            gov.extend(mod_lines(m))
        texts = []
        for e in blk.get_all("effect"):
            effect_text(e, texts)
        trait = blk.get("trait")
        for k in blk.keys():
            if k not in HANDLED and k not in SKIP_FIELDS:
                unhandled[k] += 1

        perks.append({
            "id": key,
            "name": dynamic_name(blk, key),
            "lifestyle": blk.get("lifestyle"),
            "tree": blk.get("tree"),
            "x": xy[0] if len(xy) > 0 else 0,
            "y": xy[1] if len(xy) > 1 else 0,
            "parents": [p for p in blk.get_all("parent") if isinstance(p, str)],
            "effects": effects + gov + texts,
            "trait": ({"id": trait, "name": ck3.render_text(ck3.loc(f"trait_{trait}") or trait)}
                      if isinstance(trait, str) else None),
            "icon": str(blk.get("icon") or key).removesuffix(".dds"),
            "dlc": dlc,
            "features": features,
        })

    lifestyles = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "lifestyles"):
        dlc, features = ck3.dlc_tag(path, blk)
        lifestyles.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(f"{key}_name") or ck3.loc(key) or key),
            "dlc": dlc,
        })

    focuses = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "focuses"):
        if not isinstance(blk, Block):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        lines = []
        for m in blk.get_all("modifier"):
            lines.extend(mod_lines(m))
        focuses.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(f"{key}_name") or key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "lifestyle": blk.get("lifestyle"),
            "education": bool(blk.get("is_education", key.startswith("education_"))),
            "effects": lines,
            "dlc": dlc,
        })

    trees = {}
    for p in perks:
        t = trees.setdefault(p["tree"], {
            "id": p["tree"], "lifestyle": p["lifestyle"],
            "name": ck3.render_text(
                ck3.loc(f"{p['tree']}_name") or ck3.loc(f"{p['tree']}_tree_name")
                or ck3.loc(p["tree"]) or p["tree"].replace("_", " ").title()),
            "perks": [],
        })
        t["perks"].append(p)
    for t in trees.values():
        t["perks"].sort(key=lambda p: (p["y"], p["x"]))

    ck3.write_json("lifestyles.json", {
        "lifestyles": lifestyles,
        "focuses": sorted(focuses, key=lambda f: (f["education"], f["lifestyle"] or "", f["id"])),
        "trees": sorted(trees.values(), key=lambda t: (t["lifestyle"], t["id"])),
    })
    if unhandled:
        print("⚠ unhandled perk fields:")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")


if __name__ == "__main__":
    main()
