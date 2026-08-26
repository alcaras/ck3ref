#!/usr/bin/env python3
"""Build src/data/activities.json from common/activities/ + common/travel/.

Four record sets: activities (activity_types/), intents (intents/),
travelOptions (travel/travel_options/), pois (travel/point_of_interest_types/),
plus the activity group list (activity_group_types/).

Costs are conditional script values balanced "on County/Early Era starting
point" — we surface the game's own desc-tagged base line where one exists
(the court-positions salary pattern), else the first non-zero base in the
value chain, always marked as scaling. Never a fake single number.

DLC provenance: activities gate on scripted has_*_dlc_trigger macros and
has_dlc_feature checks inside is_shown — the whole-block dlc_tag scan would
mis-tag base activities whose *options* are DLC-gated (feast's Legendary
Feast), so features are scanned per gate block, not per entry.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP_FIELDS = {
    "notify_player_can_join_open_activity": "alert-toggle default, GUI plumbing",
    "notify_player_can_join_activity": "alert-toggle default, GUI plumbing (undocumented variant)",
    "guest_description": "planner flavor text (dynamic)",
    "can_plan": "planner gating variant; can_start covers the requirements",
    "can_always_plan": "planner gating plumbing",
    "is_valid": "mid-activity invalidation checks, not planning requirements",
    "on_invalidated": "script effect",
    "on_host_death": "script effect",
    "province_filter": "location-picker plumbing",
    "ai_province_filter": "AI plumbing",
    "province_filter_target": "location-picker plumbing",
    "is_location_valid": "per-province validity script, not a player fact",
    "province_score": "location scoring script",
    "max_province_icons": "map GUI detail",
    "max_route_deviation_mult": "travel-path GUI detail",
    "is_single_location": "planner plumbing (phases imply it)",
    "planner_type": "GUI variant flag",
    "ai_will_do": "AI hosting weight",
    "ai_check_interval": "AI plumbing",
    "ai_check_interval_by_tier": "AI plumbing",
    "ai_will_select_province": "AI plumbing",
    "ai_select_num_provinces": "AI plumbing",
    "cost": "planning-time cost script; ui_predicted_cost is the game's own "
            "player-facing estimate and is what we render",
    "reserved_guest_slots": "guest-list sizing internals",
    "allow_zero_guest_invites": "planner plumbing",
    "can_be_activity_guest": "guest eligibility script (baseline adult/range checks)",
    "guest_subsets": "phase-scripting internals",
    "guest_join_chance": "AI accept-chance script",
    "on_enter_travel_state": "script effect", "on_enter_passive_state": "script effect",
    "on_enter_active_state": "script effect", "on_leave_travel_state": "script effect",
    "on_leave_passive_state": "script effect", "on_leave_active_state": "script effect",
    "on_travel_state_pulse": "script effect", "on_passive_state_pulse": "script effect",
    "on_active_state_pulse": "script effect", "on_start": "script effect",
    "on_complete": "script effect",
    "pulse_actions": "flavor-event scheduling (skipped dir, same reason)",
    "activity_window_widgets": "GUI plugin wiring",
    "activity_planner_widgets": "GUI plugin wiring",
    "map_entity": "3D map art selection",
    "background": "event background art selection",
    "locale_background": "locale background art selection",
    "window_characters": "portrait GUI wiring",
    "travel_entourage_selection": "entourage auto-pick weights",
    "province_description": "planner flavor text (per-province dynamic)",
    "host_description": "planner flavor text (dynamic)",
    "conclusion_description": "conclusion flavor text (dynamic)",
    "locales": "locale-slot wiring; activity_locales dir skipped (GUI scene system)",
    "locale_cooldown": "locale visit pacing", "auto_select_locale_cooldown": "locale visit pacing",
    "early_locale_opening_duration": "locale visit pacing",
    "wait_time_before_start": "start-date scheduling detail",
    "max_guest_arrival_delay_time": "start-date scheduling detail",
    "max_pickable_phases_per_province": "phase-picker detail",
    "on_enter_phase": "script effect",
}

HANDLED_FIELDS = {
    "is_shown", "can_start", "can_start_showing_failures_only",
    "activity_group_type", "sort_order", "ui_predicted_cost", "cooldown",
    "max_guests", "open_invite", "options", "special_option_category",
    "phases", "num_pickable_phases", "host_intents", "guest_intents",
    "guest_invite_rules", "special_guests",
}

NEGATORS = {"NOT", "NOR", "NAND"}

# --------------------------------------------------------------------------
# DLC provenance from scripted has_*_dlc_trigger macros (name -> DLC), built
# from scripted_triggers/00_has_dlc_scripted_triggers.txt so 'ach', 'tgp',
# 'mp1' etc. resolve without extending PREFIX_TO_DLC.

_dlc_triggers: dict | None = None


def dlc_trigger_map():
    global _dlc_triggers
    if _dlc_triggers is None:
        _dlc_triggers = {}
        p = ck3.COMMON / "scripted_triggers" / "00_has_dlc_scripted_triggers.txt"
        for key, _op, blk in ck3.parse_file(p):
            if not isinstance(blk, Block):
                continue
            feats = set()
            ck3._scan_features(blk, feats)
            dlcs = sorted({ck3.FEATURE_TO_DLC[f] for f in feats if f in ck3.FEATURE_TO_DLC})
            if dlcs:
                _dlc_triggers[key] = dlcs[0]
    return _dlc_triggers


# Scripted-trigger index for one-level macro expansion (coronation_trigger
# hides its has_ach_dlc_trigger inside a scripted trigger).
_scripted_triggers: dict | None = None


def scripted_trigger(name):
    global _scripted_triggers
    if _scripted_triggers is None:
        _scripted_triggers = {}
        for _p, key, blk in ck3.parse_dir(ck3.COMMON / "scripted_triggers"):
            if isinstance(blk, Block):
                _scripted_triggers.setdefault(key, blk)
    return _scripted_triggers.get(name)


def scan_dlc(blk, dlcs, depth=0, expand=True):
    """DLC provenance from one gate block only (never the whole entry)."""
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block) or depth > 8:
        return
    for k, _op, v in blk:
        if k == "has_dlc_feature" and isinstance(v, str) and v in ck3.FEATURE_TO_DLC:
            dlcs.add(ck3.FEATURE_TO_DLC[v])
        elif isinstance(k, str) and k in dlc_trigger_map():
            dlcs.add(dlc_trigger_map()[k])
        elif isinstance(v, (Block, Tagged)):
            scan_dlc(v, dlcs, depth + 1, expand)
        elif expand and isinstance(k, str) and k.endswith("_trigger") and v is True:
            body = scripted_trigger(k)
            if body is not None:
                scan_dlc(body, dlcs, depth + 1, expand=False)


# --------------------------------------------------------------------------
# money: desc-tagged base extraction for scaled costs (court salary pattern)

# Chains whose base line is an income-scaled unit value (medium_gold_value
# etc., base 1) produce meaningless tiny bases — below this they stay "scales".
MIN_BASE = 5


def _find_base(v, depth=0, desc_only=True):
    """Walk the raw value chain the way the game evaluates it — through
    value/add and if/else branches — for the base line. First pass takes only
    desc-tagged lines (the game's own breakdown base, court salary pattern);
    the fallback pass takes the first static value/add >= MIN_BASE."""
    if depth > 8:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if not desc_only and v >= MIN_BASE:
            return v
        return None
    if isinstance(v, str):
        v = ck3.script_values().get(re.sub(r"^(root|scope:\w+|this)\.", "", v))
    if not isinstance(v, Block):
        return None
    for k, _op, val in v:
        if k in ("value", "add"):
            if isinstance(val, Block):
                if desc_only and not val.has("desc"):
                    n = _find_base(val, depth + 1, desc_only)
                else:
                    n = _find_base(val.get("value"), depth + 1, desc_only=False) \
                        if val.has("desc") else _find_base(val, depth + 1, desc_only)
            else:
                n = _find_base(val, depth + 1, desc_only)
            if n is not None:
                return n
        elif k in ("if", "else_if", "else") and isinstance(val, Block):
            body = Block([t for t in val if t[0] != "limit"])
            n = _find_base(body, depth + 1, desc_only)
            if n is not None:
                return n
    return None


def money(v):
    n, _rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": round(n, 2)} if n else None
    base = _find_base(v, desc_only=True)
    if base is None:
        base = _find_base(v, desc_only=False)
    if base is not None:
        return {"base": round(base, 2), "scales": True}
    return {"scales": True}


def money_block(blk):
    """cost block -> {resource: money}; treasury is the same amount routed by
    has_treasury and is merged into gold (court-positions pattern)."""
    if not isinstance(blk, Block):
        return {}
    out = {}
    for k, _op, v in blk:
        if k is None or k == "round":
            continue
        m = money(v)
        if m:
            out[k] = m
    if "treasury" in out:
        out.setdefault("gold", out["treasury"])
        del out["treasury"]
    return out


def duration(blk):
    """cooldown-style {years/months/weeks/days = v} -> {unit, value|base+scales}."""
    if not isinstance(blk, Block):
        return None
    for unit in ("years", "months", "weeks", "days"):
        v = blk.get(unit)
        if v is not None:
            m = money(v) or {"value": 0}
            return {"unit": unit, **m}
    return None


# --------------------------------------------------------------------------
# gates -> requirement chips (shallow, negation-aware; court-positions pattern)

TIER_NAMES = {"tier_barony": "Barony", "tier_county": "County", "tier_duchy": "Duchy",
              "tier_kingdom": "Kingdom", "tier_empire": "Empire", "tier_hegemony": "Hegemony"}

# Baseline/plumbing triggers that would repeat on nearly every row.
GATE_IGNORE = {
    "is_ai", "always", "exists", "is_adult", "is_available_adult",
    "is_capable_adult", "is_alive", "is_imprisoned", "is_landed",
    "is_landed_or_landless_administrative", "is_playable_character",
    "is_at_war", "is_ruler", "is_independent_ruler", "save_temporary_scope_as",
    "save_scope_as", "years_from_game_start", "has_character_flag",
    "has_variable", "has_game_rule", "is_activity_type_on_cooldown",
    "in_diplomatic_range", "is_healthy", "age", "trigger_if",
    "trigger_else_if", "trigger_else", "limit", "custom_description",
    "debug_only", "count", "is_current_phase_active",
    "has_attending_activity_guests",
}


def _loc_name(key, *patterns):
    for pat in patterns:
        raw = ck3.loc(pat.format(k=key))
        if raw:
            return ck3.render_text(raw)
    return None


def collect_gates(trigger, reqs, dlcs, negated=False, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 6:
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        if k == "has_dlc_feature" or (isinstance(k, str) and k in dlc_trigger_map()):
            scan_dlc(Block([(k, _op, v)]), dlcs)
            continue
        if k == "custom_tooltip" and isinstance(v, (Block, str)):
            text = v.get("text") if isinstance(v, Block) else v
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                line = ck3.render_text(raw).split("\n")[0].rstrip(":… ")
                if line:
                    reqs.append({"name": line, "negated": negated})
            continue
        if k == "highest_held_title_tier" and isinstance(v, str):
            tier = TIER_NAMES.get(v, v)
            reqs.append({"name": f"{tier} tier{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_")
            reqs.append({"name": f"{label.replace('_', ' ').title()} government",
                         "negated": negated})
            continue
        if k == "government_allows" and isinstance(v, str):
            reqs.append({"name": f"Government allows {v.replace('_', ' ')}",
                         "negated": negated})
            continue
        if k == "has_government" and isinstance(v, str):
            name = _loc_name(v, "{k}", "{k}_name")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k == "has_realm_law" and isinstance(v, str):
            name = _loc_name(v, "{k}", "{k}_name")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k == "has_trait" and isinstance(v, str):
            name = _loc_name(v, "trait_{k}")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("has_perk", "has_focus", "has_dynasty_perk") and isinstance(v, str):
            name = _loc_name(v, "{k}_name", "{k}")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("has_innovation", "has_doctrine", "has_religion") and isinstance(v, str):
            name = _loc_name(v.split(":")[-1], "{k}", "{k}_name")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k == "has_cultural_parameter" and isinstance(v, str):
            name = _loc_name(v, "culture_parameter_{k}")
            reqs.append({"name": name or "Cultural tradition", "negated": negated})
            continue
        if k in ("has_cultural_tradition", "has_cultural_pillar") and isinstance(v, str):
            name = _loc_name(v, "{k}_name", "{k}")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k in ("has_title", "completely_controls", "has_primary_title") and isinstance(v, str):
            name = _loc_name(v.split(":")[-1], "{k}")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("prestige_level", "piety_level") and isinstance(v, (int, float)):
            what = "Prestige" if k == "prestige_level" else "Devotion"
            reqs.append({"name": f"{what} level {v:g}{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k in GATE_IGNORE:
            continue
        if isinstance(v, (Block, Tagged)):
            collect_gates(v, reqs, dlcs, negated or (k in NEGATORS), depth + 1)
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            # scripted-trigger macro (coronation_trigger) — scan its body for
            # DLC gates only; its other conditions are macro internals
            body = scripted_trigger(k)
            if body is not None:
                scan_dlc(body, dlcs, expand=False)


def dedupe(reqs):
    seen, out = set(), []
    for r in reqs:
        key = (r["name"], r["negated"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# --------------------------------------------------------------------------

_missing_loc = Counter()


def loc_or_pretty(key, *patterns, strip=""):
    name = _loc_name(key, *(patterns or ("{k}",)))
    if name:
        return name
    _missing_loc[key] += 1
    return key.removeprefix(strip).replace("_", " ").title()


def intent_list(blk):
    ids = []
    if isinstance(blk, Block):
        lst = blk.get("intents")
        if isinstance(lst, Block):
            ids = [v for v in lst.values() if isinstance(v, str)]
    return ids


def build_option(key, blk, phase_names):
    """One option inside an option_category."""
    reqs, dlcs = [], set()
    collect_gates(blk.get("is_shown"), reqs, dlcs)
    collect_gates(blk.get("is_valid"), reqs, dlcs)
    blocked = []
    bp = blk.get("blocked_phases")
    if isinstance(bp, Block):
        blocked = [phase_names.get(v, v) for v in bp.values() if isinstance(v, str)]
    return {
        "id": key,
        "name": loc_or_pretty(key),
        "cost": money_block(blk.get("cost")),
        "requirements": dedupe(reqs),
        "blockedPhases": blocked,
        "dlc": sorted(dlcs)[0] if dlcs else None,
    }


def build_activity(path, key, blk, unhandled):
    name = ck3.loc(key)
    desc = ck3.loc(f"{key}_desc")

    reqs, dlcs = [], set()
    collect_gates(blk.get("is_shown"), reqs, dlcs)
    collect_gates(blk.get("can_start"), reqs, dlcs)
    collect_gates(blk.get("can_start_showing_failures_only"), reqs, dlcs)

    # phases first — options may reference them via blocked_phases
    stem = key.removeprefix("activity_")
    phases, phase_names = [], {}
    pb = blk.get("phases")
    if isinstance(pb, Block):
        for pk, _op, pv in pb:
            if pk is None or not isinstance(pv, Block):
                continue
            pname = loc_or_pretty(pk, "{k}", "activity_phase_{k}",
                                  strip=f"{stem}_phase_")
            phase_names[pk] = pname
            phases.append({
                "id": pk, "name": pname,
                "predefined": bool(pv.get("is_predefined", False)),
                "order": pv.get("order", 0),
                "cost": money_block(pv.get("cost")),
            })
        phases.sort(key=lambda p: (p["order"], p["id"]))

    special_key = blk.get("special_option_category")
    special_options, option_categories = [], []
    ob = blk.get("options")
    if isinstance(ob, Block):
        for cat, _op, cblk in ob:
            if cat is None or not isinstance(cblk, Block):
                continue
            opts = [build_option(ok, ov, phase_names)
                    for ok, _o, ov in cblk if ok is not None and isinstance(ov, Block)]
            if cat == special_key:
                special_options = opts
            else:
                option_categories.append({
                    "id": cat, "name": loc_or_pretty(cat, "{k}", f"{stem}_option_{{k}}"),
                    "options": opts,
                })

    guests = []
    sg = blk.get("special_guests")
    if isinstance(sg, Block):
        for gk, _op, gv in sg:
            if gk is not None and isinstance(gv, Block):
                guests.append({"id": gk, "name": loc_or_pretty(gk),
                               "required": bool(gv.get("is_required", False))})

    invite_rules = []
    gir = blk.get("guest_invite_rules")
    if isinstance(gir, Block):
        for part in ("rules", "defaults"):
            pblk = gir.get(part)
            if isinstance(pblk, Block):
                for _prio, _op, rule in pblk:
                    if isinstance(rule, str):
                        nm = ck3.render_text(ck3.loc(rule) or "") or None
                        if nm and nm not in invite_rules:
                            invite_rules.append(nm)

    max_guests_n, _ = ck3.resolve_value(blk.get("max_guests"))
    pickable_n, _ = ck3.resolve_value(blk.get("num_pickable_phases"))

    for k in blk.keys():
        if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
            unhandled[k] += 1

    return {
        "id": key,
        "name": ck3.render_text(name) if name else None,
        "desc": ck3.render_text(desc) if desc else None,
        "group": blk.get("activity_group_type") or "activities",
        "sortOrder": blk.get("sort_order", 0),
        "requirements": dedupe(reqs),
        "predictedCost": money_block(blk.get("ui_predicted_cost")),
        "cooldown": duration(blk.get("cooldown")),
        "maxGuests": max_guests_n,
        "openInvite": bool(blk.get("open_invite", False)),
        "specialOptions": special_options,
        "optionCategories": option_categories,
        "phases": phases,
        "numPickablePhases": pickable_n,
        "hostIntents": intent_list(blk.get("host_intents")),
        "guestIntents": intent_list(blk.get("guest_intents")),
        "specialGuests": guests,
        "inviteRules": invite_rules,
        "icon": key,
        "dlc": sorted(dlcs)[0] if dlcs else None,
        "sourceFile": path.name,
    }


# --------------------------------------------------------------------------

INTENT_SKIP = {
    "on_invalidated": "script effect", "on_target_invalidated": "script effect",
    "ai_will_do": "AI weight", "ai_targets": "AI targeting",
    "ai_target_quick_trigger": "AI targeting", "ai_target_score": "AI targeting",
    "scripted_animation": "portrait animation", "auto_complete": "GUI completion flag",
}
INTENT_HANDLED = {"is_shown", "is_valid", "is_target_valid", "icon"}


def build_intents(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "activities" / "intents"):
        if not isinstance(blk, Block):
            continue
        reqs, dlcs = [], set()
        collect_gates(blk.get("is_shown"), reqs, dlcs)
        collect_gates(blk.get("is_valid"), reqs, dlcs)
        name = ck3.loc(key)
        desc = ck3.loc(f"{key}_desc")
        for k in blk.keys():
            if k not in INTENT_HANDLED and k not in INTENT_SKIP:
                unhandled[k] += 1
        family = path.stem.removesuffix("_intents").replace("_", " ").title()
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "family": family,
            "targeted": blk.has("is_target_valid"),
            "requirements": dedupe(reqs),
            "icon": str(blk.get("icon") or key).removesuffix(".dds"),
            "dlc": sorted(dlcs)[0] if dlcs else None,
            "sourceFile": path.name,
        })
    out.sort(key=lambda r: (r["family"], r["id"]))
    return out


TRAVEL_SKIP = {
    "on_applied_effect": "script effect (its custom_tooltip is rendered as effectText)",
    "on_travel_end_effect": "script effect",
    "ai_will_do": "AI weight",
    "travel_entourage_selection": "entourage auto-pick weights",
    "owner_modifier_description": "loc override; owner_modifier lines are already rendered",
}
TRAVEL_HANDLED = {"is_shown", "is_valid", "cost", "travel_modifier", "owner_modifier"}


def rendered_mods(blk):
    out = []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return out
    for k, _op, v in blk:
        if k is None or k in ("name", "scale") or isinstance(v, (Block, Tagged)):
            continue
        out.append({"text": ck3.render_modifier(k, v),
                    "polarity": ck3.modifier_polarity(k, v)})
    return out


def effect_tooltips(blk, depth=0, found=None):
    """custom_tooltip loc lines inside an effect block — the game's own
    player-facing phrasing; we render nothing else from effects."""
    if found is None:
        found = []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block) or depth > 6:
        return found
    for k, _op, v in blk:
        if k == "custom_tooltip":
            text = v.get("text") if isinstance(v, Block) else v
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                line = ck3.render_text(raw)
                if line and line not in found:
                    found.append(line)
        elif isinstance(v, (Block, Tagged)):
            effect_tooltips(v, depth + 1, found)
    return found


def build_travel_options(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "travel" / "travel_options"):
        if not isinstance(blk, Block):
            continue
        reqs, dlcs = [], set()
        collect_gates(blk.get("is_shown"), reqs, dlcs)
        collect_gates(blk.get("is_valid"), reqs, dlcs)
        name = ck3.loc(key)
        tm = blk.get("travel_modifier")
        speed = tm.get("travel_speed") if isinstance(tm, Block) else None
        safety = tm.get("travel_safety") if isinstance(tm, Block) else None
        for k in blk.keys():
            if k not in TRAVEL_HANDLED and k not in TRAVEL_SKIP:
                unhandled[k] += 1
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "requirements": dedupe(reqs),
            "travelSpeed": speed,
            "travelSafety": safety,
            "ownerMods": rendered_mods(blk.get("owner_modifier")),
            "cost": money_block(blk.get("cost")),
            "effectText": effect_tooltips(blk.get("on_applied_effect")),
            "icon": key,
            "dlc": sorted(dlcs)[0] if dlcs else None,
            "sourceFile": path.name,
        })
    out.sort(key=lambda r: (r["name"] or r["id"]))
    return out


def build_pois():
    """POI types have no player-facing loc of their own (their names are
    per-instance tooltips) — we prettify the key and render the visit toast."""
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "travel" / "point_of_interest_types"):
        if not isinstance(blk, Block):
            continue
        visit = ck3.loc(f"{key}.visit")
        out.append({
            "id": key,
            "name": key.removeprefix("poi_").replace("_", " ").title(),
            "visitText": ck3.render_text(visit) if visit else None,
            "rewards": effect_tooltips(blk.get("on_visit")),
            "icon": key,
            "sourceFile": path.name,
        })
    out.sort(key=lambda r: r["name"])
    return out


def build_groups():
    out = []
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "activities" / "activity_group_types"):
        if isinstance(blk, Block):
            out.append({"id": key,
                        "name": loc_or_pretty(key, "activity_group_type_{k}"),
                        "sortOrder": blk.get("sort_order", 0)})
    out.sort(key=lambda g: -g["sortOrder"])
    return out


def main():
    unhandled = Counter()
    activities = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "activities" / "activity_types"):
        if isinstance(blk, Block):
            activities.append(build_activity(path, key, blk, unhandled))
    activities.sort(key=lambda r: (-r["sortOrder"], r["id"]))

    unhandled_i, unhandled_t = Counter(), Counter()
    data = {
        "groups": build_groups(),
        "activities": activities,
        "intents": build_intents(unhandled_i),
        "travelOptions": build_travel_options(unhandled_t),
        "pois": build_pois(),
    }
    ck3.write_json("activities.json", data)
    print(f"  ({len(data['activities'])} activities, {len(data['intents'])} intents, "
          f"{len(data['travelOptions'])} travel options, {len(data['pois'])} POIs)")

    for label, c in (("activity", unhandled), ("intent", unhandled_i),
                     ("travel option", unhandled_t)):
        if c:
            print(f"⚠ unhandled {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    missing = [r["id"] for r in activities if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} activities without localized names: {missing}")
    if _missing_loc:
        print(f"⚠ {len(_missing_loc)} option/phase/group keys without loc "
              f"(prettified): {[k for k, _ in _missing_loc.most_common(12)]}")


if __name__ == "__main__":
    main()
