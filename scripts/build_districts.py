#!/usr/bin/env python3
"""Build src/data/districts.json from common/districts/.

Schema documented by the game in common/districts/_districts.info. Since 1.21
a holding is made of districts: one holding district (its primary building is
the castle/city/temple…), standard districts from the holding type's roster
(common/holdings/), and slot-specific types — resource, duchy, special, great,
trade-post, entrepôt. Each district names its primary building and the first
tiers of the building lines buildable in it; the buildings themselves are in
buildings.json (build_buildings.py), cross-referenced here by key.

Emits {"types": [...], "districts": [...]}. Type names and descriptions are
the game's own DISTRICT_TYPE_* / game_concept_*_desc loc.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block

import build_buildings as bb

SKIP_FIELDS = {
    "background": "holding-view illustration selection",
    "assets": "3D model selection",
    "show_disabled": "build-menu GUI visibility plumbing",
    "can_rebuild": "great-district ruin/repair plumbing",
}

TRIGGER_FIELDS = ("can_construct_potential", "can_construct",
                  "can_construct_showing_failures_only", "is_enabled")

HANDLED_FIELDS = {
    "primary_building", "buildings", "type", "color", "can_be_replaced",
    "unlocked_by", "triggered_name", "rebuild_cost", *TRIGGER_FIELDS,
}

# district `type` -> (DISTRICT_TYPE_* loc key, game_concept key), in the order
# the game's own district concept lists them.
TYPES = {
    "holding": ("DISTRICT_TYPE_HOLDING", "holding_district"),
    "regular": ("DISTRICT_TYPE_REGULAR", "standard_district"),
    "resource": ("DISTRICT_TYPE_RESOURCE", "resource_district"),
    "duchy_capital": ("DISTRICT_TYPE_DUCHY", "duchy_district"),
    "special": ("DISTRICT_TYPE_SPECIAL", "special_district"),
    "great_district": ("DISTRICT_TYPE_GREAT", "great_district"),
    "trade_post": ("DISTRICT_TYPE_TRADE_POST", "trade_post_district"),
    "entrepot": ("DISTRICT_TYPE_ENTREPOT", "entrepot_district"),
}


def text(key):
    raw = ck3.loc(key)
    return ck3.render_text(raw).strip() if raw else None


_ICON_TOKEN = re.compile(r"\[\w+_i\]")


def focus(key):
    """<district>_desc is a "District Focus" bullet list
    ($DISTRICT_FOCUS_HEADING$ + $BULLET_WITH_TAB$ items). Return the items;
    the inline [x_i] icon tokens are dropped because each is followed by the
    concept it pictures. Anything else is returned as one plain item."""
    raw = ck3.loc(key)
    if not raw:
        return []
    raw = raw.replace("$DISTRICT_FOCUS_HEADING$", "")
    raw = _ICON_TOKEN.sub("", raw)
    parts = raw.split("$BULLET_WITH_TAB$")
    out = []
    for p in parts:
        t = ck3.render_text(p.replace("\\n", " ")).strip()
        if t:
            out.append(t)
    return out


def main():
    buildings = json.loads(
        (ck3.ROOT / "src" / "data" / "buildings.json").read_text(encoding="utf-8"))
    by_id = {b["id"]: b for b in buildings}
    chain_tiers: dict[str, list] = {}
    for b in buildings:
        chain_tiers.setdefault(b["chain"], []).append(b)
    for v in chain_tiers.values():
        v.sort(key=lambda b: b["tier"])

    # holding type -> districts it offers (primary + roster), in file order
    holding_of: dict[str, list] = {}
    for _p, hkey, hblk in ck3.parse_dir(ck3.COMMON / "holdings"):
        if not isinstance(hblk, Block):
            continue
        pd = hblk.get("primary_district")
        if isinstance(pd, str):
            holding_of.setdefault(pd, []).append({"id": hkey, "primary": True})
        dl = hblk.get("districts")
        if isinstance(dl, Block):
            for d in dl.values():
                if isinstance(d, str):
                    holding_of.setdefault(d, []).append({"id": hkey, "primary": False})

    def bref(key):
        b = by_id.get(key)
        if b is None:
            return {"id": key, "name": key.replace("_", " "), "missing": True}
        return {"id": key, "name": b["name"], "icon": b["icon"],
                "tiers": len(chain_tiers.get(b["chain"], [])), "dlc": b["dlc"]}

    unhandled = Counter()
    out = []
    order = 0
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "districts"):
        if not isinstance(blk, Block):
            continue
        order += 1
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1
        dtype = str(blk.get("type", "regular"))
        dlc, features = ck3.dlc_tag(path, blk)

        reqs = []
        for f in TRIGGER_FIELDS:
            for t in blk.get_all(f):
                bb.collect_requirements(t, reqs)
        reqs = bb.dedupe_reqs(reqs)

        pb = blk.get("primary_building")
        primary = bref(pb) if isinstance(pb, str) else None
        # building slots per district tier: building_slots_for_host_district
        # on each tier of the primary building
        tier_slots = [b["hostSlots"] for b in chain_tiers.get(pb, [])] if isinstance(pb, str) else []
        roster = []
        bl = blk.get("buildings")
        if isinstance(bl, Block):
            roster = [bref(b) for b in bl.values() if isinstance(b, str)]
        # DLC: a district inherits it from its primary building when it has
        # none of its own (special districts are one-building wrappers)
        if dlc is None and primary and not primary.get("missing"):
            dlc = primary.get("dlc")

        ub = blk.get("unlocked_by")
        rc = blk.get("rebuild_cost")
        color = blk.get("color")
        out.append({
            "id": key,
            "order": order,
            "name": text(key) or key.replace("_", " "),
            "focus": focus(f"{key}_desc"),
            "flavor": text(f"{key}_desc_flavor"),
            "type": dtype,
            "category": bb.district_category(key, {key: (dtype, path.name)}),
            "color": color if isinstance(color, str) else None,
            "primaryBuilding": primary,
            "tierSlots": tier_slots,
            "buildings": roster,
            "canBeReplaced": blk.get("can_be_replaced") is True,
            "unlockedBy": {"id": ub, "name": text(ub) or ub.replace("_", " ")} if isinstance(ub, str) else None,
            "holdings": holding_of.get(key, []),
            "requirements": reqs,
            "nameVariants": bb.triggered_names(blk),
            "rebuildCost": {k: bb.cost_value(v) for k, _o, v in rc if k is not None} if isinstance(rc, Block) else None,
            "icon": primary.get("icon") if primary else None,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    # reverse of unlocked_by
    unlocks: dict[str, list] = {}
    for d in out:
        if d["unlockedBy"]:
            unlocks.setdefault(d["unlockedBy"]["id"], []).append({"id": d["id"], "name": d["name"]})
    for d in out:
        d["unlocks"] = unlocks.get(d["id"], [])

    counts = Counter(d["type"] for d in out)
    types = []
    for t, (lk, concept) in TYPES.items():
        types.append({
            "id": t,
            "name": text(lk) or text(f"game_concept_{concept}") or t,
            "concept": concept,
            "desc": text(f"game_concept_{concept}_desc"),
            "count": counts.get(t, 0),
        })
    unknown_types = sorted(set(counts) - set(TYPES))

    # trade goods: key + name (+ the game's base price and categories), for
    # need/requirement display and the province planner. No trade page.
    goods = []
    cats: dict[str, list] = {}
    for _p, ckey, cblk in ck3.parse_dir(ck3.COMMON / "trade" / "trade_good_categories"):
        tg = cblk.get("trade_goods") if isinstance(cblk, Block) else None
        if isinstance(tg, Block):
            for g in tg.values():
                cats.setdefault(g, []).append(ckey)
    for _p, gkey, gblk in ck3.parse_dir(ck3.COMMON / "trade" / "trade_good_types"):
        if not isinstance(gblk, Block):
            continue
        goods.append({"id": gkey, "name": bb.trade_good_name(gkey),
                      "basePrice": gblk.get("base_price"),
                      "isBasic": gblk.get("is_basic") is True,
                      "categories": cats.get(gkey, [])})
    categories = [{"id": c, "name": bb.trade_good_name(c)}
                  for c in sorted({c for v in cats.values() for c in v})]

    # county -> potential trade goods (common/trade/county_potential_trade_goods),
    # fetched by the province planner. Goods as indexes into `goods`.
    gidx = {g["id"]: i for i, g in enumerate(goods)}
    county_goods: dict[str, list] = {}
    for _p, gkey, gblk in ck3.parse_dir(ck3.COMMON / "trade" / "county_potential_trade_goods"):
        cl = gblk.get("counties") if isinstance(gblk, Block) else None
        if isinstance(cl, Block) and gkey in gidx:
            for c in cl.values():
                county_goods.setdefault(c, []).append(gidx[gkey])
    for v in county_goods.values():
        v.sort()
    # county display names: the county title's own loc key
    counties = {c: [ck3.render_text(ck3.loc(c)) if ck3.loc(c) else c, g]
                for c, g in county_goods.items()}
    ck3.write_public_json("data/county-trade-goods.json",
                          {"goods": [g["id"] for g in goods], "counties": counties},
                          compact=True)

    ck3.write_json("districts.json", {
        "types": types,
        "districts": out,
        "tradeGoods": goods,
        "tradeCategories": categories,
        "concept": text("game_concept_district_desc"),
        "tierConcept": text("game_concept_district_tier_desc"),
    })
    print(f"  {len(out)} districts: {dict(counts)}")
    if unknown_types:
        print(f"⚠ district types with no DISTRICT_TYPE_* mapping: {unknown_types}")
    if unhandled:
        print("⚠ unhandled district fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    dangling = sorted({b["id"] for d in out for b in [d["primaryBuilding"] or {}, *d["buildings"]] if b.get("missing")})
    if dangling:
        print(f"⚠ building keys not found in buildings.json: {dangling}")
    nameless = [d["id"] for d in out if not ck3.loc(d["id"])]
    if nameless:
        print(f"⚠ {len(nameless)} districts without localized names: {nameless[:10]}")


if __name__ == "__main__":
    main()
