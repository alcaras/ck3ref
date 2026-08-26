#!/usr/bin/env python3
"""Build src/data/buildings.json from common/buildings/.

Schema documented by the game in _buildings.info. Buildings form upgrade
chains via next_building (wind_furnace_01 -> 02 -> ...); every record carries
its chain root and 1-based tier so the page can group them. Requirement
triggers are extracted shallowly: terrain gates hide one level down in
building_*_requirement_terrain scripted triggers, which we resolve by parsing
common/scripted_triggers/ and pulling out the terrain/coastal/riverside
mentions. Every field present in the data is either emitted, consciously
skipped (SKIP_FIELDS), or reported as unhandled.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "ai_value": "AI construction weight, not player-facing",
    "asset": "3D model / illustration selection",
    "assets": "3D model / illustration selection",
    "on_complete": "scripted flavor effects on finish (events, variables)",
    "flag": "internal trigger flags checked by other script",
    "show_disabled": "build-menu GUI visibility plumbing",
    "can_rebuild": "great-building ruin/repair plumbing",
    "fallback": "alternative modifier set while ruined/disabled (5 great buildings)",
    "great_project_type": "great-project upgrade plumbing",
    "is_graphical_background": "map wall graphics, not constructible (entries excluded)",
}

# scope field -> (display scope, condition kind or None)
MODIFIER_BLOCKS = {
    "province_modifier": ("Holding", None),
    "county_modifier": ("County", None),
    "character_modifier": ("Owner", None),
    "county_holder_character_modifier": ("County holder", None),
    "duchy_capital_county_modifier": ("Duchy counties", None),
    "province_culture_modifier": ("Holding", "culture"),
    "county_culture_modifier": ("County", "culture"),
    "character_culture_modifier": ("Owner", "culture"),
    "duchy_capital_county_culture_modifier": ("Duchy counties", "culture"),
    "province_faith_modifier": ("Holding", "faith"),
    "county_faith_modifier": ("County", "faith"),
    "character_faith_modifier": ("Owner", "faith"),
    "province_terrain_modifier": ("Holding", "terrain"),
    "province_government_modifier": ("Holding", "government"),
    "character_government_modifier": ("Owner", "government"),
    "province_dynasty_modifier": ("Holding", "dynasty"),
    "county_dynasty_modifier": ("County", "dynasty"),
    "county_holding_modifier": ("County holdings", "holding"),
}

TRIGGER_FIELDS = (
    "can_construct_potential", "can_construct",
    "can_construct_showing_failures_only", "is_enabled",
)

HANDLED_FIELDS = {
    "construction_time", "cost_gold", "cost_prestige", "cost_piety", "cost",
    "rebuild_cost", "next_building", "type", "type_icon", "effect_desc",
    "levy", "max_garrison", "garrison_reinforcement_factor",
    "is_mandala_capital",
    *TRIGGER_FIELDS, *MODIFIER_BLOCKS,
}

CATEGORY_BY_FILE = {
    "00_castle_buildings.txt": "Castle holdings",
    "00_city_buildings.txt": "City holdings",
    "00_temple_buildings.txt": "Temple holdings",
    "temple_citadel_buildings.txt": "Temple citadels",
    "00_tribal_buildings.txt": "Tribal",
    "00_nomad_buildings.txt": "Nomadic",
    "00_admin_buildings.txt": "Administrative",
    "00_common_buildings.txt": "Common",
    "00_standard_economy_buildings.txt": "Economy",
    "00_standard_military_buildings.txt": "Military",
    "00_standard_fortification_buildings.txt": "Fortifications",
    "00_duchy_capital_buildings.txt": "Duchy capital",
    "00_special_buildings.txt": "Special",
    "ccp3_special_buildings.txt": "Special",
    "cp6_special_buildings.txt": "Special",
    "cp8_special_buildings.txt": "Special",
    "00_special_mines.txt": "Special mines",
    "00_legendary_buildings.txt": "Legendary",
    "tgp_great_project_buildings.txt": "Great projects",
    "99_ach_buildings.txt": "Oath buildings",
    "99_background_graphics_buildings.txt": "Background graphics",
}

# The game's loc file misspells this one key (building_liangzhen_mines_03).
LOC_FIXUPS = {"liangzhe_mines_03": "building_liangzhen_mines_03"}


def cost_value(v):
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 2) if isinstance(n, float) else n
    return {"rules": rules}


def costs(blk):
    """Merge cost_gold/cost_prestige/cost_piety fields and cost = {} blocks."""
    out = {}
    for field, kind in (("cost_gold", "gold"), ("cost_prestige", "prestige"),
                        ("cost_piety", "piety")):
        v = blk.get(field)
        if v is not None:
            out[kind] = cost_value(v)
    c = blk.get("cost")
    if isinstance(c, Block):
        for k, _op, v in c:
            if k is not None:
                out[k] = cost_value(v)
    elif c is not None:
        out["gold"] = cost_value(c)
    return out or None


# --- scripted trigger resolution -------------------------------------------

_triggers: dict | None = None


def scripted_triggers():
    global _triggers
    if _triggers is None:
        _triggers = {}
        for _p, key, blk in ck3.parse_dir(ck3.COMMON / "scripted_triggers"):
            if isinstance(blk, Block):
                _triggers[key] = blk
    return _triggers


def extract_terrains(trigger, found, flags):
    """Terrain/coastal/riverside mentions anywhere inside a trigger body."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k == "terrain" and isinstance(v, str):
            found.append(v)
        elif k == "is_coastal" and v is True:
            flags.add("coastal")
        elif k in ("is_riverside", "is_riverside_province") and v is True:
            flags.add("riverside")
        elif isinstance(v, (Block, Tagged)):
            extract_terrains(v, found, flags)


NEGATORS = {"NOT", "NOR", "NAND"}
RECURSE_ONLY = {"OR", "AND", "trigger_if", "trigger_else_if", "trigger_else",
                "limit", "custom_description", "custom_tooltip", "culture",
                "county", "barony", "faith", "capital_province"}

# Named requirement triggers with hand-written labels (bodies verified in
# scripted_triggers/00_building_requirement_triggers.txt).
TRIGGER_LABELS = {
    "building_requirement_tribal": ("government", "Tribal, nomadic or wanua government"),
    "building_requirement_wanua": ("government", "Wanua government"),
    "building_requirement_nomad": ("government", "Nomadic government"),
    "building_requirement_herder": ("government", "Herder government"),
    "building_requirement_tribal_holding_in_county": ("holding", "No tribal holding in county"),
    "building_requirement_nomad_holding_in_county": ("holding", "No nomad holding in county"),
    "building_requirement_herder_holding_in_county": ("holding", "No herder holding in county"),
}

LEVEL_TRIGGERS = {
    "building_requirement_castle_city_church",
    "building_requirement_castle_city_church_temple_citadel_tribe",
}

_SYNCRETIC = re.compile(r"^(\w+?)_or_syncretic_with_\w+$")

terrain_names_used: Counter = Counter()


def _terrain_name(t):
    return ck3.loc(t, t.replace("_", " ")).title() if ck3.loc(t) else t.replace("_", " ")


def add_req(reqs, kind, key, name, negated, detail=None):
    reqs.append({"kind": kind, "key": key, "negated": negated,
                 "name": name, "detail": detail})


def trigger_ref_chips(name, value, reqs, negated):
    """One level of scripted-trigger resolution -> requirement chips."""
    if value is False:
        negated = not negated
    if name in TRIGGER_LABELS:
        kind, label = TRIGGER_LABELS[name]
        add_req(reqs, kind, name, label, negated)
        return True
    if name in LEVEL_TRIGGERS:
        lvl = value.get("LEVEL") if isinstance(value, Block) else None
        add_req(reqs, "holding_level", name, f"Holding level {lvl or '?'}", negated,
                "the castle/city/temple building of this holding at this tier or higher")
        return True
    body = scripted_triggers().get(name)
    if body is None:
        return False
    if len(body) == 0:
        return True  # empty stub (e.g. all-terrain triggers, commented bodies)
    terrains, flags = [], set()
    extract_terrains(body, terrains, flags)
    if terrains or flags:
        for t in dict.fromkeys(terrains):
            terrain_names_used[t] += 1
            add_req(reqs, "terrain", t, _terrain_name(t), negated, f"via {name}")
        for f in sorted(flags):
            add_req(reqs, "terrain", f, f.title(), negated, f"via {name}")
        return True
    m = _SYNCRETIC.match(name)
    if m:
        add_req(reqs, "religion", name, f"{m.group(1).title()} (or syncretic)", negated)
        return True
    # named trigger whose conditions we don't unpack: show its name, keyed for
    # the tooltip so the reader can look the trigger up
    label = re.sub(r"^building_|^(mpo|tgp|laamp|fp\d|ep\d|bp\d)_|_requirement.*$|_trigger$", "",
                   name).replace("_", " ")
    if label.strip():
        add_req(reqs, "trigger", name, label.strip().title(), negated,
                f"scripted trigger {name}")
    return True


def gov_flag_name(flag):
    return flag.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title() + " government"


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
        elif k == "terrain" and isinstance(v, str):
            terrain_names_used[v] += 1
            add_req(reqs, "terrain", v, _terrain_name(v), negated)
        elif k in ("has_innovation", "has_all_innovations") and isinstance(v, str):
            add_req(reqs, "innovation", v, ck3.render_text(ck3.loc(v) or v.removeprefix("innovation_").replace("_", " ").title()), negated)
        elif k == "has_cultural_parameter" and isinstance(v, str):
            raw = ck3.loc(f"culture_parameter_{v}")
            add_req(reqs, "cultural_parameter", v, "Cultural tradition", negated,
                    ck3.render_text(raw) if raw else v.replace("_", " "))
        elif k == "has_building_or_higher" and isinstance(v, str):
            add_req(reqs, "building", v, ck3.render_text(ck3.loc(f"building_{v}") or v.replace("_", " ").title()), negated)
        elif k == "government_has_flag" and isinstance(v, str):
            add_req(reqs, "government", v, gov_flag_name(v), negated)
        elif k == "has_government" and isinstance(v, str):
            add_req(reqs, "government", v, ck3.render_text(ck3.loc(v) or v.replace("_", " ").title()), negated)
        elif k == "has_holding_type" and isinstance(v, str):
            add_req(reqs, "holding", v, ck3.render_text(ck3.loc(v) or v.replace("_", " ").title()), negated)
        elif k == "is_holy_site_of":
            add_req(reqs, "holy_site", str(v), "Holy site of your faith", negated)
        elif k == "has_doctrine_parameter" and isinstance(v, str):
            add_req(reqs, "doctrine_parameter", v, v.replace("_", " ").capitalize(), negated)
        elif k == "is_county_capital":
            add_req(reqs, "location", k, "County capital", negated if v is not False else not negated)
        elif k == "is_independent_ruler":
            add_req(reqs, "character", k, "Independent ruler", negated if v is not False else not negated)
        elif k == "has_title" and isinstance(v, str) and v.startswith("title:"):
            t = v.removeprefix("title:")
            add_req(reqs, "title", t, ck3.render_text(ck3.loc(t) or t.replace("_", " ").title()), negated)
        elif isinstance(v, str) and v.startswith("faith:"):
            f = v.removeprefix("faith:")
            add_req(reqs, "faith", f, ck3.render_text(ck3.loc(f) or f.title()), negated)
        elif isinstance(k, str) and (k in scripted_triggers() or k in TRIGGER_LABELS or k in LEVEL_TRIGGERS):
            trigger_ref_chips(k, v, reqs, negated)
        elif isinstance(v, (Block, Tagged)):
            # OR/AND flattening and scope drills (scope:holder.culture etc.)
            collect_requirements(v, reqs, negated)
        # anything else: shallow extraction consciously ignores it


def condition_label(kind, mb):
    """Display text for a conditional modifier block's gate."""
    if kind == "culture":
        p = mb.get("parameter")
        raw = ck3.loc(f"culture_parameter_{p}") if p else None
        return f"if culture: {ck3.render_text(raw) if raw else str(p).replace('_', ' ')}"
    if kind == "faith":
        p = mb.get("parameter")
        return f"if faith: {str(p).replace('_', ' ')}"
    if kind == "government":
        p = mb.get("parameter")
        return f"if {gov_flag_name(str(p)).lower()}"
    if kind == "dynasty":
        p = mb.get("county_holder_dynasty_perk")
        raw = ck3.loc(f"{p}_name") if p else None
        return f"if dynasty legacy: {ck3.render_text(raw) if raw else str(p).replace('_', ' ')}"
    if kind == "holding":
        p = mb.get("holding")
        return f"in each {str(p).replace('_holding', '').replace('_', ' ')} holding"
    if kind == "terrain":
        parts = []
        for t in mb.get_all("terrain"):
            terrain_names_used[t] += 1
            parts.append(_terrain_name(t))
        if mb.get("is_coastal") is True:
            parts.append("coastal")
        elif mb.get("is_coastal") is False:
            parts.append("non-coastal")
        if mb.get("is_riverside") is True:
            parts.append("riverside")
        p = mb.get("parameter")
        cond = " & ".join(parts) if parts else "any terrain"
        if p:
            raw = ck3.loc(f"culture_parameter_{p}")
            cond += f", culture: {ck3.render_text(raw) if raw else str(p).replace('_', ' ')}"
        return f"if {cond}"
    return None


META_KEYS = {"parameter", "terrain", "is_coastal", "is_riverside",
             "county_holder_dynasty_perk", "holding", "requires_dlc_flag"}


def modifier_groups(blk):
    groups = []
    for field, (scope, kind) in MODIFIER_BLOCKS.items():
        for mb in blk.get_all(field):
            if not isinstance(mb, Block):
                continue
            lines = []
            for k, _op, v in mb:
                if k is None or k in META_KEYS:
                    continue
                if isinstance(v, str):
                    n, _rules = ck3.resolve_value(v)
                    if n is not None:
                        v = round(n, 3) if isinstance(n, float) else n
                lines.append(ck3.render_modifier(k, v))
            if not lines:
                continue
            groups.append({
                "scope": scope,
                "cond": condition_label(kind, mb) if kind else None,
                "lines": lines,
            })
    return groups


def effect_text(ed):
    """effect_desc: a loc key, or a dynamic-description block of desc keys."""
    if isinstance(ed, str):
        raw = ck3.loc(ed)
        return ck3.render_text(raw) if raw else None
    if isinstance(ed, Block):
        texts = []
        def walk(b):
            for k, _op, v in b:
                if k == "desc" and isinstance(v, str):
                    raw = ck3.loc(v)
                    if raw:
                        texts.append(ck3.render_text(raw))
                elif isinstance(v, (Block, Tagged)):
                    walk(v.block if isinstance(v, Tagged) else v)
        walk(ed)
        return " / ".join(dict.fromkeys(texts)) or None
    return None


# Whole-file provenance where neither feature flags nor filename prefixes
# exist: the oath buildings are built via coronation-oath decisions
# (decisions/10_ach_oath_decisions.txt), a Crowns of the World feature.
# requires_dlc_flag and has_dlc mentions are deliberately NOT used as
# fallbacks: the former marks cosmetic asset variants (castle_01 carries
# Northern Lords meshes), the latter often gates an optional alternative
# construction route (castle_03's Japanese-castle branch).
FILE_DLC = {"99_ach_buildings.txt": "Crowns of the World"}


def main():
    entries = ck3.parse_dir(ck3.COMMON / "buildings")
    unhandled = Counter()
    by_key = {}
    excluded = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        if blk.get("is_graphical_background") is True:
            excluded.append(key)
            continue
        by_key[key] = (path, blk)

    # chain assembly: root = never referenced as next_building
    nexts = {k: b.get("next_building") for k, (_p, b) in by_key.items()
             if b.get("next_building") in by_key}
    targets = set(nexts.values())
    chain_of, tier_of = {}, {}
    for root in [k for k in by_key if k not in targets]:
        cur, tier, seen = root, 1, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain_of[cur], tier_of[cur] = root, tier
            cur, tier = nexts.get(cur), tier + 1

    # icon fallback: inherit from the nearest chain member that has one
    def icon_for(key):
        p, b = by_key[key]
        ti = b.get("type_icon")
        if ti:
            return str(ti).removesuffix(".dds")
        chain = [k for k in by_key if chain_of.get(k) == chain_of.get(key)]
        chain.sort(key=lambda k: tier_of[k])
        for k in chain:
            ti = by_key[k][1].get("type_icon")
            if ti:
                return str(ti).removesuffix(".dds")
        return None

    out = []
    cross_file = []
    static_costs = conditional_costs = 0
    for key, (path, blk) in by_key.items():
        dlc, features = ck3.dlc_tag(path, blk)
        if dlc is None:
            dlc = FILE_DLC.get(path.name)

        loc_key = LOC_FIXUPS.get(key, f"building_{key}")
        name = ck3.loc(loc_key)
        desc = ck3.loc(f"building_{key}_desc")

        reqs = []
        for f in TRIGGER_FIELDS:
            for t in blk.get_all(f):
                collect_requirements(t, reqs)
        # dedupe; drop references to the building's own chain (implicit in tiers)
        seen, deduped = set(), []
        root = chain_of[key]
        for r in reqs:
            sig = (r["kind"], r["key"], r["negated"])
            if sig in seen:
                continue
            if r["kind"] == "building" and chain_of.get(r["key"]) == root:
                continue
            seen.add(sig)
            deduped.append(r)

        c = costs(blk)
        for v in (c or {}).values():
            if isinstance(v, dict):
                conditional_costs += 1
            else:
                static_costs += 1

        ct = None
        if blk.has("construction_time"):
            ct = cost_value(blk.get("construction_time"))

        rc = None
        if blk.has("rebuild_cost"):
            rcv = blk.get("rebuild_cost")
            rc = costs(Block([("cost", "=", rcv)])) if not isinstance(rcv, Block) else {
                k: cost_value(v) for k, _o, v in rcv if k is not None}

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        root_path = by_key[root][0]
        if root_path.name != path.name:
            cross_file.append(key)

        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "category": CATEGORY_BY_FILE.get(root_path.name, root_path.stem),
            "type": blk.get("type", "regular"),
            "chain": root,
            "tier": tier_of[key],
            "constructionTime": ct,
            "cost": c,
            "rebuildCost": rc,
            "levy": cost_value(blk.get("levy")) if blk.has("levy") else None,
            "maxGarrison": cost_value(blk.get("max_garrison")) if blk.has("max_garrison") else None,
            "garrisonReinforcement": cost_value(blk.get("garrison_reinforcement_factor")) if blk.has("garrison_reinforcement_factor") else None,
            "modifiers": modifier_groups(blk),
            "effects": effect_text(blk.get("effect_desc")),
            "requirements": deduped,
            "mandalaCapital": bool(blk.get("is_mandala_capital", False)),
            "icon": icon_for(key),
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: (r["category"], r["chain"], r["tier"]))
    ck3.write_json("buildings.json", out)

    chains = len({r["chain"] for r in out})
    print(f"  {chains} chains; costs: {static_costs} static, {conditional_costs} conditional")
    if excluded:
        print(f"  excluded {len(excluded)} is_graphical_background entries (map wall graphics): {excluded}")
    if cross_file:
        print(f"⚠ {len(cross_file)} buildings in a different file than their chain root: {cross_file[:5]}")
    if unhandled:
        print("⚠ unhandled building fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")
    unres = ck3.unresolved_report()
    if unres:
        print(f"  ({len(unres)} unresolved loc functions in rendered text)")


if __name__ == "__main__":
    main()
