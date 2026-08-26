#!/usr/bin/env python3
"""Build src/data/court_positions.json from common/court_positions/.

Two record sets: positions (types/) and tasks (tasks/), joined by the task's
court_position_types list. Schema documented by the game in
_court_positions.info and _court_position_tasks.info (note: the tasks .info
says `position_types` but the data uses `court_position_types`).

Salaries/costs are conditional script values (cultural-era multipliers,
treasury routing, obligation hooks) — we surface the game's own base line
(the add tagged desc = COURT_POSITION_SALARY_BREAKDOWN_BASE) and mark the
value as scaling, never a fake single number.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKILLS = ("diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess")
LEVELS = ("terrible", "poor", "average", "good", "excellent")

# GUI list-bullet loc macro that render_text can't resolve; purely decorative.
_BULLET = re.compile(r"EFFECT_LIST_BULLET\s*")


def clean_text(s):
    return _BULLET.sub("", s).strip() if isinstance(s, str) else s

SKIP_FIELDS = {
    "court_position_asset": "GUI animation/background selection",
    "sort_order": "consumed for category banding, not shown as a number",
    "is_shown_character": "candidate-list visibility plumbing (uniform)",
    "valid_character": "candidate eligibility macros (adult courtier etc.), not position facts",
    "revoke_cost": "conditional prestige refund plumbing; not a hiring decision input",
    "received_salary": "employee-side accounting; equals paid salary in all but treasury routing",
    "on_court_position_received": "script effect (title grants etc.)",
    "on_court_position_revoked": "script effect",
    "on_court_position_invalidated": "script effect",
    "on_court_position_vacated": "script effect",
    "search_for_courtier": "event plumbing for the hire-a-courtier flow",
    "ai_position_score": "AI hiring weight",
    "ai_candidate_score": "AI candidate weight",
    "is_powerful_agent": "scheme-agent internals flag",
    "custom_scaling_employer_modifier_description": "loc override for level ranges; custom desc already rendered",
    "is_travel_related": "GUI sorting flag for travel window",
}

HANDLED_FIELDS = {
    "max_available_positions", "minimum_rank", "skill", "opinion",
    "aptitude_level_breakpoints", "aptitude", "is_shown", "valid_position",
    "salary", "base_employer_modifier", "culture_modifier", "faith_modifier",
    "scaling_employer_modifiers", "base_employer_court_modifier",
    "scaling_employer_court_modifiers", "custom_employer_modifier_description",
    "modifier", "custom_employee_modifier_description",
}

TASK_SKIP_FIELDS = {
    "court_position_asset": "GUI asset selection",
    "received_cost": "employee-side accounting mirror of cost",
    "is_shown": "visibility gates (DLC checks consumed for provenance)",
    "is_valid_showing_failures_only": "grey-out validity plumbing",
    "on_start": "script effect; modifiers/desc carry the player-facing summary",
    "on_end": "script effect",
    "on_monthly": "script effect (event scheduling)",
    "on_yearly": "script effect (event scheduling)",
    "ai_will_do": "AI task-picking weight",
}

TASK_HANDLED_FIELDS = {
    "court_position_types", "cost", "employee_modifier", "base_employer_modifier",
    "scaling_employer_modifiers", "base_employer_court_modifier",
    "scaling_employer_court_modifiers",
}

# --------------------------------------------------------------------------
# money: base extraction for scaled salaries/costs

BASE_DESCS = {"COURT_POSITION_SALARY_BREAKDOWN_BASE",
              "COURT_POSITION_TASK_COST_BREAKDOWN_BASE"}


def _base_of(v):
    """First 'base' number in a resolve_value rule structure."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return n
    stack = [rules]
    while stack:
        r = stack.pop(0)
        if isinstance(r, dict):
            if isinstance(r.get("base"), (int, float)):
                return r["base"]
            stack.extend(v for v in r.values() if isinstance(v, (list, dict)))
        elif isinstance(r, list):
            stack.extend(r)
    return None


def _find_base(v, depth=0):
    """The game's own 'base' line: an add/value block tagged with the salary
    or task-cost breakdown desc. Returns its number, or None."""
    if isinstance(v, str):
        v = ck3.script_values().get(v)
    if not isinstance(v, Block) or depth > 8:
        return None
    for k, _op, val in v:
        if k in ("add", "value") and isinstance(val, Block) and val.get("desc") in BASE_DESCS:
            n = _base_of(val.get("value"))
            if n is not None:
                return n
        if k in ("value", "add", "if", "else_if", "else") and isinstance(val, (Block, str)):
            n = _find_base(val, depth + 1)
            if n is not None:
                return n
    return None


def money(v):
    n, _rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": round(n, 2)} if n else None
    base = _find_base(v)
    if base is not None:
        return {"base": round(base, 2), "scales": True}
    return {"scales": True}


def money_block(blk):
    """salary/cost block -> {resource: money}. gold and treasury are the same
    amount routed by has_treasury; merged into gold."""
    if not isinstance(blk, Block):
        return {}
    out = {}
    for k, _op, v in blk:
        if k in (None, "round"):
            continue
        m = money(v)
        if m:
            out[k] = m
    if "treasury" in out:
        out.setdefault("gold", out["treasury"])
        del out["treasury"]
    return out


# --------------------------------------------------------------------------
# modifiers

def rendered_mods(blk):
    """A modifier block -> list of game-phrased lines (+ polarity)."""
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


def scaling_mods(blk):
    """scaling_employer_modifiers -> {level: [lines]} (terrible..excellent)."""
    out = {}
    if isinstance(blk, Block):
        for lvl in LEVELS:
            b = blk.get(lvl)
            if isinstance(b, Block):
                mods = rendered_mods(b)
                if mods:
                    out[lvl] = mods
    return out


# --------------------------------------------------------------------------
# aptitude: skills referenced (shallow), breakpoints

def aptitude_skills(blk, found=None, depth=0):
    if found is None:
        found = []
    if not isinstance(blk, Block) or depth > 8:
        return found
    for k, _op, v in blk:
        if k in ("value", "add", "min", "max", "multiply") and isinstance(v, str) and v in SKILLS:
            if v not in found:
                found.append(v)
        elif isinstance(v, Block):
            aptitude_skills(v, found, depth + 1)
    return found


# --------------------------------------------------------------------------
# gates: valid_position / is_shown -> requirement chips + DLC provenance

NEGATORS = {"NOT", "NOR", "NAND"}
_DLC_TRIGGER = re.compile(r"^has_([a-z]+\d?)(?:_[a-z_]+)?_dlc_trigger$")

TIER_NAMES = {"tier_barony": "Barony", "tier_county": "County", "tier_duchy": "Duchy",
              "tier_kingdom": "Kingdom", "tier_empire": "Empire", "tier_hegemony": "Hegemony"}

# Baseline/plumbing triggers that would repeat on nearly every row.
GATE_IGNORE = {"is_ai", "always", "is_landed_or_landless_administrative",
               "save_temporary_scope_as", "exists", "is_independent_ruler",
               "court_position_employee_shown_trigger",
               # conditional sub-logic (mostly AI-visibility branches) — too
               # deep for shallow requirement chips
               "trigger_if", "trigger_else_if", "trigger_else", "limit"}


def collect_gates(trigger, reqs, dlcs, negated=False, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 6:
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        m = _DLC_TRIGGER.match(k)
        if m:
            dlc = ck3.PREFIX_TO_DLC.get(m.group(1))
            if dlc:
                dlcs.add(dlc)
            continue
        if k == "custom_tooltip" and isinstance(v, Block):
            text = v.get("text")
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                # multi-line tooltips list buildings etc.; the first line is the chip
                line = clean_text(ck3.render_text(raw)).split("\n")[0].rstrip(":… ")
                if line:
                    reqs.append({"name": line, "negated": negated})
            continue
        if k == "highest_held_title_tier" and isinstance(v, str):
            tier = TIER_NAMES.get(v, v)
            reqs.append({"name": f"{tier} tier{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title()
            reqs.append({"name": f"{label} government", "negated": negated})
            continue
        if k == "has_realm_law" and isinstance(v, str):
            raw = ck3.loc(v) or ck3.loc(f"{v}_name")
            reqs.append({"name": ck3.render_text(raw) if raw else v.replace("_", " ").title(),
                         "negated": negated})
            continue
        if k == "has_cultural_parameter" and isinstance(v, str):
            raw = ck3.loc(f"culture_parameter_{v}")
            reqs.append({"name": ck3.render_text(raw) if raw else "Cultural tradition",
                         "negated": negated})
            continue
        if k == "has_cultural_tradition" and isinstance(v, str):
            raw = ck3.loc(f"{v}_name")
            reqs.append({"name": ck3.render_text(raw) if raw else v.replace("_", " ").title(),
                         "negated": negated})
            continue
        if k == "has_trait" and isinstance(v, str):
            raw = ck3.loc(f"trait_{v}")
            if raw:
                reqs.append({"name": ck3.render_text(raw), "negated": negated})
            continue
        if k in ("has_innovation", "has_doctrine", "has_perk", "has_religion") and isinstance(v, str):
            raw = ck3.loc(v) or ck3.loc(f"{v}_name")
            if raw:
                reqs.append({"name": ck3.render_text(raw), "negated": negated})
            continue
        if k == "has_royal_court" and v is True:
            reqs.append({"name": "Royal Court", "negated": negated})
            continue
        if k in GATE_IGNORE:
            continue
        if isinstance(v, (Block, Tagged)):
            collect_gates(v, reqs, dlcs, negated or (k in NEGATORS), depth + 1)


def dedupe(reqs):
    seen, out = set(), []
    for r in reqs:
        key = (r["name"], r["negated"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# --------------------------------------------------------------------------
# categories: the game's own sort-order comment bands in 00_court_positions.txt;
# the DLC files each hold one flavor court and get named for it.

FILE_CATEGORY = {
    "00_admin_court_position.txt": "Administrative",
    "00_celestial_court_positions.txt": "Celestial court",
    "00_mandala_court_positions.txt": "Mandala court",
    "00_mpo_court_positions.txt": "Nomadic court",
    "00_camp_officers.txt": "Camp officers",
}


def category(path, sort_order):
    if path.name in FILE_CATEGORY:
        return FILE_CATEGORY[path.name]
    if isinstance(sort_order, Block):
        n, _ = ck3.resolve_value(sort_order)
        sort_order = n if n is not None else sort_order.get("value")
    if not isinstance(sort_order, (int, float)):
        sort_order = 0
    if sort_order >= 300:
        return "Important positions"
    if sort_order >= 200:
        return "Regular positions"
    if sort_order >= 100:
        return "Kingdom-tier positions"
    return "Special positions"


def entry_dlc(path, blk, gate_dlcs):
    dlc, features = ck3.dlc_tag(path, blk)
    if not dlc and gate_dlcs:
        dlc = sorted(gate_dlcs)[0]
    return dlc, features


# --------------------------------------------------------------------------

def build_positions(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "court_positions" / "types"):
        if isinstance(blk, Tagged):
            continue
        name = ck3.loc(key)
        desc = ck3.loc(f"{key}_desc")

        reqs, gate_dlcs = [], set()
        collect_gates(blk.get("valid_position"), reqs, gate_dlcs)
        collect_gates(blk.get("is_shown"), reqs, gate_dlcs)
        # DLC triggers also hide in the aptitude/salary chains? No — provenance
        # only from gates + has_dlc_feature scan (dlc_tag).
        dlc, features = entry_dlc(path, blk, gate_dlcs)

        opinion_n, _ = ck3.resolve_value(blk.get("opinion"))

        bps = blk.get("aptitude_level_breakpoints")
        breakpoints = [v for v in bps.values() if isinstance(v, (int, float))] if isinstance(bps, Block) else None

        culture_mods = []
        for cm in blk.get_all("culture_modifier") + blk.get_all("faith_modifier"):
            if isinstance(cm, Block):
                param = cm.get("parameter")
                raw = ck3.loc(f"culture_parameter_{param}") if param else None
                culture_mods.append({
                    "parameter": ck3.render_text(raw) if raw else str(param).replace("_", " ").title(),
                    "mods": rendered_mods(cm),
                })

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        cust_er = ck3.loc(blk.get("custom_employer_modifier_description") or "")
        cust_ee = ck3.loc(blk.get("custom_employee_modifier_description") or "")

        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "category": category(path, blk.get("sort_order")),
            "maxPositions": blk.get("max_available_positions"),
            "minimumRank": blk.get("minimum_rank"),
            "skill": blk.get("skill"),
            "aptitudeSkills": aptitude_skills(blk.get("aptitude")),
            "breakpoints": breakpoints,
            "opinion": opinion_n,
            "salary": money_block(blk.get("salary")),
            "scalingModifiers": scaling_mods(blk.get("scaling_employer_modifiers")),
            "scalingCourtModifiers": scaling_mods(blk.get("scaling_employer_court_modifiers")),
            "baseEmployerMods": rendered_mods(blk.get("base_employer_modifier")),
            "baseCourtMods": rendered_mods(blk.get("base_employer_court_modifier")),
            "employeeMods": rendered_mods(blk.get("modifier")),
            "cultureMods": culture_mods,
            "customEmployerDesc": clean_text(ck3.render_text(cust_er)) if cust_er else None,
            "customEmployeeDesc": clean_text(ck3.render_text(cust_ee)) if cust_ee else None,
            "requirements": dedupe(reqs),
            "icon": key,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)
    return out


def build_tasks(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "court_positions" / "tasks"):
        if isinstance(blk, Tagged):
            continue
        name = ck3.loc(key)
        desc = ck3.loc(f"{key}_desc")

        positions = []
        pt = blk.get("court_position_types")
        if isinstance(pt, Block):
            positions = [v for v in pt.values() if isinstance(v, str)]

        reqs, gate_dlcs = [], set()
        collect_gates(blk.get("is_shown"), reqs, gate_dlcs)
        dlc, features = entry_dlc(path, blk, gate_dlcs)

        for k in blk.keys():
            if k not in TASK_HANDLED_FIELDS and k not in TASK_SKIP_FIELDS:
                unhandled[k] += 1

        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "positions": positions,
            "cost": money_block(blk.get("cost")),
            "employeeMods": rendered_mods(blk.get("employee_modifier")),
            "baseEmployerMods": rendered_mods(blk.get("base_employer_modifier")),
            "scalingModifiers": scaling_mods(blk.get("scaling_employer_modifiers")),
            "scalingCourtModifiers": scaling_mods(blk.get("scaling_employer_court_modifiers")),
            "dlc": dlc,
            "sourceFile": path.name,
        }
        out.append(rec)
    return out


def main():
    unhandled_p, unhandled_t = Counter(), Counter()
    positions = build_positions(unhandled_p)
    tasks = build_tasks(unhandled_t)

    positions.sort(key=lambda r: (r["category"], r["id"]))
    tasks.sort(key=lambda r: (r["positions"][0] if r["positions"] else "", r["id"]))
    ck3.write_json("court_positions.json", {"positions": positions, "tasks": tasks})

    for label, c in (("position", unhandled_p), ("task", unhandled_t)):
        if c:
            print(f"⚠ unhandled court {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    missing = [r["id"] for r in positions + tasks if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
