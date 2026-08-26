#!/usr/bin/env python3
"""Build factions.json, elections.json, administration.json.

Factions, the election/appointment systems (vote-weight factors rendered as
readable lines, never collapsed to a number), vassal stances, confederations,
and the administrative taxation layer (tax slots + lease contracts).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

NEG = {"NOT", "NOR", "NAND"}


def pretty(k):
    t = (str(k).removesuffix("_trigger").removeprefix("is_").removeprefix("has_")
         .replace("_", " ").strip())
    return t[:1].upper() + t[1:] if t else str(k)


def conditions(block, out, negated=False, depth=0):
    """Readable condition labels, negation-aware, one level of macros deep."""
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block) or depth > 3:
        return
    for k, _op, v in block:
        if not isinstance(k, str):
            continue
        if isinstance(v, (Block, Tagged)):
            conditions(v, out, negated or (k in NEG), depth + 1)
        elif v is True and (k.endswith("_trigger") or k.startswith("is_") or k.startswith("has_")):
            out.append({"name": pretty(k), "negated": negated})
        elif isinstance(v, str) and k in ("has_government", "government_has_flag",
                                          "has_trait", "has_doctrine", "has_realm_law"):
            loc = ck3.loc(f"trait_{v}") if k == "has_trait" else ck3.loc(v)
            out.append({"name": ck3.render_text(loc) if loc else pretty(v),
                        "negated": negated})


def dedupe(items, cap=8):
    seen, out = set(), []
    for x in items:
        sig = (x["name"], x["negated"])
        if sig not in seen:
            seen.add(sig)
            out.append(x)
    return out[:cap]


def weight_lines(block, depth=0, out=None):
    """Vote/candidate weighting rendered as readable factor lines. The game
    computes these from live state; we surface the named contributors."""
    out = [] if out is None else out
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block) or depth > 3:
        return out
    for k, _op, v in block:
        if k in ("add", "subtract", "multiply", "divide") and not isinstance(v, (Block, Tagged)):
            n, _r = ck3.resolve_value(v)
            out.append(f"{k} {n if n is not None else pretty(v)}")
        elif k in ("value", "base") and not isinstance(v, (Block, Tagged)):
            n, _r = ck3.resolve_value(v)
            out.append(f"base {n if n is not None else pretty(v)}")
        elif k in ("if", "else_if", "modifier") and isinstance(v, Block):
            cond = []
            conditions(v.get("limit") or v, cond)
            inner = weight_lines(v, depth + 1)
            label = ", ".join(c["name"] for c in dedupe(cond, 3)) or "conditional"
            if inner:
                out.append(f"{'; '.join(inner[:3])} — when {label}")
        elif isinstance(v, (Block, Tagged)):
            weight_lines(v, depth + 1, out)
    return out


def name_of(key, *extra):
    for cand in (key, f"{key}_name", *extra):
        v = ck3.loc(cand)
        if v:
            t = ck3.render_text(v)
            if t and "…" not in t:
                return t
    return pretty(key)


def mod_lines(blk, field):
    out = []
    for m in blk.get_all(field):
        if isinstance(m, Block):
            for k, _op, v in m:
                if k and not isinstance(v, (Block, Tagged)):
                    out.append(ck3.render_modifier(k, v))
    return out


def build_factions():
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "factions"):
        if not isinstance(blk, Block):
            continue
        join, valid = [], []
        conditions(blk.get("can_character_join"), join)
        conditions(blk.get("is_character_valid"), valid)
        cb = blk.get("casus_belli")
        thresh, _r = ck3.resolve_value(blk.get("power_threshold"))
        out.append({
            "id": key,
            "name": name_of(key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "shortEffect": ck3.render_text(ck3.loc(str(blk.get("short_effect_desc") or "")) or "") or None,
            "demand": blk.get("demand") is not None,
            "casusBelli": cb if isinstance(cb, str) else None,
            "casusBelliName": ck3.render_text(ck3.loc(cb) or "") if isinstance(cb, str) else None,
            "powerThreshold": thresh,
            "countyFaction": bool(blk.get("county_faction", False)),
            "canJoin": dedupe(join),
            "validWhen": dedupe(valid),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    out.sort(key=lambda r: r["name"])
    ck3.write_json("factions.json", out)


def build_elections():
    elections = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "succession_election"):
        if not isinstance(blk, Block):
            continue
        elections.append({
            "id": key,
            "name": name_of(key),
            "electors": weight_lines(blk.get("electors"))[:6],
            "candidates": weight_lines(blk.get("candidates"))[:6],
            "voteStrength": weight_lines(blk.get("elector_vote_strength"))[:10],
            "candidateScore": weight_lines(blk.get("candidate_score"))[:10],
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    appointments = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "succession_appointment"):
        if not isinstance(blk, Block):
            continue
        appointments.append({
            "id": key,
            "name": name_of(key),
            "level": blk.get("level"),
            "allowChildren": bool(blk.get("allow_children", False)),
            "sameTier": bool(blk.get("allow_same_tier_candidates", False)),
            "candidateScore": weight_lines(blk.get("candidate_score"))[:10],
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    stances = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "vassal_stances"):
        if not isinstance(blk, Block):
            continue
        stances.append({
            "id": key,
            "name": name_of(key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "factors": weight_lines(blk.get("score"))[:8],
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    confeds = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "confederation_types"):
        if not isinstance(blk, Block):
            continue
        levels = []
        cl = blk.get("cohesion_level")
        if isinstance(cl, Block):
            for lk, _o, lv in cl:
                if isinstance(lv, Block):
                    levels.append({"name": name_of(str(lk)),
                                   "lines": mod_lines(lv, "modifier")[:4]})
        confeds.append({
            "id": key,
            "name": name_of(key),
            "houseBased": bool(blk.get("house_based_confederation", False)),
            "levels": levels,
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    ck3.write_json("elections.json", {
        "elections": sorted(elections, key=lambda r: r["name"]),
        "appointments": sorted(appointments, key=lambda r: r["name"]),
        "stances": sorted(stances, key=lambda r: r["name"]),
        "confederations": sorted(confeds, key=lambda r: r["name"]),
    })


def build_admin():
    slots = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "tax_slots" / "types"):
        if not isinstance(blk, Block):
            continue
        obl = blk.get("obligations")
        slots.append({
            "id": key,
            "name": name_of(key),
            "defaultObligation": blk.get("default_obligation"),
            "obligations": [o for o in (obl.values() if isinstance(obl, Block) else [])
                            if isinstance(o, str)],
            "vassalLimit": ck3.resolve_value(blk.get("tax_slot_vassal_limit"))[0],
            "aptitudeFactors": weight_lines(blk.get("tax_collector_aptitude"))[:8],
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    obligations = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "tax_slots" / "obligations"):
        if not isinstance(blk, Block):
            continue
        gates = []
        conditions(blk.get("is_vassal_valid"), gates)
        conditions(blk.get("is_valid"), gates)
        tax, _ = ck3.resolve_value(blk.get("tax_factor"))
        levy, _ = ck3.resolve_value(blk.get("levies_factor"))
        obligations.append({
            "id": key,
            "name": name_of(key),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "tax": tax, "levies": levy,
            "subjectModifiers": mod_lines(blk, "subject_modifier")[:6],
            "liegeModifiers": mod_lines(blk, "liege_modifier")[:6],
            "gates": dedupe(gates, 5),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    leases = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "lease_contracts"):
        if not isinstance(blk, Block):
            continue
        vh = blk.get("valid_holdings")
        tax, _ = ck3.resolve_value(blk.get("tax"))
        levy, _ = ck3.resolve_value(blk.get("levy"))
        leases.append({
            "id": key,
            "name": name_of(key),
            "government": blk.get("government") if isinstance(blk.get("government"), str) else None,
            "hierarchy": [h for h in (blk.get("hierarchy").values()
                          if isinstance(blk.get("hierarchy"), Block) else [])
                          if isinstance(h, str)],
            "validHoldings": [h for h in (vh.values() if isinstance(vh, Block) else [])
                              if isinstance(h, str)],
            "tax": tax, "levy": levy,
            "minOpinion": blk.get("ruler_share_min_opinion_from_lessee"),
            "maxHookOpinion": blk.get("hook_strength_max_opinion"),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    ck3.write_json("administration.json", {
        "slots": slots, "obligations": sorted(obligations, key=lambda r: r["name"]),
        "leases": leases,
    })


if __name__ == "__main__":
    build_factions()
    build_elections()
    build_admin()
