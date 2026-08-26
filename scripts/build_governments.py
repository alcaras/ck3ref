#!/usr/bin/env python3
"""Build src/data/governments.json from common/governments/.

Schema documented in _governments.info. Every field present in the data is
emitted, consciously skipped (SKIP_FIELDS), or reported unhandled.
"""

import colorsys
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "ai": "AI behaviour toggles, not player-facing",
    "ai_ruler_desired_kingdom_titles": "AI title-retention tuning",
    "ai_ruler_desired_empire_titles": "AI title-retention tuning",
    "ai_can_reassign_council_positions": "AI council plumbing",
    "realm_mask_offset": "map-render geometry",
    "realm_mask_scale": "map-render geometry",
    "opinion_of_liege": "conditional opinion script (piety/alliance ladders); not statically resolvable",
    "opinion_of_liege_desc": "dynamic description for the above",
    "opinion_of_suzerain": "conditional opinion script; not statically resolvable",
    "opinion_of_suzerain_desc": "dynamic description for the above",
    "generated_character_template": "character-generation plumbing",
    "can_move_realm_capital": "situational trigger (Japan regent edge case)",
    "house_unity": "house-unity config key; house mechanics page lands later",
    "tax_slot_type": "admin/clan taxation config; tax_slots page lands later",
    "can_get_government": "auto-assignment trigger; DLC gate extracted into dlc field",
}

HANDLED_FIELDS = {
    "government_rules", "royal_court", "blocked_subject_courts", "fallback",
    "primary_holding", "valid_holdings", "required_county_holdings",
    "primary_heritages", "preferred_religions", "vassal_contract_group",
    "domicile_type", "main_administrative_tier", "min_appointment_tier",
    "minimum_provincial_maa_tier", "administrative_title_maa_setup",
    "title_maa_setup", "character_modifier", "top_liege_character_modifier",
    "flags", "mechanic_type", "is_mechanic_type_default", "color",
    "supply_limit_mult_for_others", "prestige_opinion_override",
    "court_generate_commanders", "court_generate_spouses", "max_dread",
    "currency_levels_cap", "compatible_government_type_succession",
}

# Scripted triggers named has_<prefix>_dlc_trigger gate governments on DLC;
# the prefixes map through ck3.PREFIX_TO_DLC (tgp, mpo, ep3, ...).
_DLC_TRIGGER = re.compile(r"^has_([a-z0-9]+)_dlc_trigger$")


def scan_dlc_triggers(block, found):
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block):
        return
    for k, _op, v in block:
        if isinstance(k, str):
            m = _DLC_TRIGGER.match(k)
            if m and m.group(1) in ck3.PREFIX_TO_DLC:
                found.add(ck3.PREFIX_TO_DLC[m.group(1)])
        if isinstance(v, (Block, Tagged)):
            scan_dlc_triggers(v, found)


def color_hex(v):
    """color = hsv{...} / rgb{...} / { r g b } -> #rrggbb."""
    if isinstance(v, Tagged):
        vals = [x for x in v.block.values() if isinstance(x, (int, float))]
        if v.tag == "hsv" and len(vals) == 3:
            r, g, b = colorsys.hsv_to_rgb(*vals)
            return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        v = v.block if v.tag == "rgb" else None
        if v is None:
            return None
    if isinstance(v, Block):
        vals = [x for x in v.values() if isinstance(x, (int, float))]
        if len(vals) == 3:
            return "#%02x%02x%02x" % tuple(min(255, max(0, round(x))) for x in vals)
    return None


def rendered_modifiers(blk, field):
    out = []
    b = blk.get(field)
    if isinstance(b, Block):
        for k, _op, v in b:
            if k is None:
                continue
            out.append({"key": k, "text": ck3.render_modifier(k, v),
                        "polarity": ck3.modifier_polarity(k, v)})
    return out


def name_list(values, loc_fn):
    out = []
    for v in values:
        if isinstance(v, str):
            raw = loc_fn(v)
            out.append(ck3.render_text(raw) if raw else v.replace("_", " ").title())
    return out


def holding_name(key):
    raw = ck3.loc(key)
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


def main():
    entries = ck3.parse_dir(ck3.COMMON / "governments")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        if dlc is None:
            triggered = set()
            scan_dlc_triggers(blk.get("can_get_government"), triggered)
            # a rule that the schema doc says requires a dlc_flag
            rules_blk = blk.get("government_rules")
            if not triggered and isinstance(rules_blk, Block):
                if rules_blk.get("administrative") or rules_blk.get("landless_playable"):
                    triggered.add("Roads to Power")
            dlc = sorted(triggered)[0] if triggered else None

        rules = {}
        rb = blk.get("government_rules")
        if isinstance(rb, Block):
            for k, _op, v in rb:
                if k is not None and isinstance(v, bool):
                    rules[k] = v

        flags = []
        fb = blk.get("flags")
        if isinstance(fb, Block):
            for f in fb.values():
                if isinstance(f, str):
                    raw = ck3.loc(f)
                    flags.append({"key": f, "name": ck3.render_text(raw) if raw else None})

        valid = [v for v in (blk.get("valid_holdings").values() if isinstance(blk.get("valid_holdings"), Block) else [])]
        required = [v for v in (blk.get("required_county_holdings").values() if isinstance(blk.get("required_county_holdings"), Block) else [])]

        caps = {}
        cb = blk.get("currency_levels_cap")
        if isinstance(cb, Block):
            caps = {k: v for k, _o, v in cb if k is not None}

        prestige_override = None
        po = blk.get("prestige_opinion_override")
        if isinstance(po, Block):
            prestige_override = [v for v in po.values() if isinstance(v, (int, float))]

        contract_group = blk.get("vassal_contract_group")

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name = ck3.loc(key)
        desc = ck3.loc(f"{key}_desc")
        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "mechanicType": blk.get("mechanic_type"),
            "isMechanicDefault": bool(blk.get("is_mechanic_type_default", False)),
            "fallback": blk.get("fallback"),
            "primaryHolding": {"key": blk.get("primary_holding"),
                               "name": holding_name(blk.get("primary_holding"))} if blk.get("primary_holding") else None,
            "validHoldings": [{"key": h, "name": holding_name(h)} for h in valid if isinstance(h, str)],
            "requiredCountyHoldings": [{"key": h, "name": holding_name(h)} for h in required if isinstance(h, str)],
            "rules": rules,
            "flags": flags,
            "royalCourt": blk.get("royal_court"),
            "blockedSubjectCourts": name_list(
                blk.get("blocked_subject_courts").values() if isinstance(blk.get("blocked_subject_courts"), Block) else [],
                ck3.loc),
            "vassalContractGroup": {"key": contract_group,
                                    "name": ck3.render_text(ck3.loc(contract_group) or contract_group)} if contract_group else None,
            "primaryHeritages": name_list(
                blk.get("primary_heritages").values() if isinstance(blk.get("primary_heritages"), Block) else [],
                lambda k: ck3.loc(k) or ck3.loc(f"{k}_name")),
            "preferredReligions": name_list(
                blk.get("preferred_religions").values() if isinstance(blk.get("preferred_religions"), Block) else [],
                ck3.loc),
            "domicileType": blk.get("domicile_type"),
            "adminTiers": {t: blk.get(f)
                           for t, f in (("main", "main_administrative_tier"),
                                        ("appointment", "min_appointment_tier"),
                                        ("provincialMaa", "minimum_provincial_maa_tier"))
                           if blk.has(f)} or None,
            "titleMaaSetup": blk.get("administrative_title_maa_setup") or blk.get("title_maa_setup"),
            "characterModifiers": rendered_modifiers(blk, "character_modifier"),
            "topLiegeModifiers": rendered_modifiers(blk, "top_liege_character_modifier"),
            "supplyLimitMultForOthers": blk.get("supply_limit_mult_for_others"),
            "prestigeOpinionOverride": prestige_override,
            "courtGenerateCommanders": blk.get("court_generate_commanders"),
            "maxDread": blk.get("max_dread"),
            "currencyLevelCaps": caps,
            "compatibleSuccession": name_list(
                blk.get("compatible_government_type_succession").values()
                if isinstance(blk.get("compatible_government_type_succession"), Block) else [],
                ck3.loc),
            "color": color_hex(blk.get("color")),
            "icon": key,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)

    # mechanic-type defaults first, then the rest alphabetically by name
    out.sort(key=lambda r: (not r["isMechanicDefault"], r["name"] or r["id"]))
    ck3.write_json("governments.json", out)

    if unhandled:
        print("⚠ unhandled government fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")


if __name__ == "__main__":
    main()
