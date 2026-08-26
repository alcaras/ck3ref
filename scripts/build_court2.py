#!/usr/bin/env python3
"""Build royalcourt.json (court types, amenities, inspirations) and
gamerules.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged


def name_of(key, *extra):
    for cand in (key, f"{key}_name", *extra):
        v = ck3.loc(cand)
        if v:
            t = ck3.render_text(v)
            if t and "…" not in t:
                return t
    return key.replace("_", " ").title()


def mods(block):
    out = []
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block):
        return out
    for k, _op, v in block:
        if k and not isinstance(v, (Block, Tagged)):
            out.append(ck3.render_modifier(k, v))
    return out


def deep_mods(blk, depth=0):
    """Modifier lines from any nested *_modifier block."""
    out = []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block) or depth > 3:
        return out
    for k, _op, v in blk:
        if isinstance(k, str) and k.endswith("modifier") and isinstance(v, Block):
            out.extend(mods(v))
        elif isinstance(v, (Block, Tagged)):
            out.extend(deep_mods(v, depth + 1))
    return out


def build_court():
    types = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "court_types"):
        if not isinstance(blk, Block):
            continue
        perks = []
        for lp in blk.get_all("level_perk"):
            if isinstance(lp, Block):
                lvl = lp.get("level")
                lines = deep_mods(lp)
                if lines or lvl:
                    perks.append({"level": lvl, "lines": lines[:6]})
        cost, _r = ck3.resolve_value(blk.get("cost"))
        types.append({
            "id": key,
            "name": name_of(key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "cost": cost,
            "default": bool(blk.get("default", False)),
            "perks": sorted(perks, key=lambda p: p["level"] or 0),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })

    def amenity_cost(lv):
        """cost = { gold = {...} treasury = {...} } — the same amount, routed
        differently depending on whether a treasury exists."""
        cb = lv.get("cost")
        if not isinstance(cb, Block):
            return None
        for field in ("gold", "treasury"):
            v = cb.get(field)
            n, rules = ck3.resolve_value(v)
            if n:
                return round(n, 1)
            if rules:
                # amenity upkeep scales with realm size and court grandeur —
                # there is no single number to print.
                return "scales"
        return None

    amenities = []
    # each FILE top-level entry is one amenity setting; its Block children are
    # its levels (plus a `default` pointer).
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "court_amenities"):
        if not isinstance(blk, Block):
            continue
        default = blk.get("default")
        levels = []
        for lk, _o2, lv in blk:
            if not isinstance(lv, Block) or not isinstance(lk, str):
                continue
            levels.append({"id": lk, "name": name_of(lk),
                           "cost": amenity_cost(lv),
                           "isDefault": lk == default,
                           "lines": deep_mods(lv)[:5]})
        if levels:
            amenities.append({
                "id": key,
                "name": name_of(key),
                "levels": levels,
                "dlc": ck3.dlc_tag(path, blk)[0],
            })

    inspirations = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "inspirations"):
        if not isinstance(blk, Block):
            continue
        gold, _ = ck3.resolve_value(blk.get("gold"))
        chance, _ = ck3.resolve_value(blk.get("progress_chance"))
        inspirations.append({
            "id": key,
            "name": name_of(key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "gold": gold,
            "progressChance": chance,
            "dlc": ck3.dlc_tag(path, blk)[0],
        })

    ck3.write_json("royalcourt.json", {
        "types": sorted(types, key=lambda r: r["name"]),
        "amenities": amenities,
        "inspirations": sorted(inspirations, key=lambda r: r["name"]),
    })


def build_gamerules():
    rules = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "game_rules"):
        if not isinstance(blk, Block):
            continue
        default = blk.get("default")
        cats = blk.get("categories")
        options = []
        for ok, _o, ov in blk:
            if not isinstance(ov, Block) or ok in ("categories",):
                continue
            options.append({
                "id": ok,
                "name": name_of(f"setting_{ok}", f"setting_{key}_{ok}", ok),
                "desc": ck3.render_text(ck3.loc(f"setting_{ok}_desc")
                                        or ck3.loc(f"setting_{key}_{ok}_desc") or "") or None,
                "blocksAchievements": "blocks_achievements" in
                                      [x for x in ov.get_all("flag") if isinstance(x, str)],
                "isDefault": ok == default,
            })
        rules.append({
            "id": key,
            "name": name_of(f"rule_{key}", f"setting_{key}", key),
            "desc": ck3.render_text(ck3.loc(f"rule_{key}_desc")
                                    or ck3.loc(f"setting_{key}_desc") or "") or None,
            "categories": [c for c in (cats.values() if isinstance(cats, Block) else [])
                           if isinstance(c, str)],
            "default": default if isinstance(default, str) else None,
            "options": options,
        })
    rules.sort(key=lambda r: ((r["categories"] or ["zz"])[0], r["name"]))
    ck3.write_json("gamerules.json", rules)


if __name__ == "__main__":
    build_court()
    build_gamerules()
