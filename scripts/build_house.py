#!/usr/bin/env python3
"""Build src/data/house.json — the dynasty-house mechanics bundle:

- house_unities/          unity stages (clan government)
- house_aspirations/      admin powerful-family powers + AUH/TGP aspirations
- house_relation_types/   feud→amity relation ladder
- legitimacy/             per-tier legitimacy levels (thresholds × tier/era)
- diarchies/              diarchy types (scales of power) + mandates

Each section keeps its own HANDLED/SKIP accounting; anything else is
reported unhandled. Legitimacy thresholds are `base × legitimacy_title_era_value`
(2–8, title tier + cultural era) — emitted as {base, min, max}, never one number.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

unhandled = Counter()

# ---------------------------------------------------------------------------
# shared loc helpers (same conventions as build_accolades.py)

_SCRIPT_VALUE = re.compile(r"\[EmptyScope\.ScriptValue\(\s*'(\w+)'\s*\)(\|[^\]]+)?\]")


def resolve_scriptvalue_calls(s):
    def sub(m):
        n, _rules = ck3.resolve_value(m.group(1))
        if n is None:
            return m.group(0)
        fmt = m.group(2) or ""
        pct = ""
        if "%" in fmt:
            pct = "%"
            if "%/" not in fmt:  # '%' scales ×100; '%/' is sign-only
                n = n * 100
        num = f"{round(n, 2):g}"
        if "+" in fmt and n > 0:
            num = "+" + num
        return num + pct
    return _SCRIPT_VALUE.sub(sub, s)


def render_loc(raw):
    raw = raw.replace("$EFFECT_LIST_BULLET$", "\\n")
    raw = re.sub(r"\[\w+_i\]", "", raw)
    text = ck3.render_text(resolve_scriptvalue_calls(raw))
    text = text.replace("++", "+")  # loc "+" meeting a sign-formatted value
    lines = [ln.strip().lstrip("•").strip() for ln in text.split("\n")]
    # a line that is only "…" carries no information — the caller falls back
    return [ln for ln in lines if ln and ln != "…"]


def prettify(key):
    return key.replace("_", " ").capitalize()


def render_mods(blk, skip=()):
    if not isinstance(blk, Block):
        return []
    return [ck3.render_modifier(k, v) for k, v in blk.items() if k not in skip]


def num_or_rules(v):
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 2) if isinstance(n, float) else n
    return {"rules": rules}


# ---------------------------------------------------------------------------
# house unities

UNITY_META = {"default_value", "min_value"}
UNITY_STAGE_HANDLED = {"points", "parameters", "modifiers", "decisions"}
UNITY_STAGE_SKIP = {
    "on_start": "stage-entry effect (succession law swap is surfaced via the "
                "unity_succession_* parameter loc)",
    "on_end": "stage-exit effect plumbing",
    "succession_law_flag": "internal law-selection flag",
    "icon": "GUI stage icon",
}


def build_unity():
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "house_unities"):
        gov = key.removesuffix("_house_unity")
        gov_name = ck3.loc(f"{gov}_government")
        concept = ck3.loc("game_concept_house_unity") or "House Unity"
        stages = []
        acc = 0
        for sk, _op, sv in blk:
            if sk in UNITY_META or sk is None or not isinstance(sv, Block):
                continue
            points = sv.get("points", 0)
            params = []
            pb = sv.get("parameters")
            if isinstance(pb, Block):
                for p, _v in pb.items():
                    raw = ck3.loc(f"house_unity_parameter_{p}")
                    params.extend((render_loc(raw) or [prettify(p)]) if raw else [prettify(p)])
            decisions = []
            db = sv.get("decisions")
            if isinstance(db, Block):
                for d in db.values():
                    if isinstance(d, str):
                        nm = ck3.loc(d)
                        decisions.append({"id": d, "name": ck3.render_text(nm) if nm else prettify(d)})
            for k in sv.keys():
                if k not in UNITY_STAGE_HANDLED and k not in UNITY_STAGE_SKIP:
                    unhandled[f"unity.stage.{k}"] += 1
            name = ck3.loc(sk)
            stages.append({
                "id": sk,
                "name": ck3.render_text(name) if name else prettify(sk),
                "points": points,
                "from": acc,
                "to": acc + points - 1,
                "params": params,
                "modifiers": render_mods(sv.get("modifiers")),
                "decisions": decisions,
            })
            acc += points
        out.append({
            "id": key,
            "name": f"{ck3.render_text(gov_name)} {ck3.render_text(concept)}" if gov_name else prettify(key),
            "defaultValue": blk.get("default_value"),
            "minValue": blk.get("min_value"),
            "maxValue": acc - 1,
            "stages": stages,
        })
    return out


# ---------------------------------------------------------------------------
# house aspirations

ASP_GROUPS = {
    "00_admin_house_powers.txt": ("admin", "Administrative — Powerful Family Attributes"),
    "10_tgp_celestial_house_powers.txt": ("celestial", "Celestial (China) — Family Aspirations"),
    "10_tgp_japan_house_aspirations.txt": ("japan", "Japanese — House Aspirations"),
    "tgp_mandala_devaraja_aspects.txt": ("mandala", "Mandala — Devaraja Aspects"),
}

ASP_HANDLED = {"is_shown", "level", "cooldown", "is_default", "confederation_type"}
ASP_SKIP = {
    "show_in_main_hud": "GUI placement flag",
    "illustration": "window art; no icon pipeline for aspiration keys yet",
    "on_changed": "aspiration-switch effect plumbing",
    "on_upgraded": "upgrade effect plumbing",
}
ASP_LEVEL_HANDLED = {"cost", "powerful_family_top_liege_modifier",
                     "powerful_family_member_modifier", "any_house_member_modifier",
                     "house_head_modifier", "parameters", "house_head_parameters",
                     "can_request_great_project_contributions_from_allies"}
ASP_LEVEL_SKIP = {
    "ai_score": "AI pick/upgrade scoring",
    "can_upgrade": "upgrade-gate trigger (house power level plumbing)",
    "always": "trigger stub in no_aspiration placeholder",
    "trigger_event": "event effect plumbing",
    "update_character_movement_power_effect": "movement-power recalc effect",
    "mandala_change_between_aspects_effect": "aspect-switch effect plumbing",
}

NEGATORS = {"NOT", "NOR", "NAND"}


def gates_from_is_shown(trigger, gates, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k == "government_allows" and isinstance(v, str):
            g = ck3.loc(f"{v}_government") or ck3.loc(v)
            gates.append({"name": f"{ck3.render_text(g) if g else prettify(v)} government",
                          "negated": negated})
        elif k == "government_has_flag" and isinstance(v, str):
            gates.append({"name": prettify(v.removeprefix("government_")), "negated": negated})
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            stem = k.removesuffix("_trigger").removeprefix("government_is_").removeprefix("is_")
            gates.append({"name": prettify(stem), "negated": negated})
        elif isinstance(v, (Block, Tagged)):
            gates_from_is_shown(v, gates, negated or (k in NEGATORS))


def build_aspirations():
    groups = {gid: {"id": gid, "label": label, "entries": []}
              for gid, label in ASP_GROUPS.values()}
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "house_aspirations"):
        gid, _label = ASP_GROUPS.get(path.name, (None, None))
        if gid is None:
            unhandled[f"aspirations.file.{path.name}"] += 1
            continue
        dlc, _features = ck3.dlc_tag(path, blk)
        gates = []
        gates_from_is_shown(blk.get("is_shown"), gates)
        # dedup, keep order
        seen = set()
        gates = [g for g in gates if not (tuple(g.values()) in seen or seen.add(tuple(g.values())))]

        levels = []
        for i, lv in enumerate(blk.get_all("level"), start=1):
            if not isinstance(lv, Block):
                continue
            cost = {}
            cb = lv.get("cost")
            if isinstance(cb, Block):
                for ck, _o, cv in cb:
                    if ck is not None:
                        cost[ck] = num_or_rules(cv)
            params = []
            for field in ("parameters", "house_head_parameters"):
                pb = lv.get(field)
                if isinstance(pb, Block):
                    for p, _v in pb.items():
                        raw = ck3.loc(f"house_aspiration_parameter_{p}")
                        params.extend((render_loc(raw) or [prettify(p)]) if raw else [prettify(p)])
            for k in lv.keys():
                if k not in ASP_LEVEL_HANDLED and k not in ASP_LEVEL_SKIP:
                    unhandled[f"aspirations.level.{k}"] += 1
            levels.append({
                "level": i,
                "cost": cost,
                "topLiege": render_mods(lv.get("powerful_family_top_liege_modifier")),
                "member": render_mods(lv.get("powerful_family_member_modifier")),
                "anyMember": render_mods(lv.get("any_house_member_modifier")),
                "houseHead": render_mods(lv.get("house_head_modifier")),
                "params": params,
                "greatProjectHelp": bool(lv.get("can_request_great_project_contributions_from_allies", False)),
            })

        for k in blk.keys():
            if k not in ASP_HANDLED and k not in ASP_SKIP:
                unhandled[f"aspirations.{k}"] += 1

        cd = blk.get("cooldown")
        name = ck3.loc(f"{key}_house_aspiration")
        groups[gid]["entries"].append({
            "id": key,
            "name": ck3.render_text(name) if name else prettify(key),
            "gates": gates,
            "isDefault": bool(blk.get("is_default", False)),
            "confederation": blk.get("confederation_type"),
            "cooldownYears": cd.get("years") if isinstance(cd, Block) else None,
            "levels": levels,
            "dlc": dlc,
        })
    return [groups[gid] for gid, _ in ASP_GROUPS.values()]


# ---------------------------------------------------------------------------
# house relations

REL_HANDLED = {"neutral_level", "levels"}
REL_SKIP = {
    "is_valid_to_start": "relation-tracking relevance trigger (memory/perf plumbing)",
    "is_valid_to_keep": "relation pruning trigger (memory/perf plumbing)",
}
REL_LEVEL_HANDLED = {"opinion", "cohesion_contribution", "parameters"}


def build_relations():
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "house_relation_types"):
        levels = []
        lb = blk.get("levels")
        if isinstance(lb, Block):
            for lk, _op, lv in lb:
                if lk is None or not isinstance(lv, Block):
                    continue
                params = []
                pb = lv.get("parameters")
                if isinstance(pb, Block):
                    for p in pb.values():
                        if isinstance(p, str):
                            raw = ck3.loc(f"house_relation_parameter_{p}")
                            params.extend((render_loc(raw) or [prettify(p)]) if raw else [prettify(p)])
                for k in lv.keys():
                    if k not in REL_LEVEL_HANDLED:
                        unhandled[f"relations.level.{k}"] += 1
                name = ck3.loc(f"{key}_level_{lk}")
                desc = ck3.loc(f"{key}_level_{lk}_desc")
                levels.append({
                    "id": lk,
                    "name": ck3.render_text(name) if name else prettify(lk),
                    "desc": ck3.render_text(desc) if desc else None,
                    "opinion": lv.get("opinion", 0),
                    "cohesion": lv.get("cohesion_contribution", 0),
                    "params": params,
                })
        for k in blk.keys():
            if k not in REL_HANDLED and k not in REL_SKIP:
                unhandled[f"relations.{k}"] += 1
        out.append({"id": key, "neutralLevel": blk.get("neutral_level"), "levels": levels})
    return out


# ---------------------------------------------------------------------------
# legitimacy

LEGIT_HANDLED = {"is_valid", "max", "below_expectations_opinion", "level"}
LEGIT_SKIP = {
    "ai_expected_level": "what level the AI expects of a liege — AI plumbing",
}
LEGIT_LEVEL_HANDLED = {"threshold", "modifier", "flag"}
LEGIT_LEVEL_SKIP = {
    "on_level_entered": "situation-catalyst effect (Mandate of Heaven loss)",
    "on_level_entered_desc": "dynamic description for the above effect",
}

DLC_TRIGGER = {"has_tgp_dlc_trigger": "The Great People",
               "has_mpo_dlc_trigger": "Khans of the Steppe",
               "has_ep3_dlc_trigger": "Roads to Power",
               "has_ep4_dlc_trigger": "All Under Heaven"}

TIER_NAMES = {"tier_county": "County", "tier_duchy": "Duchy", "tier_kingdom": "Kingdom",
              "tier_empire": "Empire", "tier_hegemony": "Hegemony"}


def threshold_value(v):
    """base × legitimacy_title_era_value (2–8) -> {base,min,max}; static -> number."""
    n, _rules = ck3.resolve_value(v)
    if n is not None:
        return round(n) if isinstance(n, float) else n
    sv = ck3.script_values().get(v) if isinstance(v, str) else v
    if isinstance(sv, Block):
        items = sv.items()
        if (len(items) == 2 and items[0][0] == "value"
                and items[1] == ("multiply", "legitimacy_title_era_value")):
            base = items[0][1]
            if isinstance(base, (int, float)):
                return {"base": base, "min": base * 2, "max": base * 8}
        # legitimacy_max-style: value = <level> ×1.15 round_to 100
        n2, rules = ck3.resolve_value(sv)
        if n2 is not None:
            return n2
        inner = threshold_value(sv.get("value")) if sv.has("value") else None
        if isinstance(inner, dict) and sv.get("multiply") is not None:
            m, _r = ck3.resolve_value(sv.get("multiply"))
            rt = sv.get("round_to") or 1
            if m is not None:
                return {"base": inner["base"],
                        "min": round(inner["min"] * m / rt) * rt,
                        "max": round(inner["max"] * m / rt) * rt}
    return {"rules": str(v)}


def build_legitimacy():
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "legitimacy"):
        applies = []
        dlc = None

        def describe_cond(k, v):
            if k == "highest_held_title_tier":
                return f"Highest title: {TIER_NAMES.get(v, prettify(str(v)))}"
            if k == "has_title" and isinstance(v, str):
                t = v.removeprefix("title:")
                nm = ck3.loc(t)
                return f"Holds {ck3.render_text(nm) if nm else prettify(t)}"
            if k == "government_has_flag":
                return prettify(str(v).removeprefix("government_"))
            if k in DLC_TRIGGER:
                return f"{DLC_TRIGGER[k]} enabled"
            return None

        iv = blk.get("is_valid")
        if isinstance(iv, Block):
            for k, _op, v in iv:
                if k == "use_general_legitimacy":
                    continue  # opt-out flag for governments with their own type
                if k in DLC_TRIGGER:
                    dlc = DLC_TRIGGER[k]
                    continue
                if k in NEGATORS and isinstance(v, Block):
                    parts = [describe_cond(kk, vv) for kk, _o, vv in v]
                    parts = [p if p else "?" for p in parts]
                    joiner = " and " if k == "NAND" else ", "
                    label = "not all of" if k == "NAND" else "none of"
                    applies.append(f"{label}: {joiner.join(parts)}")
                    continue
                d = describe_cond(k, v)
                if d:
                    applies.append(d)
                else:
                    unhandled[f"legitimacy.is_valid.{k}"] += 1

        levels = []
        for i, lv in enumerate(blk.get_all("level")):
            if not isinstance(lv, Block):
                continue
            flags = []
            for f in lv.get_all("flag"):
                raw = ck3.loc(f)
                flags.extend((render_loc(raw) or [prettify(f)]) if raw else [prettify(f)])
            for k in lv.keys():
                if k not in LEGIT_LEVEL_HANDLED and k not in LEGIT_LEVEL_SKIP:
                    unhandled[f"legitimacy.level.{k}"] += 1
            flavor = ck3.loc(f"default_legitimacy_level_{i}_flavor")
            levels.append({
                "level": i,
                "flavor": ck3.render_text(flavor) if flavor else None,
                "threshold": threshold_value(lv.get("threshold")),
                "modifiers": render_mods(lv.get("modifier")),
                "flags": flags,
            })
        for k in blk.keys():
            if k not in LEGIT_HANDLED and k not in LEGIT_SKIP:
                unhandled[f"legitimacy.{k}"] += 1
        name = ck3.loc(f"{key}_type_name")
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else prettify(key),
            "appliesTo": applies,
            "dlc": dlc,
            "max": threshold_value(blk.get("max")),
            "belowExpectationsOpinion": num_or_rules(blk.get("below_expectations_opinion")),
            "levels": levels,
        })
    return out


# ---------------------------------------------------------------------------
# diarchies

DIARCHY_GROUPS = {
    "00_regencies.txt": ("regencies", "Regencies"),
    "00_co_rulerships.txt": ("co_rulerships", "Co-Rulerships"),
    "00_primeministerships.txt": ("primeministerships", "Prime Ministerships"),
}
DIARCHY_HANDLED = {"mandate", "power_level", "swing_balance", "succession",
                   "liege_modifier", "diarch_modifier", "end_interaction"}
DIARCHY_SKIP = {
    "start": "start trigger — diarchies start via content (always yes in data)",
    "end": "end trigger — content-driven",
    "candidate_score": "AI succession-candidate scoring",
    "aptitude_score": "diarch aptitude scoring (mandate qualifications, AI)",
    "loyalty_score": "diarch loyalty scoring (AI)",
}


def diarchy_modifier(blocks):
    out = []
    for b in blocks:
        if not isinstance(b, Block):
            continue
        out.append({"lines": render_mods(b, skip=("name", "scale")),
                    "scaled": b.has("scale")})
    return out


def build_diarchies():
    types, seen_groups = [], {}
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "diarchies" / "diarchy_types"):
        gid, glabel = DIARCHY_GROUPS.get(path.name, (path.stem, prettify(path.stem)))
        mandates = []
        for m in blk.get_all("mandate"):
            if isinstance(m, str):
                nm = ck3.loc(f"{m}_mandate")
                mandates.append({"id": m, "name": ck3.render_text(nm) if nm else prettify(m)})
        powers = []
        for pl in blk.get_all("power_level"):
            if not isinstance(pl, Block):
                continue
            params = [{"key": p, "label": prettify(
                          p.removeprefix("unlock_").removesuffix("_interaction"))}
                      for p in pl.get_all("parameter") if isinstance(p, str)]
            if not params:
                continue  # hidden_parameter containers — engine bookkeeping
            powers.append({"swing": pl.get("swing", 0), "params": params})
        powers.sort(key=lambda p: p["swing"])
        sb = blk.get("swing_balance")
        swing_n, _r = ck3.resolve_value(sb) if sb is not None else (None, None)
        swing = swing_n if swing_n is not None else (
            {"base": sb.get("value"), "conditional": True} if isinstance(sb, Block) else None)
        for k in blk.keys():
            if k not in DIARCHY_HANDLED and k not in DIARCHY_SKIP:
                unhandled[f"diarchies.{k}"] += 1
        name = ck3.loc(f"{key}_diarchy_type")
        title = ck3.loc(f"{key}_diarch_title")
        ei = blk.get("end_interaction")
        ei_name = ck3.loc(ei) if isinstance(ei, str) else None
        types.append({
            "id": key,
            "name": ck3.render_text(name) if name else prettify(key),
            "title": ck3.render_text(title) if title else None,
            "group": gid,
            "groupLabel": glabel,
            "succession": bool(blk.get("succession", False)),
            "mandates": mandates,
            "swingBalance": swing,
            "powerLevels": powers,
            "liegeModifiers": diarchy_modifier(blk.get_all("liege_modifier")),
            "diarchModifiers": diarchy_modifier(blk.get_all("diarch_modifier")),
            "endInteraction": ck3.render_text(ei_name) if ei_name else None,
        })
    order = {"regencies": 0, "co_rulerships": 1, "primeministerships": 2}
    types.sort(key=lambda t: (order.get(t["group"], 9), t["id"]))
    return types


MANDATE_HANDLED = {"qualification_score"}
MANDATE_SKIP = {"ai_score": "AI mandate-pick weighting"}

SKILLS = {"diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess"}


def parse_qualification(qs):
    """The mandates all follow one idiom: primary skill, ×0.5 secondaries,
    ±flat bonus/malus traits. Anything off-pattern lands in unhandled."""
    primary, secondary, bonus, malus = [], [], [], []

    def walk(b):
        if not isinstance(b, Block):
            return
        for k, _op, v in b:
            if k == "add" and isinstance(v, Block):
                val = v.get("value")
                desc = str(v.get("desc", ""))
                if isinstance(val, str) and val in SKILLS:
                    if v.get("multiply") is not None:
                        secondary.append(val)
                    else:
                        primary.append(val)
                else:
                    walk(v)
            elif k == "if" and isinstance(v, Block):
                lim = v.get("limit")
                trait = lim.get("has_trait") if isinstance(lim, Block) else None
                add = v.get("add")
                amount = add.get("value") if isinstance(add, Block) else add
                if isinstance(trait, str) and isinstance(amount, (int, float)):
                    t = ck3.loc(f"trait_{trait}")
                    nm = ck3.render_text(t) if t else prettify(trait)
                    (bonus if amount > 0 else malus).append(nm)
                else:
                    walk(v)
            elif isinstance(v, Block):
                walk(v)

    walk(qs)
    return primary, secondary, bonus, malus


def build_mandates():
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "diarchies" / "diarchy_mandates"):
        primary, secondary, bonus, malus = parse_qualification(blk.get("qualification_score"))
        for k in blk.keys():
            if k not in MANDATE_HANDLED and k not in MANDATE_SKIP:
                unhandled[f"mandates.{k}"] += 1
        name = ck3.loc(f"{key}_mandate")
        desc = ck3.loc(f"{key}_mandate_desc")
        effects = render_loc(desc) if desc else []
        effects = [e for e in effects if not e.lower().startswith("possible mandate effects")]
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else prettify(key),
            "effects": effects,
            "primary": primary,
            "secondary": secondary,
            "bonusTraits": bonus,
            "malusTraits": malus,
        })
    return out


# ---------------------------------------------------------------------------

def main():
    data = {
        "unity": build_unity(),
        "aspirations": build_aspirations(),
        "relations": build_relations(),
        "legitimacy": build_legitimacy(),
        "diarchies": build_diarchies(),
        "mandates": build_mandates(),
    }
    ck3.write_json("house.json", data)
    n = (len(data["unity"]) + sum(len(g["entries"]) for g in data["aspirations"])
         + len(data["relations"]) + len(data["legitimacy"])
         + len(data["diarchies"]) + len(data["mandates"]))
    print(f"  ({n} entries across {len(data)} sections)")

    if unhandled:
        print("⚠ unhandled house fields (add to HANDLED or SKIP):")
        for k, c in unhandled.most_common():
            print(f"    {k} ×{c}")


if __name__ == "__main__":
    main()
