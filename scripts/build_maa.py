#!/usr/bin/env python3
"""Build src/data/maa.json from common/men_at_arms_types/.

Schema documented by the game itself in _men_at_arms_types.info. Every field
present in the data is either emitted, consciously skipped (SKIP_FIELDS), or
reported as unhandled — audit.py fails on unhandled fields after a patch.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

STATS = ("damage", "toughness", "pursuit", "screen")

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "ai_quality": "AI purchasing weight, not player-facing",
    "illustration": "art selection triggers; icon derivation covers display",
    "fallback_in_hired_troops_if_unlocked": "merc AI preference plumbing",
    "mercenary_fallback": "merc AI preference plumbing",
    "holy_order_fallback": "holy order AI preference plumbing",
    "allowed_in_hired_troops": "hired-troop pool plumbing (uniform yes)",
    "hired_stack_size": "hired-troop pool sizing detail",
    "should_show_when_unavailable": "GUI visibility plumbing",
    "access_through_subject": "subject-access dedup trigger, not player-facing",
}

HANDLED_FIELDS = {
    "type", "icon", "damage", "toughness", "pursuit", "screen", "siege_value",
    "siege_tier", "fights_in_main_phase", "stack", "max", "max_sub_regiments",
    "max_regiments", "buy_cost", "low_maintenance_cost", "high_maintenance_cost",
    "provision_cost", "terrain_bonus", "counters", "can_recruit",
    "special_recruit_only", "winter_bonus", "holding_bonus",
}

# can_recruit trigger keys whose values are entity references worth surfacing.
REQ_KEYS = {
    "has_innovation": "innovation",
    "has_all_innovations": "innovation",
    "has_doctrine": "doctrine",
    "has_doctrine_parameter": "doctrine_parameter",
    "has_government": "government",
    "government_has_flag": "government_flag",
    "has_cultural_parameter": "cultural_parameter",
    "has_cultural_pillar": "cultural_pillar",
    "has_cultural_era_or_later": "cultural_era",
    "has_trait": "trait",
    "has_dynasty_perk": "dynasty_perk",
    "PARAMETER": "cultural_parameter",  # via valid_for_maa_trigger macro
}


def cost_value(v):
    """A cost -> number where static, else a rendered rule structure."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return round(n, 2) if isinstance(n, float) else n
    return {"rules": rules}


def costs_block(blk):
    if blk is None:
        return None
    if isinstance(blk, (int, float, str)):
        return {"gold": cost_value(blk)}
    out = {}
    for k, _op, v in blk:
        if k is not None:
            out[k] = cost_value(v)
    return out


NEGATORS = {"NOT", "NOR", "NAND"}

# Flags/parameters are internal identifiers, not loc keys — prettify them.
_LOC_BY_KIND = {
    "innovation": lambda k: ck3.loc(k),
    "doctrine": lambda k: ck3.loc(k) or ck3.loc(f"{k}_name"),
    "trait": lambda k: ck3.loc(f"trait_{k}"),
    "government": lambda k: ck3.loc(k),
    "cultural_pillar": lambda k: ck3.loc(k),
    "cultural_era": lambda k: ck3.loc(k),
    "dynasty_perk": lambda k: ck3.loc(f"{k}_name"),
    "cultural_parameter": lambda k: ck3.loc(f"culture_parameter_{k}"),
}


def req_name(kind, key):
    """(short label, full detail-or-None). Chips show the label; tooltips the detail."""
    raw = _LOC_BY_KIND.get(kind, lambda k: None)(key)
    detail = ck3.render_text(raw) if raw else None
    if kind == "cultural_parameter":
        # unlock params self-reference the unit ("Can recruit X as Men-at-Arms");
        # the *which tradition* answer arrives via backlinks in phase 1.
        if key.startswith("unlock_maa_") or (detail or "").startswith("Can recruit"):
            return "Cultural tradition", detail
        if key.endswith("_ban"):
            stem = re.sub(r"_(heavy|light)?_?maa_ban$", "", key).replace("_", " ").title()
            return f"{stem} ban", detail
    if detail:
        return detail, None
    label = (key.removeprefix("government_is_").removeprefix("government_")
                .removeprefix("flag_").replace("_", " ").title())
    return label, None


def collect_requirements(trigger, reqs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k in REQ_KEYS and isinstance(v, str):
            name, detail = req_name(REQ_KEYS[k], v)
            reqs.append({"kind": REQ_KEYS[k], "key": v, "negated": negated,
                         "name": name, "detail": detail})
        elif isinstance(v, (Block, Tagged)):
            collect_requirements(v, reqs, negated or (k in NEGATORS))


def main():
    entries = ck3.parse_dir(ck3.COMMON / "men_at_arms_types")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        name = ck3.loc(key)
        flavor = ck3.loc(f"{key}_flavor")

        def bonus_map(field):
            out = {}
            b = blk.get(field)
            if isinstance(b, Block):
                for ctx, _op, bonuses in b:
                    if ctx is not None and isinstance(bonuses, Block):
                        out[ctx] = {k: v for k, _o, v in bonuses if k is not None}
            return out

        terrain = bonus_map("terrain_bonus")
        winter = bonus_map("winter_bonus")
        holding = bonus_map("holding_bonus")

        counters = {}
        cb = blk.get("counters")
        if isinstance(cb, Block):
            for arch, _op, n in cb:
                if arch is not None:
                    counters[arch] = n

        reqs = []
        collect_requirements(blk.get("can_recruit"), reqs)

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        icon = blk.get("icon") or key
        icon = str(icon).removesuffix(".dds")

        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "flavor": ck3.render_text(flavor) if flavor else None,
            "type": blk.get("type"),
            "typeName": ck3.render_text(ck3.loc(blk.get("type"), "") or (blk.get("type") or "").replace("_", " ").title()) or None,
            "stats": {s: blk.get(s, 0) for s in STATS},
            "siegeValue": cost_value(blk.get("siege_value")) if blk.has("siege_value") else None,
            "siegeTier": blk.get("siege_tier"),
            "mainPhase": not blk.get("fights_in_main_phase") is False if blk.has("fights_in_main_phase") else True,
            "stack": blk.get("stack"),
            "maxSubRegiments": blk.get("max_sub_regiments"),
            "maxRegiments": blk.get("max_regiments"),
            "maxSizeBonus": blk.get("max"),
            "buyCost": costs_block(blk.get("buy_cost")),
            "lowMaintenance": costs_block(blk.get("low_maintenance_cost")),
            "highMaintenance": costs_block(blk.get("high_maintenance_cost")),
            "provisionCost": cost_value(blk.get("provision_cost")) if blk.has("provision_cost") else None,
            "terrainBonus": terrain,
            "winterBonus": winter,
            "holdingBonus": holding,
            "counters": counters,
            "requirements": reqs,
            "specialRecruitOnly": bool(blk.get("special_recruit_only", False)),
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: (r["type"] or "", r["id"]))
    ck3.write_json("maa.json", out)

    if unhandled:
        print("⚠ unhandled MAA fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")


if __name__ == "__main__":
    main()
