#!/usr/bin/env python3
"""Build src/data/terrain.json from common/terrain_types/.

Schema documented by the game in _terrains.info. Movement, combat width,
combat-effect advantage, and the province / county-capital / combat-side
modifier blocks are rendered through ck3.render_modifier so phrasing matches
the game. Script-valued numbers (danger, fertility growth) resolve statically.

common/province_terrain/ is consciously NOT read: it is per-province plumbing
(province id -> terrain assignment, winter severity biases), not reference data.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

HANDLED_FIELDS = {
    "color", "movement_speed", "combat_width", "attacker_modifier",
    "defender_modifier", "attacker_combat_effects", "defender_combat_effects",
    "province_modifier", "county_capital_modifier", "travel_danger_score",
    "provision_cost", "county_fertility",
}

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "audio_parameter": "ambient audio selection, not player-facing",
    "entity": "environmental 3D asset reference, not player-facing",
    "travel_danger_color": "travel-planner map-mode tint; danger score is rendered",
}


def css_color(v):
    """Game color (hsv/rgb Tagged or bare component list) -> #rrggbb."""
    tag = "rgb"
    if isinstance(v, Tagged):
        tag, v = v.tag, v.block
    if not isinstance(v, Block):
        return None
    comps = [c for c in v.values() if isinstance(c, (int, float))][:4]
    if len(comps) < 3:
        return None
    if tag == "hsv":
        h, s, val = comps[0], comps[1], comps[2]  # 4th component (alpha) ignored
        h = h / 360.0 if h > 1 else h  # hue is 0-1, but some entries use degrees
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(s, 1.0), min(val, 1.0))
        rgb = (r * 255, g * 255, b * 255)
    else:
        rgb = comps[:3]
        if all(c <= 1 for c in rgb):
            rgb = tuple(c * 255 for c in rgb)
    return "#{:02x}{:02x}{:02x}".format(*(round(c) for c in rgb))


def number(v):
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 2) if isinstance(n, float) else n
    return {"rules": rules}


def mod_lines(blk):
    if not isinstance(blk, Block):
        return []
    return [{"text": ck3.render_modifier(k, v), "polarity": ck3.modifier_polarity(k, number(v) if isinstance(v, str) else v)}
            for k, _op, v in blk if k is not None]


def combat_advantage(blk):
    """A combat_effects block -> its advantage number (name/image are art keys)."""
    if isinstance(blk, Block) and blk.has("advantage"):
        return number(blk.get("advantage"))
    return None


def main():
    entries = ck3.parse_dir(ck3.COMMON / "terrain_types")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if not isinstance(blk, Block):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name = ck3.loc(key)
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "color": css_color(blk.get("color")),
            "movementSpeed": number(blk.get("movement_speed", 1)),
            "combatWidth": number(blk.get("combat_width", 1)),
            "attackerAdvantage": combat_advantage(blk.get("attacker_combat_effects")),
            "defenderAdvantage": combat_advantage(blk.get("defender_combat_effects")),
            "attackerModifiers": mod_lines(blk.get("attacker_modifier")),
            "defenderModifiers": mod_lines(blk.get("defender_modifier")),
            "provinceModifiers": mod_lines(blk.get("province_modifier")),
            "countyCapitalModifiers": mod_lines(blk.get("county_capital_modifier")),
            "travelDangerScore": number(blk.get("travel_danger_score", 0)),
            "provisionCost": number(blk.get("provision_cost", 0)),
            "countyFertility": number(blk.get("county_fertility", 0)),
            "icon": key,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (r["name"] or r["id"]))
    ck3.write_json("terrain.json", out)

    if unhandled:
        print("⚠ unhandled terrain fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing}")


if __name__ == "__main__":
    main()
