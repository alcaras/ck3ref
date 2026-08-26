#!/usr/bin/env python3
"""Build src/data/schemes.json from common/schemes/.

Three record sets: schemes (scheme_types/), agents (agent_types/), and
countermeasures (scheme_countermeasures/), cross-referenced:

- A scheme's agent slots come from `add_agent_slot` effects in its on_start
  (slots added inside a conditional `if` are flagged). Contract (laamp)
  schemes receive agents through "critical moment" events instead — no
  static slots exist for them and the page says so.
- Countermeasures act on schemes through parameters; which schemes a
  countermeasure affects is derivable from the scheme's base_success_chance
  invoking apply_<class>_scheme_success_chance_adjustments_modifier
  (class: calculated/opportunistic/indirect/political) and base_secrecy
  invoking countermeasure_apply_secrecy_maluses_value. We emit the class on
  the scheme and phrase each countermeasure's parameters with the resolved
  magnitudes from script_values (secrecy −15/−25/−35; success chance
  −50/−100/−150 effective, +10/+15/+25 weak).

Success/secrecy formulas are NOT computed — we render their structure:
base number + the named contributing modifiers one level deep
(honest-rendering rule 4).
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKILLS = ("diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess")

SKIP_FIELDS = {
    "illustration": "event-window art selection; icon derivation covers display",
    "on_phase_completed": "script effect (event scheduling); success_desc carries the outcome",
    "on_hud_click": "GUI event plumbing",
    "on_monthly": "script effect (discovery checks, ongoing events)",
    "on_semiyearly": "AI agent-assignment plumbing",
    "on_invalidated": "script effect (fallback events)",
    "agent_join_chance": "AI willingness-to-join weight",
    "agent_leave_threshold": "AI leave threshold",
    "valid_agent": "per-agent validity macro (uniform standard trigger)",
    "pulse_actions": "flavor-event scheduling (schemes/pulse_actions/ likewise skipped)",
    "hide_target_name": "GUI display flag",
    "spymaster_speed_per_skill_point": "spymaster speed detail; base speed params cover the mechanic",
    "target_spymaster_speed_per_skill_point": "spymaster speed detail (target side)",
    "tier_speed": "title-tier speed detail",
}

HANDLED_FIELDS = {
    "skill", "desc", "success_desc", "discovery_desc", "icon", "category",
    "target_type", "is_secret", "is_basic", "uses_resistance", "use_secrecy",
    "maximum_breaches", "cooldown", "allow", "valid", "on_start",
    "starting_agent_slots", "agent_groups_owner_perspective",
    "agent_groups_target_character_perspective", "odds_prediction",
    "base_success_chance", "base_secrecy", "base_progress_goal",
    "base_maximum_success", "minimum_success", "maximum_secrecy",
    "minimum_secrecy", "speed_per_skill_point", "speed_per_target_skill_point",
    "success_chance_growth_per_skill_point", "phases_per_agent_charge",
    "freeze_scheme_when_traveling", "freeze_scheme_when_traveling_target",
    "cancel_scheme_when_traveling", "cancel_scheme_when_traveling_target",
}

AGENT_HANDLED = {"contribution_type", "valid_agent_for_slot", "contribution"}
AGENT_SKIP = {}

CM_SKIP_FIELDS = {
    "is_valid_showing_failures_only": "uniform home-court validity macro",
    "on_activate": "player-notification effect",
    "ai_will_do": "AI countermeasure-picking weight",
}
CM_HANDLED_FIELDS = {"frame", "is_shown", "owner_modifier", "parameters"}

# Debug/QA entries the game itself never surfaces.
DEBUG_AGENTS = {"agent_hitman", "agent_vampire", "agent_werewolf", "agent_mage",
                "agent_wraith", "agent_changeling"}

NEGATORS = {"NOT", "NOR", "NAND"}

# The five schemes without an explicit category are the classic personal
# schemes (seduce, sway, courting, learn_language, convert_to_witchcraft);
# the game defaults category to personal.
DEFAULT_CATEGORY = "personal"


def pretty(key):
    return str(key).replace("_", " ").strip()


def static(v):
    """resolve_value, rounded when static; None when conditional."""
    n, _rules = ck3.resolve_value(v)
    if isinstance(n, float):
        return round(n, 2)
    return n


# --------------------------------------------------------------------------
# odds / success-chance / secrecy structure (one level deep, never computed)

# Display names for the recurring named script-value components.
FACTOR_NAMES = {
    "hostile_scheme_base_odds_prediction_target_is_char_value": "hostile-scheme base odds",
    "political_scheme_base_odds_prediction_target_is_char_value": "political-scheme base odds",
    "personal_scheme_base_odds_prediction_target_is_char_value": "personal-scheme base odds",
    "agent_groups_owner_perspective_value": "agents available to you",
    "agent_groups_target_character_perspective_value": "agents around the target",
    "secrecy_base_value": "base secrecy (20)",
    "countermeasure_apply_secrecy_maluses_value": "target's countermeasures",
    "secrecy_charting_realm_increase_value": "charting the target's realm",
    "hostile_scheme_base_chance_modifier": "standard hostile-scheme factors",
    "personal_scheme_base_chance_modifier": "standard personal-scheme factors",
    "political_scheme_base_chance_modifier": "standard political-scheme factors",
    "diarch_scheming_within_realm_bonus_modifier": "diarch scheming in liege's realm",
    "house_feud_hostile_scheme_success_modifier": "house feud",
    "apply_calculated_scheme_success_chance_adjustments_modifier": "target's countermeasures (calculated class)",
    "apply_opportunistic_scheme_success_chance_adjustments_modifier": "target's countermeasures (opportunistic class)",
    "apply_indirect_scheme_success_chance_adjustments_modifier": "target's countermeasures (indirect class)",
    "apply_political_scheme_success_chance_adjustments_modifier": "target's countermeasures (political class)",
}

_ODDS_SKILL = re.compile(r"^odds_skill_contribution_(\w+?)_value$")
_ODDS_VARS = re.compile(r"^odds_(?:variables|\w*?)_contribution_(\w+)$")
_VALUE_SUB = re.compile(r"\$VALUE[^$]*\$")


def factor_name(name):
    if name in FACTOR_NAMES:
        return FACTOR_NAMES[name]
    m = _ODDS_SKILL.match(name)
    if m and m.group(1) in SKILLS:
        return f"your {m.group(1).title()}"
    return pretty(re.sub(r"_(value|modifier)$", "", name))


_VALUE_TAIL = re.compile(r"[:\s]*\$VALUE[^$]*\$")
_TECHNICAL = re.compile(r"^(scope:|var:|exists$|NOT$|OR$|AND$|first_valid$|trigger_)")


def modifier_line(blk):
    """One `modifier = { add = X desc = KEY … }` block -> {label, add}.

    The label carries the full display text (the game's own $VALUE$ slot is
    filled with the resolved add where static, stripped where dynamic); `add`
    is kept as a number for polarity coloring.
    """
    add = static(blk.get("add"))
    desc = blk.get("desc")
    label = None
    if isinstance(desc, str):
        raw = ck3.loc(desc) or ck3.loc(desc.lower())
        if raw is not None:
            if add is not None:
                raw = _VALUE_SUB.sub(f"{add:+g}", raw)
                if "$VALUE" not in (ck3.loc(desc) or ""):
                    raw = f"{raw}: {add:+g}"
            else:
                raw = _VALUE_TAIL.sub("", raw)
            label = ck3.render_text(raw)
    if not label:
        # fall back to the first non-technical trigger key in the block
        for k, _op, v in blk:
            if k in (None, "add", "desc", "factor") or _TECHNICAL.match(k):
                continue
            label = pretty(k)
            break
        if label and add is not None:
            label = f"{label}: {add:+g}"
    return {"label": label or "situational", "add": add}


def chance_structure(v):
    """base_success_chance / odds_prediction / base_secrecy -> structure.

    Returns {"base": n|None, "factors": [{"label", "add"|None, "group"?}]}.
    Never collapses to one number.
    """
    if v is None:
        return None
    n = static(v)
    if n is not None:
        return {"base": n, "factors": []}
    if not isinstance(v, Block):
        return {"base": None, "factors": [{"label": str(v), "add": None}]}
    base = None
    factors = []
    for k, _op, val in v:
        if k is None:
            continue
        if k in ("base", "value"):
            base = static(val) if base is None else base
        elif k == "add":
            n = static(val)
            if n is not None:
                factors.append({"label": "flat", "add": n} if base is not None else {"label": "base", "add": n})
            elif isinstance(val, str):
                factors.append({"label": factor_name(val), "add": None})
            elif isinstance(val, Block):
                factors.append(modifier_line(val))
        elif k == "modifier" and isinstance(val, Block):
            factors.append(modifier_line(val))
        elif k == "first_valid" and isinstance(val, Block):
            for kk, _o, vv in val:
                if kk == "modifier" and isinstance(vv, Block):
                    line = modifier_line(vv)
                    line["group"] = "first-match"
                    factors.append(line)
        elif k in ("min", "max"):
            factors.append({"label": f"{k} {static(val)}", "add": None})
        elif k.endswith("_modifier"):
            label = factor_name(k)
            if k == "scheme_type_skill_success_chance_modifier" and isinstance(val, Block):
                skill = val.get("SKILL")
                if isinstance(skill, str):
                    label = f"your {skill.title()} skill"
            factors.append({"label": label, "add": None})
        # anything else (if/every_…): structural — omitted, page notes "abridged"
    # merge duplicate base handling
    if base is None:
        for f in list(factors):
            if f["label"] == "base":
                base = f["add"]
                factors.remove(f)
                break
    seen = set()
    deduped = []
    for f in factors:
        sig = (f["label"], f.get("add"), f.get("group"))
        if sig not in seen:
            seen.add(sig)
            deduped.append(f)
    return {"base": base, "factors": deduped}


# --------------------------------------------------------------------------
# gates (allow / valid): shallow, negation-aware

TIER_NAMES = {"tier_barony": "Barony", "tier_county": "County", "tier_duchy": "Duchy",
              "tier_kingdom": "Kingdom", "tier_empire": "Empire"}

BOOL_GATES = {
    "is_adult": ("Adult", "Not adult"),
    "is_imprisoned": ("Imprisoned", "Not imprisoned"),
    "is_landed": ("Landed", "Unlanded"),
    "is_travelling": ("Travelling", "Not travelling"),
    "is_governor": ("Governor", "Not a governor"),
    "is_house_head": ("House head", "Not house head"),
    "is_incapable": ("Incapable", "Not incapable"),
    "is_playable_character": ("Ruler", "Not a ruler"),
    "is_ruler": ("Ruler", "Not a ruler"),
    "is_at_war": ("At war", "At peace"),
    "is_alive": ("Alive", "Dead"),
}


def tier_gate(key, op, v):
    name = TIER_NAMES.get(v, pretty(str(v)))
    if op == ">":
        return f"Title above {name}"
    if op == ">=":
        return f"{name}-tier title or higher"
    if op == "<":
        return f"Title below {name}"
    return f"{name}-tier title"


def gate_leaf(key, op, v):
    """Recognized leaf trigger -> (label, detail) or None to skip."""
    if key in BOOL_GATES and isinstance(v, bool):
        return (BOOL_GATES[key][0] if v else BOOL_GATES[key][1]), None
    if key == "age":
        return (f"Age {v}+" if op in (">=", ">") else f"Age {op} {v}"), None
    if key == "has_trait" and isinstance(v, str):
        t = ck3.loc(f"trait_{v}")
        return (ck3.render_text(t) if t else pretty(v)), "trait"
    if key == "has_perk" and isinstance(v, str):
        p = ck3.loc(f"{v}_name")
        return (ck3.render_text(p) if p else pretty(v)), "perk"
    if key == "has_focus" and isinstance(v, str):
        f = ck3.loc(f"{v}_name")
        return (ck3.render_text(f) if f else pretty(v)), "focus"
    if key == "government_has_flag" and isinstance(v, str):
        return pretty(str(v).removeprefix("government_is_")).title() + " government", None
    if key == "has_government" and isinstance(v, str):
        g = ck3.loc(v)
        return (ck3.render_text(g) if g else pretty(v)), None
    if key == "government_allows" and isinstance(v, str):
        return f"{pretty(v).title()} government", None
    if key in ("highest_held_title_tier", "tier"):
        return tier_gate(key, op, v), None
    if key == "has_character_flag" and isinstance(v, str):
        return pretty(v).capitalize(), "event flag"
    if key == "has_royal_court" and isinstance(v, bool):
        return ("Has a royal court" if v else "No royal court"), None
    if key == "is_attracted_to_gender_of":
        return "Attracted to the target", None
    if key == "in_diplomatic_range":
        return "Within diplomatic range", None
    if key == "exists" and v == "location":
        return None  # technical liveness check
    return None


CONTAINERS = {"OR", "AND", "NOT", "NOR", "NAND", "trigger_if", "trigger_else",
              "first_valid"}
SCOPES = {"scope:target": "Target", "scope:owner": None, "root": None,
          "house": "House", "top_liege": "Top liege", "liege": "Liege",
          "any_held_title": None}


def collect_gates(trigger, out, stage, negated=False, any_of=False,
                  scope=None, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 4:
        return
    for k, op, v in trigger:
        if k is None:
            continue
        if k in ("custom_description", "custom_tooltip") and isinstance(v, Block):
            text = v.get("text")
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                out.append({"stage": stage, "name": ck3.render_text(raw),
                            "detail": "condition", "negated": negated,
                            "anyOf": any_of, "scope": scope})
            continue
        if k == "any_character_struggle" and isinstance(v, Block):
            phase = None
            for kk, _o, vv in v:
                if kk == "has_struggle_phase_parameter" and isinstance(vv, str):
                    phase = vv
            label = "During a struggle" + (f" ({pretty(phase.removeprefix('unlocks_'))})" if phase else "")
            out.append({"stage": stage, "name": label, "detail": "struggle phase",
                        "negated": negated, "anyOf": any_of, "scope": scope})
            continue
        leaf = gate_leaf(k, op, v) if not isinstance(v, (Block, Tagged)) else None
        if leaf:
            name, detail = leaf
            out.append({"stage": stage, "name": name, "detail": detail,
                        "negated": negated, "anyOf": any_of, "scope": scope})
        elif isinstance(v, (Block, Tagged)):
            if k in CONTAINERS:
                collect_gates(v, out, stage, negated or (k in NEGATORS),
                              any_of or k == "OR", scope, depth + 1)
            elif k in SCOPES:
                collect_gates(v, out, stage, negated, any_of,
                              SCOPES[k] or scope, depth + 1)
            elif k == "limit":
                continue  # trigger_if condition — shallow: skip the condition itself
            # other scope/list blocks: shallow extraction stops here
    return


def dedupe_gates(gates):
    seen = set()
    out = []
    for g in gates:
        key = (g["stage"], g["name"], g["negated"], g["scope"])
        if g["name"] and key not in seen:
            seen.add(key)
            out.append(g)
    return out


# --------------------------------------------------------------------------
# agent slots from on_start

def find_agent_slots(effect, out, conditional=False):
    if isinstance(effect, Tagged):
        effect = effect.block
    if not isinstance(effect, Block):
        return
    for k, _op, v in effect:
        if k == "add_agent_slot" and isinstance(v, str):
            out.append((v, conditional))
        elif isinstance(v, (Block, Tagged)):
            cond = conditional
            if k in ("if", "else_if", "else"):
                limit = v.block.get("limit") if isinstance(v, Tagged) else v.get("limit")
                # the agents_added guard is save-game plumbing, not a real condition
                plumbing = isinstance(limit, Block) and "agents_added" in str(limit)
                cond = conditional or not plumbing
            find_agent_slots(v, out, cond)


# --------------------------------------------------------------------------
# schemes

def cooldown_text(blk):
    if not isinstance(blk, Block):
        return None
    parts = []
    for unit in ("years", "months", "days"):
        n = blk.get(unit)
        if n:
            parts.append(f"{n} {unit if n != 1 else unit[:-1]}")
    return " ".join(parts) or None


def target_sub(raw):
    """Statically-known data functions -> plain referents before render_text."""
    if not isinstance(raw, str):
        return raw
    raw = re.sub(r"\[(?:TARGET_CHARACTER|TARGET|SCHEME\.GetTargetCharacter|scheme_target_character)[^\]]*\]",
                 "the target", raw)
    raw = re.sub(r"\[(?:OWNER|SCHEME\.GetOwner|scheme_owner)[^\]]*\]", "the schemer", raw)
    return raw


def render_desc(key):
    raw = ck3.loc(key) if isinstance(key, str) else None
    return ck3.render_text(target_sub(raw)) if raw else None


def build_schemes(unhandled):
    entries = ck3.parse_dir(ck3.COMMON / "schemes" / "scheme_types")
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[f"scheme:{k}"] += 1
        dlc, features = ck3.dlc_tag(path, blk)

        slots_raw = []
        find_agent_slots(blk.get("on_start"), slots_raw)
        ss = blk.get("starting_agent_slots")
        if isinstance(ss, Block):
            slots_raw += [(v, False) for v in ss.values() if isinstance(v, str)]
        slot_counts = Counter(slots_raw)
        slots = [{"type": t, "count": n, "conditional": cond}
                 for (t, cond), n in sorted(slot_counts.items())]

        gates = []
        collect_gates(blk.get("allow"), gates, "start")
        collect_gates(blk.get("valid"), gates, "ongoing")
        gates = dedupe_gates(gates)

        counter_class = None
        secrecy_countered = False
        bsc = blk.get("base_success_chance")
        if isinstance(bsc, Block):
            for k in bsc.keys():
                m = re.match(r"apply_(\w+)_scheme_success_chance_adjustments_modifier", k or "")
                if m:
                    counter_class = m.group(1)
        bsec = blk.get("base_secrecy")
        if isinstance(bsec, Block) and "countermeasure_apply_secrecy_maluses_value" in str(bsec):
            secrecy_countered = True

        category = blk.get("category")
        skill = blk.get("skill")
        icon = str(blk.get("icon") or key).removesuffix(".dds")
        groups_owner = blk.get("agent_groups_owner_perspective")
        groups_target = blk.get("agent_groups_target_character_perspective")

        rec = {
            "id": key,
            "name": render_desc(key),
            "desc": render_desc(blk.get("desc")),
            "successDesc": render_desc(blk.get("success_desc")),
            "discoveryDesc": render_desc(blk.get("discovery_desc")),
            "category": category or DEFAULT_CATEGORY,
            "categoryDefaulted": category is None,
            "targetType": blk.get("target_type"),
            "skill": skill,
            "skillName": ck3.render_text(ck3.loc(skill, "") or str(skill).title()),
            "isSecret": bool(blk.get("is_secret", False)),
            "conditionalSecrecy": blk.has("use_secrecy"),
            "isBasic": bool(blk.get("is_basic", False)),
            "usesResistance": blk.get("uses_resistance") is not False,
            "phaseLengthDays": static(blk.get("base_progress_goal")),
            "speedPerSkillPoint": static(blk.get("speed_per_skill_point")),
            "speedPerTargetSkillPoint": static(blk.get("speed_per_target_skill_point")),
            "successGrowthPerSkillPoint": static(blk.get("success_chance_growth_per_skill_point")),
            "baseMaxSuccess": static(blk.get("base_maximum_success")),
            "minSuccess": static(blk.get("minimum_success")),
            "maxSecrecy": static(blk.get("maximum_secrecy")),
            "minSecrecy": static(blk.get("minimum_secrecy")),
            "maxBreaches": blk.get("maximum_breaches"),
            "phasesPerAgentCharge": static(blk.get("phases_per_agent_charge")),
            "cooldown": cooldown_text(blk.get("cooldown")),
            "freezeWhenTraveling": bool(blk.get("freeze_scheme_when_traveling", False)),
            "freezeWhenTargetTraveling": bool(blk.get("freeze_scheme_when_traveling_target", False)),
            "agentSlots": slots,
            "agentGroupsOwner": [v for v in groups_owner.values()] if isinstance(groups_owner, Block) else [],
            "agentGroupsTarget": [v for v in groups_target.values()] if isinstance(groups_target, Block) else [],
            "odds": chance_structure(blk.get("odds_prediction")),
            "successChance": chance_structure(bsc),
            "secrecy": chance_structure(bsec),
            "gates": gates,
            "counterClass": counter_class,
            "counterSecrecy": secrecy_countered,
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)
    cat_order = {"hostile": 0, "political": 1, "personal": 2, "contract": 3}
    out.sort(key=lambda r: (cat_order.get(r["category"], 9), r["name"] or r["id"]))
    return out


# --------------------------------------------------------------------------
# agents

_TIER_VALUE = re.compile(r"^agent_trait_(bonus|malus)_t(\d)_value$")


def build_agents(scheme_slots, unhandled):
    entries = ck3.parse_dir(ck3.COMMON / "schemes" / "agent_types")
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged) or key in DEBUG_AGENTS:
            continue
        for k in blk.keys():
            if k not in AGENT_HANDLED and k not in AGENT_SKIP:
                unhandled[f"agent:{k}"] += 1

        skills = []
        traits = []
        other = []
        contrib = blk.get("contribution")
        if isinstance(contrib, Block):
            for k, _op, v in contrib:
                if k == "add" and isinstance(v, Block) and v.get("value") in SKILLS:
                    skills.append({
                        "skill": v.get("value"),
                        "mult": static(v.get("multiply")),
                        "cap": static(v.get("max")),
                    })
                elif k == "if" and isinstance(v, Block):
                    limit = v.get("limit")
                    add = v.get("add")
                    if not isinstance(add, Block):
                        continue
                    tier = 0
                    tv = add.get("value")
                    m = _TIER_VALUE.match(tv) if isinstance(tv, str) else None
                    if m:
                        tier = int(m.group(2)) * (1 if m.group(1) == "bonus" else -1)
                    trait = limit.get("has_trait") if isinstance(limit, Block) else None
                    situational = isinstance(limit, Block) and len(limit.items()) > 1
                    if isinstance(trait, str):
                        t = ck3.loc(f"trait_{trait}")
                        traits.append({"trait": ck3.render_text(t) if t else pretty(trait),
                                       "tier": tier, "situational": situational})
                    else:
                        desc = add.get("desc")
                        raw = ck3.loc(desc) if isinstance(desc, str) else None
                        label = ck3.render_text(raw) if raw else (pretty(desc or "situational"))
                        other.append({"label": label, "tier": tier})

        gate = []
        collect_gates(blk.get("valid_agent_for_slot"), gate, "slot")
        gate = dedupe_gates(gate)

        out.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(key, pretty(key.removeprefix("agent_")).title())),
            "contributionType": blk.get("contribution_type"),
            "skills": skills,
            "traits": traits,
            "other": other,
            "gates": gate,
            "usedBy": sorted(scheme_slots.get(key, [])),
        })
    out.sort(key=lambda r: (not r["usedBy"], r["name"], r["id"]))
    return out


# --------------------------------------------------------------------------
# countermeasures

_CM_TIER = re.compile(r"^(.*)_t(\d)$")
_FRAME = re.compile(r"frame_(\w+)\.dds$")

# parameter -> phrased effect, with resolved magnitudes (see module docstring)
_SECRECY_MAG = {"minor": -15, "medium": -25, "major": -35}
_EFFECTIVE_MAG = {"minor": -50, "medium": -100, "major": -150}
_WEAK_MAG = {"minor": 10, "medium": 15, "major": 25}
_PARAM = re.compile(
    r"^(?:secrecy_vs_(all)_schemes_(bonus)|success_chance_vs_(\w+?)_schemes_(bonus|malus))_(minor|medium|major)$")


def param_effect(p):
    if p == "countermeasure_only_affects_court_holder":
        return {"label": "Protects only the court holder", "add": None, "vs": None}
    m = _PARAM.match(p)
    if not m:
        return None  # state-check parameters (has_*_active) — internal
    all_, sec_bonus, cls, kind, mag = m.groups()
    if sec_bonus:
        return {"label": "Secrecy of all schemes against you",
                "add": _SECRECY_MAG[mag], "vs": "all"}
    add = _EFFECTIVE_MAG[mag] if kind == "bonus" else _WEAK_MAG[mag]
    return {"label": f"Success chance of {cls} schemes against you",
            "add": add, "vs": cls}


def build_countermeasures(unhandled):
    entries = ck3.parse_dir(ck3.COMMON / "schemes" / "scheme_countermeasures")
    families = {}
    for path, key, blk in entries:
        if isinstance(blk, Tagged) or key == "debug_countermeasure":
            continue  # debug_countermeasure: is_shown = never, parameter registry only
        for k in blk.keys():
            if k not in CM_HANDLED_FIELDS and k not in CM_SKIP_FIELDS:
                unhandled[f"countermeasure:{k}"] += 1
        m = _CM_TIER.match(key)
        fam, tier = (m.group(1), int(m.group(2))) if m else (key, 0)

        frame = blk.get("frame") or ""
        fm = _FRAME.search(str(frame))

        gates = []
        shown = blk.get("is_shown")
        if isinstance(shown, Block):
            for k, op, v in shown:
                if k == "government_allows" and isinstance(v, str):
                    gates.append(f"{pretty(v).title()} government")
                # scheme_countermeasure_access_select_best_tier_trigger is the
                # tier-unlock ladder itself — represented by the tier column

        mods = []
        om = blk.get("owner_modifier")
        if isinstance(om, Block):
            for k, _op, v in om:
                if k is not None:
                    mods.append(ck3.render_modifier(k, v))

        effects = []
        params = blk.get("parameters")
        if isinstance(params, Block):
            for k, _op, v in params:
                if k is None:
                    continue
                e = param_effect(k)
                if e:
                    effects.append(e)

        families.setdefault(fam, {"id": fam,
                                  "name": ck3.render_text(ck3.loc(f"scheme_countermeasure_type_{fam}", pretty(fam).title())),
                                  "desc": render_desc(f"scheme_countermeasure_type_{fam}_desc"),
                                  # per-family art ships only as tier icons; t1 stands in
                                  "icon": f"{fam}_t1" if tier else fam,
                                  "tiers": []})
        families[fam]["tiers"].append({
            "id": key,
            "tier": tier,
            "frame": fm.group(1) if fm else None,
            "gates": gates,
            "ownerModifiers": mods,
            "effects": effects,
        })
    out = []
    for fam in families.values():
        fam["tiers"].sort(key=lambda t: t["tier"])
        fam["gates"] = fam["tiers"][0]["gates"]
        out.append(fam)
    out.sort(key=lambda f: f["name"])
    return out


# --------------------------------------------------------------------------

def main():
    unhandled = Counter()
    schemes = build_schemes(unhandled)

    scheme_slots = {}
    for s in schemes:
        for slot in s["agentSlots"]:
            scheme_slots.setdefault(slot["type"], []).append(s["id"])

    agents = build_agents(scheme_slots, unhandled)
    countermeasures = build_countermeasures(unhandled)

    ck3.write_json("schemes.json", {
        "schemes": schemes,
        "agents": agents,
        "countermeasures": countermeasures,
    })
    print(f"  ({len(schemes)} schemes, {len(agents)} agent types, "
          f"{len(countermeasures)} countermeasure families)")

    if unhandled:
        print("⚠ unhandled scheme fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in schemes if not r["name"]]
    missing += [r["id"] for r in agents if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
