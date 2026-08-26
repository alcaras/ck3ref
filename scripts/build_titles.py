#!/usr/bin/env python3
"""Build src/data/titles.json — the de jure title hierarchy.

Tiers: h_ (hegemony, All Under Heaven) > e_ > k_ > d_ > c_ > b_. Baronies are
kept as name lists on their county (no pages). Titular/landless titles are
flagged. Colors come through as hex for swatches.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

TIERS = {"h_": "hegemony", "e_": "empire", "k_": "kingdom", "d_": "duchy",
         "c_": "county", "b_": "barony"}

META = {
    "color", "capital", "definite_form", "ruler_uses_title_name", "landless",
    "no_automatic_claims", "always_follows_primary_heir", "destroy_if_invalid_heir",
    "de_jure_drift_disabled", "can_be_named_after_dynasty", "male_names",
    "female_names", "cultural_names", "ai_primary_priority", "can_create",
    "can_create_on_partition", "province", "ignore_titularity_for_title_weighting",
    "requires_landless_type_to_hold", "noble_family", "delete_on_destroy",
    "title_history_only", "landless_playable", "creation_requires_capital",
    "no_partition", "should_show_as_hegemony", "min_independent_dejure_counties_to_be_created",
    "can_destroy", "personal_relation_entry", "personal_relation_vassal",
    "holding_regnal_male_names", "posthumous_regnal_male_names",
    "posthumous_regnal_female_names",
}


def tier_of(key):
    return TIERS.get(key[:2]) if isinstance(key, str) else None


def color_hex(v):
    vals = []
    if isinstance(v, Tagged):
        if v.tag == "hsv":
            import colorsys
            f = [x for x in v.block.values() if isinstance(x, (int, float))]
            if len(f) >= 3:
                r, g, b = colorsys.hsv_to_rgb(f[0], f[1], f[2])
                return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
            return None
        v = v.block
    if isinstance(v, Block):
        vals = [x for x in v.values() if isinstance(x, (int, float))]
    if len(vals) >= 3:
        if all(isinstance(x, float) and x <= 1.0 for x in vals[:3]):
            vals = [x * 255 for x in vals]
        return "#%02x%02x%02x" % tuple(int(max(0, min(255, x))) for x in vals[:3])
    return None


unknown_fields = Counter()


def build_node(key, blk):
    node = {
        "id": key,
        "tier": tier_of(key),
        "name": ck3.render_text(ck3.loc(key) or key),
        "color": color_hex(blk.get("color")),
    }
    cap = blk.get("capital")
    if isinstance(cap, str):
        node["capital"] = cap
    flags = [f for f in ("landless", "no_automatic_claims", "destroy_if_invalid_heir",
                         "de_jure_drift_disabled", "title_history_only", "noble_family")
             if blk.get(f) is True]
    if flags:
        node["flags"] = flags
    children = []
    baronies = []
    for k, _op, v in blk:
        if k is None or not isinstance(v, (Block, Tagged)):
            continue
        t = tier_of(k)
        if t == "barony":
            baronies.append(ck3.render_text(ck3.loc(k) or k))
        elif t:
            children.append(build_node(k, v if isinstance(v, Block) else v.block))
        elif k not in META:
            unknown_fields[k] += 1
    if baronies:
        node["baronies"] = baronies
    if children:
        node["children"] = children
    return node


def main():
    roots = []
    for f in sorted((ck3.COMMON / "landed_titles").glob("*.txt")):
        if f.name.startswith("_"):
            continue
        blk = ck3.parse_file(f)
        for key, _op, v in blk:
            if key and tier_of(key) and isinstance(v, Block):
                roots.append(build_node(key, v))

    counts = Counter()

    def count(n):
        counts[n["tier"]] += 1
        counts["barony"] += len(n.get("baronies", []))
        for c in n.get("children", []):
            count(c)

    for r in roots:
        count(r)

    ck3.write_json("titles.json", {"roots": roots, "counts": dict(counts)})
    print(f"  tiers: {dict(counts)}")
    if unknown_fields:
        print("⚠ unhandled title fields:")
        for k, n in unknown_fields.most_common(12):
            print(f"    {k} ×{n}")


if __name__ == "__main__":
    main()
