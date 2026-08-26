#!/usr/bin/env python3
"""Build src/data/task_contracts.json from common/task_contracts/.

Schema documented by the game in _task_contracts.info: the adventurer /
governor job board. Name, description and request text all follow the default
loc conventions (<key>_contract / <key>_desc / <key>_request). Contract
groups have NO localization anywhere in the game files — the game only uses
them for spawn pooling — so display labels are hand-maintained here.

Employer/location criteria are extracted shallowly from valid_to_create +
valid_to_accept (negation-aware; scripted-trigger macros get hand labels and
are never recursed into — their argument blocks are macro args, not
triggers). Rewards render the game's own per-reward tooltip loc
(task_contract_reward_effect_<name>_desc) plus any currency amounts we can
resolve from the disbursal effects; scaling values surface their game-marked
base (the court-salary desc-tag convention) or an honest 'scaled' marker.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "weight": "spawn-pool weighting for populate_task_contracts_for_area, AI-facing",
    "on_create": "scripted setup effects (variables, scheme prep)",
    "on_accepted": "scripted flow effects (events, schemes, travel plans)",
    "on_completed": "scripted flow effects; rewards carry the player-facing outcome",
    "on_invalidated": "scripted cleanup effects and interface messages",
}

HANDLED_FIELDS = {
    "group", "icon", "travel", "is_criminal", "use_diplomatic_range",
    "valid_to_create", "valid_to_accept", "valid_to_continue", "valid_to_keep",
    "task_contract_reward",
}

# Contract groups have no loc — hand labels (game terms where they exist:
# 'Governance' from task_contract_governance_desc_title, adventurer groups
# named for the skill they exercise per the data files' own comments).
GROUP_LABELS = {
    "laamp_contracts_diplomacy_group": "Diplomacy",
    "laamp_contracts_martial_group": "Martial",
    "laamp_contracts_stewardship_group": "Stewardship",
    "laamp_contracts_intrigue_group": "Intrigue",
    "laamp_contracts_learning_group": "Learning",
    "laamp_contracts_hunting_group": "Hunting",
    "laamp_contracts_justicar_group": "Justicar",
    "laamp_contracts_hireling_group": "Hireling",
    "laamp_contracts_criminal_group": "Criminal",
    "laamp_contracts_transport_group": "Transport",
    "laamp_contracts_war_group": "War",
    "laamp_contracts_noticeboard_group": "Noticeboard",
    "laamp_contracts_legitimist_group": "Legitimist",
    "admin_governance_group": "Governance",
    "mandala_realm_group": "Mandala Realm",
    "nomadic_settling_group": "Nomadic Settling",
}

# Whole-file provenance where filename prefixes don't resolve: admin
# (governor) contracts shipped with Roads to Power's administrative
# government; nomadic migration contracts with Khans of the Steppe's nomads.
# laamp_* and tgp_* files resolve via ck3.PREFIX_TO_DLC.
FILE_DLC = {
    "admin_contracts.txt": "Roads to Power",
    "nomads_migration_contracts.txt": "Khans of the Steppe",
}

# --- scaling money ---------------------------------------------------------

BASE_DESCS = {"BASE_VALUE"}


def _base_of(v):
    """Leading 'base' number of a rule structure; follows only base chains."""
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
    """{'value': n} | {'base': n, 'scales': True} | {'scales': True}."""
    n, _rules = ck3.resolve_value(v)
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
        return {"base": round(b, 2) if isinstance(b, float) else b, "scales": True}
    return {"scales": True}


# --- criteria (shallow, negation-aware) ------------------------------------

NEGATORS = {"NOT", "NOR", "NAND"}

# Scripted triggers used by contract validity, with hand labels (bodies
# verified in scripted_triggers/). None → consciously skipped plumbing.
TRIGGER_LABELS = {
    "valid_laamp_basic_trigger": ("government", "Landless adventurer",
                                  "you lead an adventurer camp; the employer is within rank/prestige reach or a contact"),
    "council_task_contract_valid_employer_trigger": ("government", "Landless adventurer",
                                                     "hired into the employer's council pool"),
    "valid_governor_contract_trigger": ("government", "Administrative government",
                                        "you govern under an administrative (or celestial) realm"),
    "mandala_task_contract_valid_to_create_trigger": ("government", "Mandala government", None),
    "employer_has_treasury_to_offer_job_trigger": ("employer", "Employer can pay", "employer holds 50+ gold (or barter goods)"),
    "rule_out_dramatic_laamp_employers_trigger": ("employer", "Employer below empire rank", "and not a head of faith"),
    "laamp_task_contract_employer_not_antisocial_trigger": ("employer", "Employer not shy, paranoid or cynical", None),
    "laamp_task_contract_employer_would_resort_to_violence_trigger": ("employer", "Employer not compassionate", None),
    "laamp_task_contract_employer_would_resort_to_deceit_trigger": ("employer", "Employer not honest", None),
    "laamp_task_contract_employer_would_chase_money_trigger": ("employer", "Employer covets money", None),
    "settlement_issue_valid_to_create_default_trigger": ("location", "Held county below 90 control", "and at least one knight"),
    "valid_laamp_basic_accept_only_trigger": None,   # accept-time double-booking plumbing
    "valid_laamp_sensible_start_trigger": None,      # employer-availability plumbing
    "lock_contracts_from_spawning_in_sahara_trigger": ("location", "Not deep Sahara", "unless Saharan Nomads tradition"),
}

# plumbing triggers with no reference value
SKIP_TRIGGER_KEYS = {
    "is_available", "is_available_quick", "is_ai", "always", "exists",
    "in_diplomatic_range", "save_temporary_scope_as", "is_alive",
}

SCOPE_HINTS = {
    "scope:employer": "employer", "task_contract_employer": "employer",
    "employer": "employer", "task_contract_taker": None, "root": None,
}

RECURSE = {"OR", "AND", "trigger_if", "trigger_else_if", "trigger_else",
           "limit", "custom_description", "top_liege", "liege", "house",
           "faith", "culture", "location", "capital_county"}

_scripted: dict | None = None


def scripted_triggers():
    global _scripted
    if _scripted is None:
        _scripted = {}
        for _p, key, blk in ck3.parse_dir(ck3.COMMON / "scripted_triggers"):
            if isinstance(blk, Block):
                _scripted[key] = blk
    return _scripted


def add_req(reqs, kind, key, name, negated, detail=None):
    reqs.append({"kind": kind, "key": key, "negated": negated,
                 "name": name, "detail": detail})


def _pfx(scope):
    return "Employer: " if scope == "employer" else ""


TIER_NAMES = {"tier_barony": "barony", "tier_county": "county",
              "tier_duchy": "duchy", "tier_kingdom": "kingdom",
              "tier_empire": "empire"}


def collect_criteria(trigger, reqs, negated=False, scope=None):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k is None or k in SKIP_TRIGGER_KEYS:
            continue
        base_key = k.split(".")[-1]
        if k in NEGATORS:
            collect_criteria(v, reqs, not negated, scope)
        elif k in TRIGGER_LABELS or base_key in TRIGGER_LABELS:
            lab = TRIGGER_LABELS.get(k) or TRIGGER_LABELS.get(base_key)
            if lab is not None:
                kind, name, detail = lab
                add_req(reqs, kind, k, name, negated, detail)
            # never recurse: argument blocks are macro args, not triggers
        elif k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title()
            add_req(reqs, "government", v, f"{_pfx(scope)}{label} government", negated)
        elif k == "government_allows" and isinstance(v, str):
            add_req(reqs, "government", v, f"{_pfx(scope)}{v.replace('_', ' ').title()} government", negated)
        elif k == "has_trait" and isinstance(v, str):
            raw = ck3.loc(f"trait_{v}")
            add_req(reqs, "trait", v,
                    f"{_pfx(scope)}{ck3.render_text(raw) if raw else v.replace('_', ' ').title()} trait", negated)
        elif base_key == "highest_held_title_tier":
            tier = TIER_NAMES.get(str(v), str(v))
            add_req(reqs, "employer" if scope == "employer" or "." in k else "character",
                    k, f"{_pfx(scope) or 'Employer: '}rank {op} {tier}", negated)
        elif k == "num_taken_task_contracts":
            add_req(reqs, "condition", k, "No other contract taken", negated)
        elif k == "is_landed" and isinstance(v, bool):
            add_req(reqs, "employer" if scope == "employer" else "character", k,
                    f"{_pfx(scope)}Landed", negated if v else not negated)
        elif k == "prestige_level":
            add_req(reqs, "character", k, f"{_pfx(scope)}Prestige level {op} {v}", negated)
        elif k == "legitimacy_level":
            add_req(reqs, "character", k, f"{_pfx(scope)}Legitimacy level {op} {v}", negated)
        elif k == "custom_tooltip" and isinstance(v, Block):
            # UNMET-state phrasing — label as a condition, never a positive
            # requirement (see CLAUDE.md)
            t = v.get("text")
            raw = ck3.loc(t) if isinstance(t, str) else None
            if raw:
                add_req(reqs, "condition", str(t), ck3.render_text(raw), negated)
            else:
                collect_criteria(v, reqs, negated, scope)
        elif k in SCOPE_HINTS and isinstance(v, (Block, Tagged)):
            collect_criteria(v, reqs, negated, SCOPE_HINTS[k] or scope)
        elif k in RECURSE and isinstance(v, (Block, Tagged)):
            collect_criteria(v, reqs, negated, scope)
        elif isinstance(v, (Block, Tagged)) and k in scripted_triggers():
            # unknown scripted-trigger macro invocation: label it, don't recurse
            label = k.removesuffix("_trigger").replace("_", " ")
            add_req(reqs, "trigger", k, label.capitalize(), negated,
                    f"scripted trigger {k}")
        elif isinstance(v, bool) and k in scripted_triggers():
            label = k.removesuffix("_trigger").replace("_", " ")
            add_req(reqs, "trigger", k, label.capitalize(),
                    negated if v else not negated, f"scripted trigger {k}")
        # anything else (any_* iterators, variables, artifact checks…):
        # shallow extraction consciously ignores it


# --- rewards ---------------------------------------------------------------

# uppercase macro args and direct effects -> reward currency slots
MACRO_CURRENCY = {"GOLD": "gold", "PRESTIGE": "prestige", "PIETY": "piety",
                  "PROVISIONS": "provisions", "OPINION": "employerOpinion"}
EFFECT_CURRENCY = {
    "add_gold": "gold", "add_prestige": "prestige", "add_piety": "piety",
    "change_influence": "influence", "change_merit": "merit",
    "add_dread": "dread", "add_stress": "stress",
    "change_county_control": "control",
}
LIFESTYLE_XP = {"add_diplomacy_lifestyle_xp", "add_martial_lifestyle_xp",
                "add_stewardship_lifestyle_xp", "add_intrigue_lifestyle_xp",
                "add_learning_lifestyle_xp"}


def _amount_value(v):
    """Effect amounts often wrap the number in { value = X … }."""
    if isinstance(v, Block) and v.has("value"):
        m = money(Block([(k, o, x) for k, o, x in v if k != "desc"]))
    else:
        m = money(v)
    return m


def scan_reward_effect(b, amounts, depth=0):
    if isinstance(b, Tagged):
        b = b.block
    if not isinstance(b, Block) or depth > 12:
        return
    for k, _op, v in b:
        if k is None:
            continue
        cur = MACRO_CURRENCY.get(k) or EFFECT_CURRENCY.get(k)
        if k in LIFESTYLE_XP:
            cur = "lifestyleXp"
        if cur and cur not in amounts:
            if isinstance(v, str) and v.startswith(("scope:", "flag:", "var:")):
                amounts[cur] = {"scales": True}
            else:
                m = _amount_value(v)
                if m.get("value") != 0:
                    amounts[cur] = m
        elif k == "XP_MIN" and "traitXp" not in amounts:
            amounts["traitXp"] = {"min": money(v)}
        elif k == "XP_MAX" and isinstance(amounts.get("traitXp"), dict):
            amounts["traitXp"]["max"] = money(v)
        elif k == "TRACK" and isinstance(v, str) and isinstance(amounts.get("traitXp"), dict):
            raw = ck3.loc(f"trait_{v}")
            amounts["traitXp"]["track"] = ck3.render_text(raw) if raw else v.replace("_", " ")
        elif k == "CONTACT" and v is True:
            amounts.setdefault("contact", True)
        elif k == "CONTACT_HOOK" and v is True:
            amounts.setdefault("contactHook", True)
        if isinstance(v, (Block, Tagged)):
            scan_reward_effect(v, amounts, depth + 1)


def rewards(blk):
    out = []
    if not isinstance(blk, Block):
        return out
    for name, _op, rb in blk:
        if name is None or not isinstance(rb, Block):
            continue
        raw = ck3.loc(f"task_contract_reward_effect_{name}_desc")
        amounts = {}
        scan_reward_effect(rb.get("effect"), amounts)
        label = ck3.render_text(raw) if raw else name.replace("_", " ").title()
        out.append({
            "id": name,
            "label": label.rstrip(":").strip(),
            "positive": rb.get("positive", True) is not False,
            "visible": rb.get("visible", True) is not False,
            "amounts": amounts,
        })
    return out


# --- main ------------------------------------------------------------------

GROUP_ORDER = [
    "laamp_contracts_diplomacy_group", "laamp_contracts_martial_group",
    "laamp_contracts_stewardship_group", "laamp_contracts_intrigue_group",
    "laamp_contracts_learning_group", "laamp_contracts_hunting_group",
    "laamp_contracts_justicar_group", "laamp_contracts_hireling_group",
    "laamp_contracts_war_group", "laamp_contracts_transport_group",
    "laamp_contracts_criminal_group", "laamp_contracts_noticeboard_group",
    "laamp_contracts_legitimist_group", "admin_governance_group",
    "mandala_realm_group", "nomadic_settling_group",
]


def rel_icon(path):
    if not isinstance(path, str):
        return None
    return path.lstrip("/").removeprefix("gfx/interface/icons/").removesuffix(".dds")


def main():
    entries = ck3.parse_dir(ck3.COMMON / "task_contracts")
    unhandled = Counter()
    unknown_groups = set()
    excluded = []
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        vc = blk.get("valid_to_create")
        if isinstance(vc, Block) and vc.get("always") is False:
            # disabled/cut content: can never spawn, and has no name loc
            excluded.append(key)
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        if dlc is None:
            dlc = FILE_DLC.get(path.name)

        name = ck3.loc(f"{key}_contract")
        desc = ck3.loc(f"{key}_desc")
        request = ck3.loc(f"{key}_request")

        group = blk.get("group")
        if group not in GROUP_LABELS:
            unknown_groups.add(group)

        criteria = []
        collect_criteria(blk.get("valid_to_create"), criteria)
        collect_criteria(blk.get("valid_to_accept"), criteria)
        seen, deduped = set(), []
        for r in criteria:
            sig = (r["kind"], r["name"], r["negated"])
            if sig not in seen:
                seen.add(sig)
                deduped.append(r)

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "request": ck3.render_text(request) if request else None,
            "group": group,
            "groupName": GROUP_LABELS.get(group, str(group).replace("_", " ").title()),
            "travel": bool(blk.get("travel", False)),
            "isCriminal": bool(blk.get("is_criminal", False)),
            "useDiplomaticRange": bool(blk.get("use_diplomatic_range", False)),
            "criteria": deduped,
            "rewards": rewards(blk.get("task_contract_reward")),
            "icon": rel_icon(blk.get("icon")),
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    out.sort(key=lambda r: (order.get(r["group"], 99), r["name"] or r["id"]))
    ck3.write_json("task_contracts.json", out)

    ngroups = len({r['group'] for r in out})
    print(f"  {ngroups} groups; {sum(len(r['rewards']) for r in out)} reward entries")
    if excluded:
        print(f"  excluded {len(excluded)} disabled contracts (valid_to_create: always = no): {excluded}")
    if unknown_groups:
        print(f"⚠ groups without a hand label (add to GROUP_LABELS): {sorted(unknown_groups)}")
    if unhandled:
        print("⚠ unhandled task_contract fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
