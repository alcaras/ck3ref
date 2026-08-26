#!/usr/bin/env python3
"""Build src/data/contracts.json from common/subject_contracts/.

contracts/ holds the obligations (nested obligation_levels), groups/ maps each
government's contract set. Schema in _subject_contracts.info and
_subject_contract_groups.info. tax_slots/ (admin & clan taxation slots) uses a
different schema (per-slot obligations, aptitude script values) and is left to
a later page — see audit SKIP.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

CONTRACT_HANDLED = {"obligation_levels", "display_mode", "icon", "is_shown",
                    "defaults_to_highest_valid_level"}
CONTRACT_SKIP = {
    "can_be_changed": "change-blocker trigger shown only in the negotiate UI",
    "uses_opinion_of_liege": "daily-update perf toggle for script math scopes",
    "joins_suzerain_wars": "documented but unused in current data (war participation is its own contract)",
}

LEVEL_HANDLED = {
    "tax", "levies", "herd", "barter_goods", "prestige", "piety",
    "min_tax", "min_levies", "min_herd", "min_barter_goods",
    "tax_factor", "levies_factor", "herd_factor",
    "subject_opinion", "score", "flag", "default", "parent",
    "liege_modifier", "subject_modifier", "enable_title_maa",
    "enable_character_maa", "appointment_trait_flag", "is_shown", "is_valid",
}
LEVEL_SKIP = {
    "position": "negotiate-UI tree layout coordinate",
    "icon": "negotiate-UI icon path; page renders names",
    "gui_tags": "GUI size/color tags",
    "color": "GUI tint",
    "ai_liege_desire": "AI negotiation weighting",
    "ai_subject_desire": "AI negotiation weighting",
    "contribution_desc": "dynamic tooltip breakdown text",
    "tax_contribution_postfix": "tooltip breakdown text",
    "levies_contribution_postfix": "tooltip breakdown text",
    "herd_contribution_postfix": "tooltip breakdown text",
    "unclamped_contribution_label": "tooltip breakdown label",
    "min_contribution_label": "tooltip breakdown label",
}

GROUP_HANDLED = {"contracts", "is_tributary", "tributary_heir_succession",
                 "suzerain_heir_succession", "admin_province_contract"}
GROUP_SKIP = {
    "modify_contract_layout": "negotiate-UI layout key",
    "suzerain_line_type": "map line art",
    "tributary_line_type": "map line art",
    "should_show_as_suzerain_realm_name": "map label plumbing",
    "should_show_as_suzerain_realm_color": "map color plumbing",
    "tributary_can_break_free": "situational trigger (war/variable state)",
    "is_valid_tributary_contract": "suzerain-eligibility trigger (hegemony gates)",
}

SHARE_KEYS = ("tax", "levies", "herd", "barter_goods", "prestige", "piety")


def prettify(key):
    return str(key).replace("_", " ").strip().title()


def loc_text(*keys):
    for k in keys:
        if not k:
            continue
        raw = ck3.loc(k)
        if raw:
            # contract names use non-E concept format codes ([taxes|U]);
            # normalize so the concept resolver can name them
            raw = re.sub(r"\|[A-Za-z]{1,3}\]", "|E]", raw)
            return ck3.render_text(raw)
    return None


def share_value(v):
    """A contribution share -> {value} if static, {varies, rules} otherwise."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": round(n, 4), "varies": False}
    return {"value": None, "varies": True, "rules": rules}


def rendered_modifiers(b):
    out = []
    if isinstance(b, Block):
        for k, _op, v in b:
            if k is not None:
                out.append({"key": k, "text": ck3.render_modifier(k, v),
                            "polarity": ck3.modifier_polarity(k, v)})
    return out


def main():
    contracts_dir = ck3.COMMON / "subject_contracts" / "contracts"
    groups_dir = ck3.COMMON / "subject_contracts" / "groups"
    unhandled_contract = Counter()
    unhandled_level = Counter()
    unhandled_group = Counter()

    contracts = {}
    level_count = 0
    for path, ckey, cblk in ck3.parse_dir(contracts_dir):
        if not isinstance(cblk, Block):
            continue
        dlc, _features = ck3.dlc_tag(path, cblk)
        levels = []
        ob = cblk.get("obligation_levels")
        if isinstance(ob, Block):
            for lkey, _op, lblk in ob:
                if lkey is None or not isinstance(lblk, Block):
                    continue
                level_count += 1
                shares = {}
                for s in SHARE_KEYS:
                    if lblk.has(s):
                        shares[s] = share_value(lblk.get(s))
                mins = {}
                for s in SHARE_KEYS:
                    if lblk.has(f"min_{s}"):
                        mins[s] = share_value(lblk.get(f"min_{s}"))
                factors = {}
                for s in ("tax", "levies", "herd"):
                    f = f"{s}_factor"
                    if lblk.has(f):
                        factors[s] = share_value(lblk.get(f))

                for k in lblk.keys():
                    if k not in LEVEL_HANDLED and k not in LEVEL_SKIP:
                        unhandled_level[k] += 1

                levels.append({
                    "id": lkey,
                    "name": loc_text(lkey, f"{lkey}_name") or prettify(lkey),
                    "shortName": loc_text(f"{lkey}_short"),
                    "isDefault": bool(lblk.get("default", False)),
                    "parent": lblk.get("parent"),
                    "shares": shares,
                    "minimums": mins,
                    "factors": factors,
                    "subjectOpinion": lblk.get("subject_opinion"),
                    "score": lblk.get("score"),
                    "flags": [v for k, _o, v in lblk if k == "flag" and isinstance(v, str)],
                    "subjectModifiers": rendered_modifiers(lblk.get("subject_modifier")),
                    "liegeModifiers": rendered_modifiers(lblk.get("liege_modifier")),
                    "enableTitleMaa": lblk.get("enable_title_maa") if lblk.has("enable_title_maa") else None,
                    "enableCharacterMaa": lblk.get("enable_character_maa") if lblk.has("enable_character_maa") else None,
                    "appointmentTraitFlag": lblk.get("appointment_trait_flag"),
                })

        for k in cblk.keys():
            if k not in CONTRACT_HANDLED and k not in CONTRACT_SKIP:
                unhandled_contract[k] += 1

        contracts[ckey] = {
            "id": ckey,
            "name": loc_text(ckey, f"{ckey}_name") or prettify(ckey),
            "displayMode": cblk.get("display_mode", "radiobutton"),
            "defaultsToHighest": bool(cblk.get("defaults_to_highest_valid_level", False)),
            "levels": levels,
            "groups": [],
            "dlc": dlc,
            "sourceFile": path.name,
        }

    groups = []
    for path, gkey, gblk in ck3.parse_dir(groups_dir):
        if not isinstance(gblk, Block):
            continue
        member_ids = []
        cb = gblk.get("contracts")
        if isinstance(cb, Block):
            member_ids = [v for v in cb.values() if isinstance(v, str)]
        for cid in member_ids:
            if cid in contracts and gkey not in contracts[cid]["groups"]:
                contracts[cid]["groups"].append(gkey)

        for k in gblk.keys():
            if k not in GROUP_HANDLED and k not in GROUP_SKIP:
                unhandled_group[k] += 1

        groups.append({
            "id": gkey,
            "name": loc_text(gkey, f"{gkey}_name") or prettify(gkey),
            "isTributary": bool(gblk.get("is_tributary", False)),
            "heirSuccession": {
                "suzerain": bool(gblk.get("suzerain_heir_succession", True)),
                "tributary": bool(gblk.get("tributary_heir_succession", False)),
            } if gblk.get("is_tributary") else None,
            "adminProvinceContract": gblk.get("admin_province_contract"),
            "contracts": member_ids,
        })

    orphans = [c for c in contracts.values() if not c["groups"]]
    ck3.write_json("contracts.json", {"groups": groups,
                                      "contracts": sorted(contracts.values(), key=lambda c: c["id"])})
    print(f"  ({len(contracts)} contracts, {level_count} obligation levels, {len(groups)} groups)")
    if orphans:
        print(f"⚠ contracts in no group (rendered under 'Other'): {[c['id'] for c in orphans]}")

    for label, ctr, hint in (("contract", unhandled_contract, "CONTRACT"),
                             ("level", unhandled_level, "LEVEL"),
                             ("group", unhandled_group, "GROUP")):
        if ctr:
            print(f"⚠ unhandled {label} fields (add to {hint}_HANDLED or {hint}_SKIP):")
            for k, n in ctr.most_common():
                print(f"    {k} ×{n}")

    missing = [c["id"] for c in contracts.values() if not c["name"]]
    if missing:
        print(f"⚠ contracts without names: {missing[:10]}")


if __name__ == "__main__":
    main()
