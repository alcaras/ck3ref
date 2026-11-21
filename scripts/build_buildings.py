#!/usr/bin/env python3
"""Build src/data/buildings.json from common/buildings/ (recursively).

Schema documented by the game in _buildings.info (_old_buildings.info is the
retired pre-district building set kept as a .info file — the game does not
load it, and neither do we).

Since 1.21 every building lives inside a DISTRICT (common/districts/): a
district names its primary building and the first tiers of the building lines
buildable in it. This script reads the district rosters too, so every record
carries the districts it belongs to; build_districts.py emits the districts
themselves.

Buildings form upgrade chains via next_building (day_market_1 -> 2 -> ...);
every record carries its chain root and 1-based tier. Requirement triggers
are extracted into chips, resolving named scripted triggers one level down.
Trade-good needs (trade_good_need) and market modifiers are emitted as the
game states them. Every field present in the data is either emitted,
consciously skipped (SKIP_FIELDS), or reported as unhandled.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import faith_cond
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

# Modifier-block field -> (display scope, condition kind or None).
# Every block type documented in _buildings.info.
SCOPES = {
    "character": "Owner",
    "province": "Holding",
    "county": "County",
    "duchy_capital_county": "Duchy counties",
    "market": "Market",
}
COND_KINDS = ("culture", "rite", "faith", "terrain", "dynasty", "situation",
              "government", "potential_trade_good", "size", "holding")
MODIFIER_BLOCKS = {"county_holder_character_modifier": ("County holder", None)}
for _s, _label in SCOPES.items():
    MODIFIER_BLOCKS[f"{_s}_modifier"] = (_label, None)
    for _c in COND_KINDS:
        MODIFIER_BLOCKS[f"{_s}_{_c}_modifier"] = (_label, _c)
MODIFIER_BLOCKS["county_holding_modifier"] = ("County holdings", "holding")

TRIGGER_FIELDS = (
    "can_construct_potential", "can_construct",
    "can_construct_showing_failures_only", "is_enabled",
)

HANDLED_FIELDS = {
    "construction_time", "cost_gold", "cost_prestige", "cost_piety", "cost",
    "rebuild_cost", "next_building", "type", "type_icon", "effect_desc",
    "levy", "max_garrison", "garrison_reinforcement_factor",
    "is_mandala_capital", "district_level_requirement", "triggered_name",
    "trade_good_need", "override_modifiers",
    *TRIGGER_FIELDS, *MODIFIER_BLOCKS,
}

# Trade-good need fields (_buildings.info "trade_good_need"), plus the two the
# data uses that the doc doesn't list: can_be_filled_multiple_times and the
# correctly-spelled skip_internal_fulfillment (the doc writes "fullfilment").
NEED_HANDLED = {
    "trade_good", "trade_good_category", "amount", "modifiers",
    "skip_internal_fulfillment", "skip_internal_fullfilment",
    "can_be_filled_multiple_times",
    "culture_parameter", "not_culture_parameter", "rite_parameter",
    "not_rite_parameter", "government_flag", "situation_parameter",
    "dynasty_perk", "province_size", "terrain", "is_coastal", "is_riverside",
    "potential_trade_good",
}

# District slot type -> page category. Special districts are split by the
# district file they come from (that grouping is the game's own).
DISTRICT_CATEGORY = {
    "holding": "Holding districts",
    "regular": "Standard districts",
    "resource": "Resource districts",
    "duchy_capital": "Duchy districts",
    "great_district": "Great districts",
    "trade_post": "Trade posts",
    "entrepot": "Entrepôts",
    "special": "Special",
}
SPECIAL_FILE_CATEGORY = {
    "special_mines_districts.txt": "Special mines",
    "legendary_districts.txt": "Legendary",
}
# Buildings no district lists (placed by script effects or great projects).
FILE_CATEGORY = {
    "99_ach_buildings.txt": "Oath buildings",
    "tgp_great_project_buildings.txt": "Great projects",
    "pam_buildings.txt": "Great projects",
}

# The game's loc file misspells this one key (building_liangzhen_mines_03).
LOC_FIXUPS = {"liangzhe_mines_03": "building_liangzhen_mines_03"}


def cost_value(v):
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 4) if isinstance(n, float) else n
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


# --- names -------------------------------------------------------------------

def loc_name(key):
    """Building display name. Since 1.21 the loc key is the bare building key
    (day_market_1: "$day_market$"); older content still uses building_<key>."""
    for k in (LOC_FIXUPS.get(key), key, f"building_{key}"):
        if k and ck3.loc(k):
            return ck3.render_text(ck3.loc(k))
    return None


def loc_desc(key, root):
    """_buildings.info: <key>_desc, else building_type_<chain root>_desc."""
    for k in (f"{key}_desc", f"building_type_{root}_desc", f"building_{key}_desc"):
        raw = ck3.loc(k)
        if raw:
            return ck3.render_text(raw)
    return None


def trade_good_name(key):
    raw = ck3.loc(key)
    return ck3.render_text(raw) if raw else key.removeprefix("trade_good_").removeprefix("trade_category_").replace("_", " ")


def param_label(kind, p):
    """Readable label for a culture / rite / government / situation parameter."""
    p = str(p)
    if kind == "culture":
        raw = ck3.loc(f"culture_parameter_{p}")
        return ck3.render_text(raw) if raw else p.replace("_", " ")
    if kind == "rite":
        # which doctrines/tenets grant the parameter ("Rite has A or B");
        # faith_cond falls back to the raw key when nothing grants it
        names = faith_cond.rite_param_sources(p)
        if names:
            return " or ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]
        raw = (ck3.loc(f"doctrine_parameter_{p}") or ck3.loc(f"special_doctrine_{p}_name")
               or ck3.loc(f"{p}_name") or ck3.loc(p))
        return ck3.render_text(raw) if raw else p.replace("_", " ")
    if kind == "government":
        raw = ck3.loc(p)
        return ck3.render_text(raw) if raw else gov_flag_name(p)
    if kind == "dynasty":
        raw = ck3.loc(f"{p}_name")
        return ck3.render_text(raw) if raw else p.replace("_", " ")
    return p.replace("_", " ")


def gov_flag_name(flag):
    return flag.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title() + " government"


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


NEGATORS = {"NOT", "NOR", "NAND"}
CONDITIONAL = {"trigger_if", "trigger_else_if", "trigger_else"}
# keys inside triggers that carry tooltip text or plumbing, never a condition
IGNORE_KEYS = {"text", "limit", "always", "exists", "save_temporary_scope_as",
               "save_scope_as"}

# holding_district_level_N_trigger: has_building_or_higher on any holding
# district's primary building at tier N (bodies in scripted_triggers/
# district_triggers.txt; loc holding_district_level_N_tt says the same).
_HOLDING_LEVEL = re.compile(r"^holding_district_level_(\d+)_trigger$")
LEVEL_TRIGGERS = {
    "building_requirement_castle_city_church",
    "building_requirement_castle_city_church_temple_citadel_tribe",
}

_SYNCRETIC = re.compile(r"^(\w+?)_or_syncretic_with_\w+$")

terrain_names_used: Counter = Counter()


def _terrain_name(t):
    raw = ck3.loc(t)
    return ck3.render_text(raw) if raw else t.replace("_", " ")


def add_req(reqs, kind, key, name, negated, detail=None, conditional=False):
    r = {"kind": kind, "key": key, "negated": negated, "name": name, "detail": detail}
    if conditional:
        r["conditional"] = True
    reqs.append(r)


def _strip_scope(v):
    return v.split(":", 1)[1] if isinstance(v, str) and ":" in v else v


def trigger_ref_chips(name, value, reqs, negated, conditional, depth):
    """A named scripted trigger -> requirement chips (resolved one level down)."""
    if value is False:
        negated = not negated
    m = _HOLDING_LEVEL.match(name)
    if m:
        add_req(reqs, "holding_level", name, f"Holding district tier {m.group(1)}",
                negated, f"scripted trigger {name}", conditional)
        return
    if name in LEVEL_TRIGGERS:
        lvl = value.get("LEVEL") if isinstance(value, Block) else None
        add_req(reqs, "holding_level", name, f"Holding tier {lvl or '?'}", negated,
                "the castle/city/temple building of this holding at this tier or higher",
                conditional)
        return
    body = scripted_triggers().get(name)
    if body is None:
        return
    if len(body) == 0:
        return  # empty stub (e.g. all-terrain triggers, commented bodies)
    m = _SYNCRETIC.match(name)
    if m:
        add_req(reqs, "religion", name, f"{m.group(1).title()} (or syncretic)",
                negated, f"scripted trigger {name}", conditional)
        return
    if not isinstance(value, Block) and depth < 3:
        sub = []
        collect_requirements(body, sub, negated, conditional, depth + 1)
        if sub:
            for r in sub:
                r["detail"] = f"via {name}" + (f" — {r['detail']}" if r.get("detail") and not str(r["detail"]).startswith("via ") else "")
            reqs.extend(sub)
            return
    # named trigger whose conditions we don't unpack: show its name, keyed for
    # the tooltip so the reader can look the trigger up
    label = re.sub(r"^building_|^(mpo|tgp|laamp|fp\d|ep\d|bp\d)_|_requirement.*$|_trigger$", "",
                   name).replace("_", " ").strip()
    if label:
        add_req(reqs, "trigger", name, label.capitalize(), negated,
                f"scripted trigger {name}", conditional)


def collect_requirements(trigger, reqs, negated=False, conditional=False, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k is None or k in IGNORE_KEYS:
            continue
        if k in NEGATORS:
            collect_requirements(v, reqs, not negated, conditional, depth)
        elif k in CONDITIONAL:
            # situational branches: real, but only in some cases
            collect_requirements(v, reqs, negated, True, depth)
        elif k == "OR" and not negated:
            sub = []
            collect_requirements(v, sub, False, conditional, depth)
            if len(sub) == 1:
                reqs.extend(sub)
            elif sub:
                r = {"kind": "any", "key": "|".join(s["key"] for s in sub),
                     "negated": False,
                     "name": " or ".join(("not " if s["negated"] else "") + s["name"] for s in sub),
                     "detail": "any one of these", "options": sub}
                if conditional:
                    r["conditional"] = True
                reqs.append(r)
        elif k == "terrain" and isinstance(v, str):
            terrain_names_used[v] += 1
            add_req(reqs, "terrain", v, _terrain_name(v), negated, None, conditional)
        elif k == "is_coastal" and isinstance(v, bool):
            add_req(reqs, "location", "coastal", "Coastal", negated if v else not negated, None, conditional)
        elif k in ("is_riverside", "is_riverside_province") and isinstance(v, bool):
            add_req(reqs, "location", "riverside", "Riverside", negated if v else not negated, None, conditional)
        elif k in ("has_innovation", "has_all_innovations") and isinstance(v, str):
            add_req(reqs, "innovation", v, ck3.render_text(ck3.loc(v) or v.removeprefix("innovation_").replace("_", " ").title()), negated, None, conditional)
        elif k == "has_cultural_parameter" and isinstance(v, str):
            add_req(reqs, "cultural_parameter", v, "Cultural tradition", negated,
                    param_label("culture", v), conditional)
        elif k == "rite_has_parameter" and isinstance(v, str):
            add_req(reqs, "rite_parameter", v, f"Faith: {param_label('rite', v)}", negated, None, conditional)
        elif k in ("has_building_or_higher", "has_building") and isinstance(v, str):
            add_req(reqs, "building", v, loc_name(v) or v.replace("_", " ").title(), negated,
                    "or a higher tier" if k == "has_building_or_higher" else None, conditional)
        elif k == "province_has_district" and isinstance(v, str):
            raw = ck3.loc(v)
            add_req(reqs, "district", v, ck3.render_text(raw) if raw else v.replace("_", " "), negated, None, conditional)
        elif k == "has_potential_for_trade_good" and isinstance(v, str):
            g = _strip_scope(v)
            add_req(reqs, "trade_good", g, f"County can produce {trade_good_name(g)}", negated,
                    "the county's potential trade goods", conditional)
        elif k == "production_of_trade_good_type" and isinstance(v, Block):
            g = _strip_scope(v.get("target"))
            if isinstance(g, str):
                add_req(reqs, "trade_good", g, f"Produces {trade_good_name(g)}", negated,
                        "the holding already produces this good", conditional)
        elif k == "province_size_level" and isinstance(v, (int, float)):
            add_req(reqs, "size", str(v), f"Settlement size {op} {v}", negated, None, conditional)
        elif k == "government_has_flag" and isinstance(v, str):
            add_req(reqs, "government", v, param_label("government", v), negated, None, conditional)
        elif k == "has_government" and isinstance(v, str):
            add_req(reqs, "government", v, ck3.render_text(ck3.loc(v) or v.replace("_", " ").title()), negated, None, conditional)
        elif k == "has_holding_type" and isinstance(v, str):
            add_req(reqs, "holding", v, ck3.render_text(ck3.loc(v) or v.replace("_", " ").title()), negated, None, conditional)
        elif k == "is_holy_site_of":
            add_req(reqs, "holy_site", str(v), "Holy site of your faith", negated, None, conditional)
        elif k == "has_doctrine_parameter" and isinstance(v, str):
            add_req(reqs, "doctrine_parameter", v, param_label("rite", v), negated, None, conditional)
        elif k == "is_county_capital" and isinstance(v, bool):
            add_req(reqs, "location", k, "County capital", negated if v else not negated, None, conditional)
        elif k == "is_independent_ruler" and isinstance(v, bool):
            add_req(reqs, "character", k, "Independent ruler", negated if v else not negated, None, conditional)
        elif k == "has_title" and isinstance(v, str) and v.startswith("title:"):
            t = v.removeprefix("title:")
            add_req(reqs, "title", t, ck3.render_text(ck3.loc(t) or t.replace("_", " ").title()), negated, None, conditional)
        elif isinstance(v, str) and v.startswith("faith:"):
            f = v.removeprefix("faith:")
            add_req(reqs, "faith", f, ck3.render_text(ck3.loc(f) or f.title()), negated, None, conditional)
        elif isinstance(k, str) and (k in scripted_triggers() or k in LEVEL_TRIGGERS or _HOLDING_LEVEL.match(k)):
            trigger_ref_chips(k, v, reqs, negated, conditional, depth)
        elif isinstance(v, (Block, Tagged)):
            # AND flattening, custom_tooltip bodies and scope drills
            # (scope:holder, county, culture, rite …)
            collect_requirements(v, reqs, negated, conditional, depth)
        # anything else: shallow extraction consciously ignores it


def dedupe_reqs(reqs, skip_building=None):
    seen, out = set(), []
    for r in reqs:
        sig = (r["kind"], r["key"], r["negated"], bool(r.get("conditional")))
        if sig in seen:
            continue
        if skip_building and r["kind"] == "building" and skip_building(r["key"]):
            continue
        seen.add(sig)
        out.append(r)
    return out


# --- modifiers ---------------------------------------------------------------

def condition_label(kind, mb):
    """Display text for a conditional modifier block's gate."""
    p = mb.get("parameter")
    np_ = mb.get("not_parameter")
    neg = p is None and np_ is not None
    par = p if p is not None else np_
    if kind in ("culture", "rite", "faith", "government", "situation"):
        lk = {"faith": "rite"}.get(kind, kind)
        label = param_label(lk, par) if par is not None else "?"
        what = {"culture": "culture", "rite": "faith", "faith": "faith",
                "government": "government", "situation": "situation"}[kind]
        return f"if {what} {'lacks' if neg else 'has'}: {label}"
    if kind == "dynasty":
        return f"if dynasty legacy: {param_label('dynasty', mb.get('county_holder_dynasty_perk'))}"
    if kind == "holding":
        h = mb.get("holding")
        raw = ck3.loc(h) if h else None
        return f"in each {ck3.render_text(raw) if raw else str(h).replace('_', ' ')} in the county"
    if kind == "potential_trade_good":
        return f"if the county can produce {trade_good_name(str(mb.get('trade_good')))}"
    if kind == "size":
        return f"if settlement size is exactly {mb.get('province_size')}"
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
        elif mb.get("is_riverside") is False:
            parts.append("not riverside")
        cond = " & ".join(parts) if parts else "any terrain"
        if par is not None:
            cond += f", culture {'lacks' if neg else 'has'}: {param_label('culture', par)}"
        return f"if {cond}"
    return None


META_KEYS = {"parameter", "not_parameter", "terrain", "is_coastal", "is_riverside",
             "county_holder_dynasty_perk", "holding", "requires_dlc_flag",
             "trade_good", "province_size"}


def _num(v):
    if isinstance(v, str):
        n, _rules = ck3.resolve_value(v)
        if n is not None:
            return round(n, 4) if isinstance(n, float) else n
    return v


def modifier_groups(blk):
    groups = []
    for field, (scope, kind) in MODIFIER_BLOCKS.items():
        for mb in blk.get_all(field):
            if not isinstance(mb, Block):
                continue
            lines = [ck3.render_modifier(k, _num(v)) for k, _op, v in mb
                     if k is not None and k not in META_KEYS]
            if not lines:
                continue
            groups.append({
                "scope": scope,
                "cond": condition_label(kind, mb) if kind else None,
                "lines": lines,
            })
    return groups


def host_slots(blk):
    """building_slots_for_host_district in the unconditional province_modifier
    — the district building slots this (primary) building provides."""
    for mb in blk.get_all("province_modifier"):
        if isinstance(mb, Block) and mb.has("building_slots_for_host_district"):
            n = _num(mb.get("building_slots_for_host_district"))
            if isinstance(n, (int, float)):
                return n
    return None


# --- trade-good needs --------------------------------------------------------

def need_conditions(n):
    conds = []
    for f, label in (("culture_parameter", "culture has"), ("not_culture_parameter", "culture lacks")):
        if n.has(f):
            conds.append(f"{label}: {param_label('culture', n.get(f))}")
    for f, label in (("rite_parameter", "rite has"), ("not_rite_parameter", "rite lacks")):
        if n.has(f):
            conds.append(f"{label}: {param_label('rite', n.get(f))}")
    if n.has("government_flag"):
        conds.append(param_label("government", n.get("government_flag")))
    if n.has("situation_parameter"):
        conds.append(f"situation: {param_label('situation', n.get('situation_parameter'))}")
    if n.has("dynasty_perk"):
        conds.append(f"dynasty legacy: {param_label('dynasty', n.get('dynasty_perk'))}")
    if n.has("province_size"):
        conds.append(f"settlement size exactly {n.get('province_size')}")
    if n.has("terrain"):
        t = str(n.get("terrain"))
        terrain_names_used[t] += 1
        conds.append(_terrain_name(t))
    if n.has("is_coastal"):
        conds.append("coastal" if n.get("is_coastal") else "not coastal")
    if n.has("is_riverside"):
        conds.append("riverside" if n.get("is_riverside") else "not riverside")
    if n.has("potential_trade_good"):
        conds.append(f"county can produce {trade_good_name(str(n.get('potential_trade_good')))}")
    return conds


need_unhandled: Counter = Counter()
goods_used: Counter = Counter()


def trade_needs(blk):
    out = []
    for n in blk.get_all("trade_good_need"):
        if not isinstance(n, Block):
            continue
        for k in n.keys():
            if k not in NEED_HANDLED:
                need_unhandled[k] += 1
        good = n.get("trade_good")
        cat = n.get("trade_good_category")
        key = str(good or cat)
        goods_used[key] += 1
        mods = n.get("modifiers")
        rep = n.get("can_be_filled_multiple_times")
        out.append({
            "good": key,
            "kind": "good" if good else "category",
            "name": trade_good_name(key),
            "amount": cost_value(n.get("amount", 1)),
            "times": cost_value(rep) if rep is not None else None,
            "skipInternal": bool(n.get("skip_internal_fulfillment", n.get("skip_internal_fullfilment", False))),
            "conds": need_conditions(n),
            "modifiers": modifier_groups(mods) if isinstance(mods, Block) else [],
        })
    return out


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


def triggered_names(blk):
    """triggered_name: first valid name for the province; condition chips."""
    out = []
    for tn in blk.get_all("triggered_name"):
        if not isinstance(tn, Block):
            continue
        ref = tn.get("reference")
        if not isinstance(ref, str):
            continue
        reqs = []
        collect_requirements(tn.get("trigger"), reqs)
        out.append({
            "name": loc_name(ref) or ref.replace("_", " "),
            "when": " & ".join(("not " if r["negated"] else "") + r["name"] for r in dedupe_reqs(reqs)) or "varies",
        })
    return out


def override_sets(blk):
    """override_modifiers: alternative modifier sets used when a DLC flag is on."""
    out = []
    for om in blk.get_all("override_modifiers"):
        if isinstance(om, Block):
            out.append({"dlcFlag": om.get("requires_dlc_flag"), "modifiers": modifier_groups(om)})
    return out


# Whole-file provenance where neither feature flags nor filename prefixes
# exist: the oath buildings are built via coronation-oath decisions
# (decisions/10_ach_oath_decisions.txt), a Crowns of the World feature.
# requires_dlc_flag and has_dlc mentions are deliberately NOT used as
# fallbacks: the former marks cosmetic asset variants (castle_01 carries
# Northern Lords meshes), the latter often gates an optional alternative
# construction route (castle_03's Japanese-castle branch).
FILE_DLC = {"99_ach_buildings.txt": "Crowns of the World"}


def district_membership():
    """chain-root key -> [(district key, role)] from common/districts/.
    role: 'primary' (the district's primary building) or 'building'."""
    member: dict[str, list] = {}
    dinfo = {}
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "districts"):
        if not isinstance(blk, Block):
            continue
        dtype = str(blk.get("type", "regular"))
        dinfo[key] = (dtype, path.name)
        pb = blk.get("primary_building")
        if isinstance(pb, str):
            member.setdefault(pb, []).append((key, "primary"))
        bl = blk.get("buildings")
        if isinstance(bl, Block):
            for b in bl.values():
                if isinstance(b, str):
                    member.setdefault(b, []).append((key, "building"))
    return member, dinfo


def district_category(dkey, dinfo):
    dtype, fname = dinfo[dkey]
    if dtype == "special":
        return SPECIAL_FILE_CATEGORY.get(fname, "Special")
    return DISTRICT_CATEGORY.get(dtype, dtype)


def main():
    entries = ck3.parse_dir(ck3.COMMON / "buildings", "**/*.txt")
    unhandled = Counter()
    by_key = {}
    excluded = []
    dupes = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        if blk.get("is_graphical_background") is True:
            excluded.append(key)
            continue
        if key in by_key:
            dupes.append(key)
        by_key[key] = (path, blk)

    member, dinfo = district_membership()

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
    chain_members: dict[str, list] = {}
    for k in by_key:
        chain_members.setdefault(chain_of[k], []).append(k)
    for v in chain_members.values():
        v.sort(key=lambda k: tier_of[k])

    def icon_for(key):
        """type_icon, inherited from the nearest chain member that has one.
        Since 1.21 it is a path under BUILDING_TYPE_ICON_PATH that may include
        a subfolder (regular_buildings/market_villages.dds)."""
        ti = by_key[key][1].get("type_icon")
        if ti:
            return str(ti).removesuffix(".dds")
        for k in chain_members[chain_of[key]]:
            ti = by_key[k][1].get("type_icon")
            if ti:
                return str(ti).removesuffix(".dds")
        return None

    out = []
    static_costs = conditional_costs = 0
    dangling_members = sorted(k for k in member if k not in by_key)
    for key, (path, blk) in by_key.items():
        root = chain_of[key]
        dlc, features = ck3.dlc_tag(path, blk)
        if dlc is None:
            dlc = FILE_DLC.get(path.name)

        reqs = []
        for f in TRIGGER_FIELDS:
            for t in blk.get_all(f):
                collect_requirements(t, reqs)
        # drop references to the building's own chain (implicit in tiers)
        reqs = dedupe_reqs(reqs, lambda b: chain_of.get(b) == root)

        c = costs(blk)
        for v in (c or {}).values():
            if isinstance(v, dict):
                conditional_costs += 1
            else:
                static_costs += 1

        rc = None
        if blk.has("rebuild_cost"):
            rcv = blk.get("rebuild_cost")
            rc = costs(Block([("cost", "=", rcv)])) if not isinstance(rcv, Block) else {
                k: cost_value(v) for k, _o, v in rcv if k is not None}

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        mem = member.get(root, [])
        districts = list(dict.fromkeys(d for d, _r in mem))
        primary_of = [d for d, r in mem if r == "primary"]
        if districts:
            category = district_category(districts[0], dinfo)
            dtype = dinfo[districts[0]][0]
        else:
            category = FILE_CATEGORY.get(by_key[root][0].name, "Placed by script")
            dtype = None

        name = loc_name(key)
        rec = {
            "id": key,
            "name": name,
            "desc": loc_desc(key, root),
            "category": category,
            "type": dtype,
            "districts": districts,
            "primaryOf": primary_of,
            "chain": root,
            "tier": tier_of[key],
            "districtLevel": cost_value(blk.get("district_level_requirement")) if blk.has("district_level_requirement") else None,
            "hostSlots": host_slots(blk),
            "constructionTime": cost_value(blk.get("construction_time")) if blk.has("construction_time") else None,
            "cost": c,
            "rebuildCost": rc,
            "levy": cost_value(blk.get("levy")) if blk.has("levy") else None,
            "maxGarrison": cost_value(blk.get("max_garrison")) if blk.has("max_garrison") else None,
            "garrisonReinforcement": cost_value(blk.get("garrison_reinforcement_factor")) if blk.has("garrison_reinforcement_factor") else None,
            "modifiers": modifier_groups(blk),
            "needs": trade_needs(blk),
            "overrides": override_sets(blk),
            "nameVariants": triggered_names(blk),
            "effects": effect_text(blk.get("effect_desc")),
            "requirements": reqs,
            "mandalaCapital": bool(blk.get("is_mandala_capital", False)),
            "icon": icon_for(key),
            "dlc": dlc,
            "features": features,
            "sourceFile": str(path.relative_to(ck3.COMMON / "buildings")),
        }
        out.append(rec)

    out.sort(key=lambda r: (r["category"], r["chain"], r["tier"]))
    ck3.write_json("buildings.json", out)

    chains = len({r["chain"] for r in out})
    print(f"  {chains} chains; {sum(1 for r in out if r['districts'])} buildings in a district roster; "
          f"costs: {static_costs} static, {conditional_costs} conditional")
    print(f"  {sum(len(r['needs']) for r in out)} trade-good needs over {len(goods_used)} goods/categories; "
          f"categories: {dict(Counter(r['category'] for r in out))}")
    if excluded:
        print(f"  excluded {len(excluded)} is_graphical_background entries (map wall graphics): {excluded}")
    if dupes:
        print(f"⚠ {len(dupes)} building keys defined twice (last wins): {dupes[:10]}")
    if dangling_members:
        print(f"⚠ {len(dangling_members)} district roster keys with no building: {dangling_members[:10]}")
    orphans = sorted({r["chain"] for r in out if not r["districts"]})
    if orphans:
        print(f"  {len(orphans)} chains in no district roster (placed by script): {orphans[:8]}…")
    if unhandled:
        print("⚠ unhandled building fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    if need_unhandled:
        print("⚠ unhandled trade_good_need fields:")
        for k, n in need_unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")
    unres = ck3.unresolved_report()
    if unres:
        print(f"  ({len(unres)} unresolved loc functions in rendered text)")


if __name__ == "__main__":
    main()
