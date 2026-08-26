#!/usr/bin/env python3
"""Build src/data/cbs.json from common/casus_belli_types/ (+ casus_belli_groups).

Schema documented in _casus_belli.info. Every field present in the data is
either emitted, consciously skipped (SKIP_FIELDS), or reported unhandled.

Loc pattern (verified): the CB key itself is the loc name for 112/121 CBs
("claim_cb" -> "Claim"); `cb_name` points at a templated key (CLAIM_CB_NAME)
full of data functions, used only as fallback. Outcome text comes from the
on_*_desc blocks: the last plain `desc` inside first_valid is the untriggered
generic fallback the game shows to observers.
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
    # scripted effect plumbing — outcomes rendered from the on_*_desc blocks
    "on_declaration": "declaration effect script; no player-facing summary",
    "on_victory": "effect script; outcome rendered from on_victory_desc",
    "on_defeat": "effect script; outcome rendered from on_defeat_desc",
    "on_white_peace": "effect script; outcome rendered from on_white_peace_desc",
    "on_invalidated": "effect script; outcome rendered from on_invalidated_desc",
    "should_invalidate": "invalidation trigger script; rendered via on_invalidated_desc",
    "ignore_effect": "effect-tooltip suppression plumbing",
    # target/defender-side validity scripts — too conditional for shallow chips
    "allowed_against_character": "defender-side validity script (faith hostility etc.)",
    "allowed_against_character_display_regardless": "defender-side validity script",
    "valid_to_start": "target-title validity script",
    "valid_to_start_display_regardless": "target-title validity script",
    "is_allowed_claim_title": "claimant validity script",
    "mutually_exclusive_titles": "multi-title targeting rule, trigger-based",
    # warscore tuning constants (defaults live in defines)
    "attacker_ticking_warscore": "warscore tuning constant",
    "defender_ticking_warscore": "warscore tuning constant",
    "attacker_ticking_warscore_delay": "warscore tuning constant",
    "defender_ticking_warscore_delay": "warscore tuning constant",
    "attacker_wargoal_percentage": "warscore tuning constant",
    "defender_wargoal_percentage": "warscore tuning constant",
    "attacker_score_from_occupation_scale": "warscore tuning constant",
    "defender_score_from_occupation_scale": "warscore tuning constant",
    "attacker_score_from_battles_scale": "warscore tuning constant",
    "defender_score_from_battles_scale": "warscore tuning constant",
    "max_attacker_score_from_battles": "warscore tuning constant",
    "max_defender_score_from_battles": "warscore tuning constant",
    "max_attacker_score_from_occupation": "warscore tuning constant",
    "max_defender_score_from_occupation": "warscore tuning constant",
    "full_occupation_by_attacker_gives_victory": "warscore edge rule",
    "full_occupation_by_defender_gives_victory": "warscore edge rule",
    "attacker_capital_gives_war_score": "warscore edge rule",
    "defender_capital_gives_war_score": "warscore edge rule",
    "imprisonment_by_attacker_give_war_score": "warscore edge rule",
    "imprisonment_by_defender_give_war_score": "warscore edge rule",
    "occupation_participation_mult": "ally participation scoring tuning",
    "siege_participation_mult": "ally participation scoring tuning",
    "battle_participation_mult": "ally participation scoring tuning",
    "check_all_defenders_for_ticking_war_score": "warscore scoping rule",
    "ticking_war_score_targets_entire_realm": "warscore scoping rule",
    "use_de_jure_wargoal_only": "wargoal scoping for ticking score",
    "landless_attacker_needs_armies": "landless auto-loss edge rule",
    "target_top_liege_if_outside_realm": "scripted-war engine bypass",
    # war continuation plumbing (death handling IS emitted, see HANDLED)
    "transfer_behavior": "title-transfer continuation plumbing",
    "check_attacker_inheritance_validity": "inheritance validation plumbing",
    "check_defender_inheritance_validity": "inheritance validation plumbing",
    "attacker_allies_inherit": "ally inheritance plumbing",
    "defender_allies_inherit": "ally inheritance plumbing",
    # AI plumbing
    "ai": "AI usage toggle",
    "ai_score": "AI scoring script",
    "ai_score_mult": "AI scoring script",
    "ai_can_target_all_titles": "AI targeting script",
    "ai_only_against_liege": "AI targeting restriction",
    "ai_only_against_neighbors": "AI targeting restriction",
    "max_ai_diplo_distance_to_title": "AI targeting restriction",
    "ai_overlord_defensive_power_impact": "AI power-evaluation script",
    # UI plumbing
    "interface_priority": "declare-war list sort order",
    "combine_into_one": "declare-war list grouping",
    "should_show_war_goal_subview": "war UI layout flag",
    "should_check_for_interface_availability": "has-any-cb check exclusion",
    "gui_attacker_faith_might_join": "warning-text-only flag",
    "gui_defender_faith_might_join": "warning-text-only flag",
    # name variants (war_name is rendered; these are UI/grammar alternates)
    "war_name_base": "flavorization base name variant",
    "my_war_name": "grammar variant when attacker == claimant",
    "my_war_name_base": "flavorization base name variant",
    "cb_name_no_target": "UI name variant without target",
}

HANDLED_FIELDS = {
    "group", "icon", "cb_name", "war_name", "cost",
    "target_titles", "target_title_tier", "target_de_jure_regions_above",
    "on_victory_desc", "on_defeat_desc", "on_white_peace_desc",
    "on_invalidated_desc", "allowed_for_character",
    "allowed_for_character_display_regardless",
    "truce_days", "white_peace_possible", "allow_hostages",
    "is_great_holy_war", "is_holy_war", "defender_faith_can_join",
    "on_primary_attacker_death", "on_primary_defender_death",
}

# Group keys have no loc; hand-labeled for the group headers.
GROUP_LABELS = {
    "religious": "Religious",
    "religious_disorganised": "Religious (disorganised)",
    "religious_script_only": "Religious (event wars)",
    "de_jure": "De Jure",
    "claim": "Claim",
    "civil_war": "Civil War",
    "invasion": "Invasion",
    "vassalization": "Vassalization",
    "conquest": "Conquest",
    "struggle": "Struggle",
    "subjugation": "Subjugation",
    "independence": "Independence",
    "event": "Event Wars",
    "artifact": "Artifact",
    "migration": "Migration",
    "humiliation": "Humiliation",
    "mandala": "Mandala",
    "celestial": "Celestial",
    "debug": "Debug",
}

# --- role-word rendering for war names and outcome descs ---------------------
# Loc strings for CBs are full of dynamic scopes ([attacker.GetShortUIName]).
# There is no static answer, but the ROLE is static — substitute it before
# render_text so outcomes read "The claimant gains the contested Title."

ROLES = {
    "attacker": "the attacker", "defender": "the defender",
    "claimant": "the claimant", "second_attacker": "the co-attacker",
    "title": "the target title", "target_title": "the target title",
    "target": "the target title", "casus_belli": "the casus belli",
    "war": "the war", "faction": "the faction",
}
_SCOPE_CALL = re.compile(r"\[([A-Za-z_]+)((?:\.[A-Za-z_]\w*(?:\([^\[\]]*\))?)+)(\|\w+)?\]")
_CONCAT_CALL = re.compile(r"\[Concat\w*\([^\]]*\)\]")  # war-ordinal injection ("2nd …")
_PRONOUNS = {
    "GetHerHis": "their", "GetSheHe": "they", "GetHerHim": "them",
    "GetHersHis": "theirs", "GetHerselfHimself": "themselves",
    "GetWomanMan": "person", "GetDaughterSon": "child",
}


def role_render(raw):
    """render_text with dynamic character/title scopes replaced by role words."""
    if not raw:
        return None

    def sub(m):
        root, chain = m.group(1), m.group(2)
        for pn, word in _PRONOUNS.items():
            if pn in chain:
                return word
        role = ROLES.get(root.lower())
        if role is None:
            return m.group(0)  # leave for render_text (concepts, functions)
        if "Possessive" in chain or "GetAdjective" in chain:
            return role + "'s"
        return role

    txt = ck3.render_text(_SCOPE_CALL.sub(sub, _CONCAT_CALL.sub("", raw)))
    if not txt:
        return None
    txt = re.sub(r"\s+([.,])", r"\1", txt)
    txt = re.sub(r"\b[Tt]he the\b", "the", txt)
    return txt[0].upper() + txt[1:]


def desc_keys(blk):
    """All `desc` loc keys inside an on_*_desc block, fallback last."""
    out = []

    def walk(b):
        if isinstance(b, Tagged):
            b = b.block
        if not isinstance(b, Block):
            return
        for k, _op, v in b:
            if k == "desc" and isinstance(v, str):
                out.append(v)
            elif isinstance(v, (Block, Tagged)):
                walk(v)

    walk(blk)
    return out


def outcome_text(blk):
    """Rendered generic outcome: the untriggered fallback desc, else the first
    triggered desc whose loc renders non-empty."""
    keys = desc_keys(blk)
    for k in ([keys[-1]] + keys[:-1]) if keys else []:
        txt = role_render(ck3.loc(k))
        if txt:
            return txt
    return None


# --- costs -------------------------------------------------------------------

def _find_base_cost(rules):
    """The game's own base-cost concept: a static value tagged desc=CB_BASE_COST
    (see _casus_belli.info). Returns the number or None."""
    if isinstance(rules, list):
        nums = [d["base"] for d in rules if isinstance(d, dict)
                and isinstance(d.get("base"), (int, float))]
        tagged = any(isinstance(d, dict) and d.get("desc") == "CB_BASE_COST"
                     for d in rules)
        if tagged and len(nums) == 1:
            return nums[0]
        for d in rules:
            if isinstance(d, dict):
                for v in d.values():
                    n = _find_base_cost(v)
                    if n is not None:
                        return n
    return None


def cost_value(v):
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 2) if isinstance(n, float) else n
    base = _find_base_cost(rules)
    return {"varies": True, **({"base": base} if base is not None else {})}


def costs_block(blk):
    if not isinstance(blk, Block):
        return None
    return {k: cost_value(v) for k, _op, v in blk if k is not None}


# --- availability chips ------------------------------------------------------
# Shallow requirement extraction (the men-at-arms pattern): recognized trigger
# keys become chips with negation tracking. `limit` blocks are branch
# conditions, not requirements, and are not descended into. Scripted-trigger
# macro calls (herders_and_tributary_constraints, tgp_*_ban_trigger, …) are
# NOT expanded: their bodies mix attacker- and defender-side constraints under
# trigger_if scaffolding that shallow extraction would misattribute.

NEGATORS = {"NOT", "NOR", "NAND"}

REQ_KEYS = {
    "government_has_flag": "government_flag",
    "government_allows": "government_type",
    "has_government": "government",
    "has_doctrine_parameter": "doctrine_parameter",
    "has_doctrine": "doctrine",
    "has_trait": "trait",
    "has_perk": "perk",
    "has_innovation": "innovation",
    "has_cultural_parameter": "cultural_parameter",
    "has_cultural_pillar": "cultural_pillar",
    "has_realm_law": "law",
    "has_game_rule": "game_rule",
    "has_title": "title",
    "completely_controls": "title",
    "is_leading_faction_type": "faction",
}

_LOC_BY_KIND = {
    "innovation": lambda k: ck3.loc(k),
    "doctrine": lambda k: ck3.loc(k) or ck3.loc(f"{k}_name"),
    "trait": lambda k: ck3.loc(f"trait_{k}"),
    "government": lambda k: ck3.loc(k),
    "government_type": lambda k: ck3.loc(f"{k}_government") or ck3.loc(k),
    "cultural_pillar": lambda k: ck3.loc(k),
    "cultural_parameter": lambda k: ck3.loc(f"culture_parameter_{k}"),
    "perk": lambda k: ck3.loc(f"{k}_name"),
    "law": lambda k: ck3.loc(k) or ck3.loc(f"{k}_name"),
    "game_rule": lambda k: ck3.loc(f"rule_{k}") or ck3.loc(k),
    "title": lambda k: ck3.loc(k) or ck3.loc(f"{k}_name"),
    "faction": lambda k: ck3.loc(f"{k}_name") or ck3.loc(k),
}

TIERS = {"tier_barony": "barony", "tier_county": "county", "tier_duchy": "duchy",
         "tier_kingdom": "kingdom", "tier_empire": "empire"}


def req_name(kind, key):
    raw = _LOC_BY_KIND.get(kind, lambda k: None)(key)
    if raw:
        return ck3.render_text(raw)
    label = (key.removeprefix("government_is_").removeprefix("government_")
                .removeprefix("flag_").removeprefix("title:")
                .replace("_", " ").capitalize())
    return label


def collect_requirements(trigger, reqs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k is None or k == "limit":
            continue
        if k in REQ_KEYS and isinstance(v, str):
            kind = REQ_KEYS[k]
            reqs.append({"kind": kind, "key": v, "negated": negated,
                         "name": req_name(kind, v.removeprefix("title:"))})
        elif k in ("is_independent_ruler", "is_landed") and isinstance(v, bool):
            name = "Independent ruler" if k == "is_independent_ruler" else "Landed"
            reqs.append({"kind": "status", "key": k, "negated": negated != (not v),
                         "name": name})
        elif k == "highest_held_title_tier" and isinstance(v, str):
            tier = TIERS.get(v, v)
            reqs.append({"kind": "tier", "key": f"{k} {op} {v}", "negated": negated,
                         "name": f"Highest title {op} {tier}"})
        elif k in ("piety_level", "prestige_level") and isinstance(v, (int, float)):
            res = "Piety" if k == "piety_level" else "Prestige"
            reqs.append({"kind": "level", "key": f"{k} {op} {v}", "negated": negated,
                         "name": f"{res} level {op} {v:g}"})
        elif isinstance(v, (Block, Tagged)):
            collect_requirements(v, reqs, negated or (k in NEGATORS))


def dedupe(reqs):
    """Drop duplicate chips; collapse piety/prestige-level branch ladders
    (rank- and culture-dependent thresholds) into one honest 'varies' chip."""
    seen, out = set(), []
    levels = {}
    for r in reqs:
        if r["kind"] == "level" and not r["negated"]:
            res = r["name"].split()[0]
            levels.setdefault(res, []).append(r)
            continue
        if r["kind"] == "level" and r["negated"]:
            continue  # NOT piety_level = -1 style branch guards — no chip value
        sig = (r["name"], r["negated"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    for res, rs in levels.items():
        if len(rs) == 1:
            out.append(rs[0])
        else:
            ns = sorted({float(r["key"].split()[-1]) for r in rs})
            out.append({"kind": "level", "key": rs[0]["key"], "negated": False,
                        "name": f"{res} level ≥ {ns[0]:g}–{ns[-1]:g} (varies by rank)"})
    return out


# --- groups ------------------------------------------------------------------

def build_groups():
    groups = {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "casus_belli_groups"):
        reqs = []
        collect_requirements(blk.get("allowed_for_character"), reqs)
        groups[key] = {
            "label": GROUP_LABELS.get(key, key.replace("_", " ").title()),
            "scriptOnly": bool(blk.get("can_only_start_via_script", False)),
            "debug": bool(blk.get("debug", False)),
            "requirements": dedupe(reqs),
        }
    return groups


def main():
    groups = build_groups()
    entries = ck3.parse_dir(ck3.COMMON / "casus_belli_types")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)

        # religious_war's own loc is the fragment "Holy" (the UI composes
        # "Holy War for <tier>"); use the game concept's full name instead.
        if key == "religious_war":
            name = ck3.render_text(ck3.loc("game_concept_holy_war"))
        else:
            name = ck3.render_text(ck3.loc(key)) if ck3.loc(key) else None
        if not name:
            cbn = blk.get("cb_name")
            name = role_render(ck3.loc(cbn)) if isinstance(cbn, str) and ck3.loc(cbn) else None
        if not name:
            name = key.removesuffix("_cb").replace("_", " ").title()

        reqs = []
        collect_requirements(blk.get("allowed_for_character"), reqs)
        collect_requirements(blk.get("allowed_for_character_display_regardless"), reqs)

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        wn = blk.get("war_name")
        icon = str(blk.get("icon") or key).removesuffix(".dds")
        rec = {
            "id": key,
            "name": name,
            "group": blk.get("group"),
            "warName": role_render(ck3.loc(wn)) if isinstance(wn, str) else None,
            "targetTitles": blk.get("target_titles"),
            "targetTier": blk.get("target_title_tier"),
            "deJureRegionsAbove": bool(blk.get("target_de_jure_regions_above", False)),
            "costs": costs_block(blk.get("cost")),
            "outcomes": {
                "victory": outcome_text(blk.get("on_victory_desc")),
                "defeat": outcome_text(blk.get("on_defeat_desc")),
                "whitePeace": outcome_text(blk.get("on_white_peace_desc")),
                "invalidated": outcome_text(blk.get("on_invalidated_desc")),
            },
            "whitePeacePossible": blk.get("white_peace_possible") is not False,
            "allowHostages": blk.get("allow_hostages") is not False,
            "onAttackerDeath": blk.get("on_primary_attacker_death"),
            "onDefenderDeath": blk.get("on_primary_defender_death"),
            "truceDays": blk.get("truce_days"),
            "isGreatHolyWar": bool(blk.get("is_great_holy_war", False)),
            "isHolyWar": bool(blk.get("is_holy_war", False)),
            "defenderFaithCanJoin": bool(blk.get("defender_faith_can_join", False)),
            "requirements": dedupe(reqs),
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: (r["group"] or "", r["id"]))

    # Default truce: standard_truce_duration_days script value (base 5 years,
    # conditional modifiers) — only 2 CBs override with truce_days.
    n, rules = ck3.resolve_value("standard_truce_duration_days")
    base_truce = n
    if base_truce is None and isinstance(rules, list):
        base_truce = next((d["base"] for d in rules
                           if isinstance(d, dict) and isinstance(d.get("base"), (int, float))), None)

    ck3.write_json("cbs.json", {
        "cbs": out,
        "groups": groups,
        "meta": {"defaultTruceDays": base_truce, "defaultTruceVaries": n is None},
    })

    if unhandled:
        print("⚠ unhandled CB fields (add to HANDLED or SKIP):")
        for k, c in unhandled.most_common():
            print(f"    {k} ×{c}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without names: {missing[:10]}")
    no_outcome = [r["id"] for r in out if not r["outcomes"]["victory"]]
    if no_outcome:
        print(f"  (no victory text: {no_outcome})")


if __name__ == "__main__":
    main()
