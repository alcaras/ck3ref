#!/usr/bin/env python3
"""Build src/data/domiciles.json from common/domiciles/ (types + buildings).

Schema documented by the game in _domicile_types.info and
_domicile_buildings.info. Types are the five movable seats (camp, estate,
yurt, east-asian estate, japanese manor); buildings form upgrade TREES per
type via previous_building: a spine of main/external tiers with internal
buildings branching off (and 12 genuinely diverging spine branches). We
decompose each tree into tracks — a track starts at a base building, at a
slot-type change (external -> internal), or at a divergence — so the page can
render "Supply Tent I–VI" plus its internal one-offs the way the game's
domicile window slots them. Every field present in the data is either
emitted, consciously skipped (SKIP_FIELDS), or reported as unhandled.
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# No has_dlc_feature flags and no known filename prefixes anywhere under
# domiciles/ — provenance is per domicile type and hand-maintained here.
# camp + estate shipped with Roads to Power (landless adventurers + admin
# nobles), the yurt with Khans of the Steppe (nomadic government), and both
# east-asian types with All Under Heaven — the japanese manor's tgp_ files
# gate on has_tgp_dlc_trigger, whose body is has_dlc_feature =
# all_under_heaven (see ck3.PREFIX_TO_DLC's tgp entry).
TYPE_DLC = {
    "camp": "Roads to Power",
    "estate": "Roads to Power",
    "yurt": "Khans of the Steppe",
    "east_asian_estate": "All Under Heaven",
    "japanese_manor": "All Under Heaven",
}

TYPE_SKIP_FIELDS = {
    "rename_window": "which GUI rename window opens, not player-facing",
    "illustration": "realm-tab art selection",
    "map_pin_texture": "map pin art",
    "map_pin_anchor": "map pin anchoring",
    "map_pin_lobby": "game-lobby map pin visibility",
    "domicile_asset": "window background art selection",
    "map_entity": "3D map model selection",
}

TYPE_HANDLED = {
    "icon", "allowed_for_character", "provisions", "travel", "herd",
    "culture_and_faith", "move_with_realm_capital", "can_move_manually",
    "move_cooldown", "move_cost", "base_external_slots",
    "domicile_building_slots", "domicile_temperament_low_modifier",
    "domicile_temperament_high_modifier",
}

BLD_SKIP_FIELDS = {
    "ai_value": "AI construction weight, not player-facing",
    "on_complete": "scripted flavor effects on finish (events, variables)",
    "on_start": "scripted flavor effects on start",
    "on_cancelled": "scripted flavor effects on cancel",
}

BLD_HANDLED = {
    "slot_type", "internal_slots", "allowed_domicile_types",
    "previous_building", "construction_time", "cost", "refund",
    "character_modifier", "province_modifier", "parameters",
    "can_construct", "can_construct_potential", "asset",
}

# The game tags scaling costs' base line with desc = "BASE_VALUE"
# (format = "BASE_VALUE_FORMAT") — same convention as court salaries.
BASE_DESCS = {"BASE_VALUE"}


def _base_of(v):
    """The leading 'base' number of a resolve_value rule structure. Follows
    only the base chain — never multipliers/conditions, whose own bases are
    not this value's base (a ×location-modifier starting at 1 is not a cost
    of 1)."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return n
    while isinstance(rules, list) and rules and isinstance(rules[0], dict) \
            and "base" in rules[0]:
        b = rules[0]["base"]
        if isinstance(b, (int, float)):
            return b
        rules = b
    return None


def money(v):
    """One cost/amount -> {'value': n} static, {'base': n, 'scales': True}
    when the game marks a base, else {'rules': …} (rendered as 'varies')."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": round(n, 2) if isinstance(n, float) else n}
    if isinstance(v, Block):
        for k, _op, val in v:
            if k == "value" and isinstance(val, Block) and val.get("desc") in BASE_DESCS:
                b = _base_of(val.get("value"))
                if b is not None:
                    return {"base": b, "scales": True}
    b = _base_of(v)
    if b is not None:
        return {"base": b, "scales": True}
    return {"rules": rules}


def costs(blk):
    if not isinstance(blk, Block):
        return None
    out = {}
    for k, _op, v in blk:
        if k is not None:
            m = money(v)
            if m.get("value") == 0:
                continue
            out[k] = m
    return out or None


# --- requirements (shallow, negation-aware) --------------------------------

NEGATORS = {"NOT", "NOR", "NAND"}

_bld_name_cache: dict = {}


def bld_name(key):
    if key not in _bld_name_cache:
        raw = ck3.loc(f"{key}_domicile_building")
        _bld_name_cache[key] = ck3.render_text(raw) if raw else key.replace("_", " ").title()
    return _bld_name_cache[key]


def add_req(reqs, kind, key, name, negated, detail=None):
    reqs.append({"kind": kind, "key": key, "negated": negated,
                 "name": name, "detail": detail})


def collect_requirements(trigger, reqs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        if k in NEGATORS:
            collect_requirements(v, reqs, not negated)
        elif k == "has_domicile_building_or_higher" and isinstance(v, str):
            add_req(reqs, "building", v, bld_name(v), negated)
        elif k in ("has_innovation", "has_all_innovations") and isinstance(v, str):
            add_req(reqs, "innovation", v,
                    ck3.render_text(ck3.loc(v) or v.removeprefix("innovation_").replace("_", " ").title()), negated)
        elif k == "has_cultural_parameter" and isinstance(v, str):
            raw = ck3.loc(f"culture_parameter_{v}")
            add_req(reqs, "cultural_parameter", v, "Cultural tradition", negated,
                    ck3.render_text(raw) if raw else v.replace("_", " "))
        elif k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title()
            add_req(reqs, "government", v, f"{label} government", negated)
        elif k == "has_doctrine" and isinstance(v, str):
            raw = ck3.loc(v) or ck3.loc(f"{v}_name")
            add_req(reqs, "doctrine", v,
                    ck3.render_text(raw) if raw else v.replace("_", " ").title(), negated)
        elif k == "has_dynasty_perk" and isinstance(v, str):
            raw = ck3.loc(f"{v}_name")
            add_req(reqs, "dynasty_perk", v,
                    ck3.render_text(raw) if raw else v.replace("_", " ").title(), negated)
        elif k == "has_trait" and isinstance(v, str):
            raw = ck3.loc(f"trait_{v}")
            add_req(reqs, "trait", v,
                    ck3.render_text(raw) if raw else v.replace("_", " ").title(), negated)
        elif k == "is_governor" and isinstance(v, bool):
            add_req(reqs, "character", k, "Governor", negated if v else not negated)
        elif k == "is_noble_family_title" and isinstance(v, bool):
            add_req(reqs, "title", k, "Noble family title", negated if v else not negated)
        elif k == "custom_tooltip" and isinstance(v, Block):
            # UNMET-state phrasing per the game convention — label as a
            # condition, never as a positive requirement (see CLAUDE.md).
            t = v.get("text")
            raw = ck3.loc(t) if isinstance(t, str) else None
            if raw:
                add_req(reqs, "condition", str(t), ck3.render_text(raw), negated)
            collect_requirements(v, reqs, negated)
        elif isinstance(v, (Block, Tagged)):
            # OR/AND flattening and scope drills (culture, domicile, dynasty…)
            collect_requirements(v, reqs, negated)
        # anything else (has_variable, is_ai, trait xp…): shallow extraction
        # consciously ignores it


# --- temperament modifiers -------------------------------------------------

def _perk_gate(scale):
    """Camp temperament bonuses are perk-gated via `if NOT has_perk multiply 0`
    inside their scale block — surface that as the modifier's condition."""
    if not isinstance(scale, Block):
        return None
    for k, _op, v in scale:
        if k == "if" and isinstance(v, Block):
            limit = v.get("limit")
            mul = v.get("multiply")
            if mul == 0 and isinstance(limit, Block):
                neg = limit.get("NOT")
                if isinstance(neg, Block):
                    perk = neg.get("has_perk")
                    if isinstance(perk, str):
                        raw = ck3.loc(f"{perk}_name")
                        return f"with {ck3.render_text(raw) if raw else perk.replace('_', ' ')} perk"
    return None


TEMPERAMENT_META = {"name", "scale"}


def temperament(blocks):
    out = []
    for mb in blocks:
        if not isinstance(mb, Block):
            continue
        lines = [ck3.render_modifier(k, v) for k, _op, v in mb
                 if k is not None and k not in TEMPERAMENT_META]
        if lines:
            out.append({"lines": lines, "cond": _perk_gate(mb.get("scale"))})
    return out


def modifier_lines(mb):
    lines = []
    if isinstance(mb, Block):
        for k, _op, v in mb:
            if k is None:
                continue
            if isinstance(v, str):
                n, _r = ck3.resolve_value(v)
                if n is not None:
                    v = round(n, 3) if isinstance(n, float) else n
            lines.append(ck3.render_modifier(k, v))
    return lines


# --- types -----------------------------------------------------------------

def slot_counts(slots):
    counts = Counter()
    if isinstance(slots, Block):
        for _name, _op, slot in slots:
            if isinstance(slot, Block):
                counts[slot.get("slot_type", "external")] += 1
    return counts


def rel_icon(path):
    """gfx path -> key relative to gfx/interface/icons/, no extension."""
    if not isinstance(path, str):
        return None
    p = path.lstrip("/").removeprefix("gfx/interface/icons/")
    return p.removesuffix(".dds")


def build_types(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "domiciles" / "types"):
        if isinstance(blk, Tagged):
            continue
        name = ck3.loc(f"{key}_domicile_type")
        reqs = []
        collect_requirements(blk.get("allowed_for_character"), reqs)

        cooldown = None
        cd = blk.get("move_cooldown")
        if isinstance(cd, Block):
            for unit, _op, v in cd:
                if unit is not None:
                    m = money(v)
                    cooldown = {"unit": unit, **m}

        slots = slot_counts(blk.get("domicile_building_slots"))

        for k in blk.keys():
            if k not in TYPE_HANDLED and k not in TYPE_SKIP_FIELDS:
                unhandled[f"type:{k}"] += 1

        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "allowedFor": reqs,
            "travel": bool(blk.get("travel", False)),
            "provisions": bool(blk.get("provisions", False)),
            "herd": bool(blk.get("herd", False)),
            "cultureAndFaith": bool(blk.get("culture_and_faith", False)),
            "movesWithCapital": bool(blk.get("move_with_realm_capital", False)),
            "canMoveManually": bool(blk.get("can_move_manually", True)),
            "moveCooldown": cooldown,
            "moveCost": costs(blk.get("move_cost")),
            "baseExternalSlots": blk.get("base_external_slots"),
            "slots": {"main": slots.get("main", 0),
                      "external": slots.get("external", 0)},
            "temperamentHigh": temperament(blk.get_all("domicile_temperament_high_modifier")),
            "temperamentLow": temperament(blk.get_all("domicile_temperament_low_modifier")),
            "icon": rel_icon(blk.get("icon")),
            "dlc": TYPE_DLC.get(key),
            "sourceFile": path.name,
        })
    return out


# --- buildings -------------------------------------------------------------

def build_buildings(unhandled):
    entries = ck3.parse_dir(ck3.COMMON / "domiciles" / "buildings")
    by_key, order = {}, []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        by_key[key] = (path, blk)
        order.append(key)

    children = defaultdict(list)
    roots = []
    for key in order:
        prev = by_key[key][1].get("previous_building")
        if prev in by_key:
            children[prev].append(key)
        else:
            roots.append(key)

    # tree + track decomposition (definition order preserved)
    tree_of, track_of, tier_of = {}, {}, {}
    for root in roots:
        stack = [(root, root, None)]
        while stack:
            key, tree, parent = stack.pop(0)
            tree_of[key] = tree
            slot = by_key[key][1].get("slot_type", "external")
            if parent is None:
                track_of[key], tier_of[key] = key, 1
            else:
                pslot = by_key[parent][1].get("slot_type", "external")
                siblings = [c for c in children[parent]
                            if by_key[c][1].get("slot_type", "external") == slot]
                if slot == pslot and len(siblings) == 1:
                    track_of[key] = track_of[parent]
                    tier_of[key] = tier_of[parent] + 1
                else:
                    track_of[key], tier_of[key] = key, 1
            for c in children[key]:
                stack.append((c, tree, key))

    out = []
    multi_type = []
    for key in order:
        path, blk = by_key[key]
        name = ck3.loc(f"{key}_domicile_building")
        desc = ck3.loc(f"{key}_domicile_building_desc")

        allowed = blk.get("allowed_domicile_types")
        types = [v for v in allowed.values() if isinstance(v, str)] if isinstance(allowed, Block) else []
        if len(types) != 1:
            multi_type.append(key)

        reqs = []
        collect_requirements(blk.get("can_construct"), reqs)
        collect_requirements(blk.get("can_construct_potential"), reqs)
        # dedupe; drop reqs on buildings of the same tree (implicit in layout)
        seen, deduped = set(), []
        for r in reqs:
            sig = (r["kind"], r["key"], r["negated"])
            if sig in seen:
                continue
            if r["kind"] == "building" and tree_of.get(r["key"]) == tree_of[key]:
                continue
            seen.add(sig)
            deduped.append(r)

        params = []
        pb = blk.get("parameters")
        if isinstance(pb, Block):
            for pk, _op, _pv in pb:
                if pk is None:
                    continue
                # canonical key first; a handful use <key>_desc or bare <key>
                raw = (ck3.loc(f"domicile_building_parameter_{pk}")
                       or ck3.loc(f"{pk}_desc") or ck3.loc(pk))
                params.append({"key": pk,
                               "text": ck3.render_text(raw) if raw else None})

        icon = None
        for ab in blk.get_all("asset"):
            if isinstance(ab, Block) and ab.get("icon"):
                icon = rel_icon(ab.get("icon"))
                break

        for k in blk.keys():
            if k not in BLD_HANDLED and k not in BLD_SKIP_FIELDS:
                unhandled[f"building:{k}"] += 1

        dtype = types[0] if types else None
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "domicileType": dtype,
            "slotType": blk.get("slot_type", "external"),
            "internalSlots": blk.get("internal_slots", 0),
            "previousBuilding": blk.get("previous_building"),
            "tree": tree_of[key],
            "track": track_of[key],
            "tier": tier_of[key],
            "constructionTime": money(blk.get("construction_time")) if blk.has("construction_time") else None,
            "cost": costs(blk.get("cost")),
            "refund": costs(blk.get("refund")),
            "modifiers": modifier_lines(blk.get("character_modifier")),
            "provinceModifiers": modifier_lines(blk.get("province_modifier")),
            "parameters": params,
            "requirements": deduped,
            "icon": icon,
            "dlc": TYPE_DLC.get(dtype),
            "sourceFile": path.name,
        })
    if multi_type:
        print(f"⚠ {len(multi_type)} buildings with ≠1 allowed domicile type: {multi_type[:5]}")
    return out


def main():
    unhandled = Counter()
    types = build_types(unhandled)
    buildings = build_buildings(unhandled)
    ck3.write_json("domiciles.json", {"types": types, "buildings": buildings})
    print(f"  {len(types)} types, {len(buildings)} buildings,"
          f" {len({b['tree'] for b in buildings})} trees,"
          f" {len({b['track'] for b in buildings})} tracks")

    if unhandled:
        print("⚠ unhandled domicile fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [t["id"] for t in types if not t["name"]] + \
              [b["id"] for b in buildings if not b["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")
    no_param_loc = [p["key"] for b in buildings for p in b["parameters"] if not p["text"]]
    if no_param_loc:
        print(f"  ({len(no_param_loc)} parameters without loc, keys kept: {sorted(set(no_param_loc))[:8]})")


if __name__ == "__main__":
    main()
