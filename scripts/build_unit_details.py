#!/usr/bin/env python3
"""Build src/data/unit_details.json — per men-at-arms: how to unlock it, its earliest era,
and the raw game-script definition (for the detail pages).

Unlock is resolved from three mechanisms, anchored on the files:
  1. Innovation with `unlock_maa = <unit>`  → that innovation (and its culture_era).
  2. The unit's `can_recruit` requiring `has_innovation = X` / `has_all_innovations`.
  3. A cultural tradition whose `parameters` grant the unit's `unlock_maa_<x>` parameter
     (via `valid_for_maa_trigger = { PARAMETER = unlock_maa_<x> }`), or a plain
     `has_cultural_parameter`.
Base types with no gate are available to any culture from the start (tribal era).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

ERA_ORDER = ["culture_era_tribal", "culture_era_early_medieval",
             "culture_era_high_medieval", "culture_era_late_medieval"]
ERA_RANK = {e: i for i, e in enumerate(ERA_ORDER)}
MAA_DIR = ck3.COMMON / "men_at_arms_types"


def era_name(key):
    if not key:
        return None
    return key.removeprefix("culture_era_").replace("_", " ").title()


# DLC file-prefixes that leak into tradition keys when no localisation is loaded for them.
_DLC_PREFIXES = ("tgp ", "fp1 ", "fp2 ", "fp3 ", "ep1 ", "ep2 ", "ep3 ", "mpo ", "bp1 ", "bp2 ")


def trad_display_name(key):
    loc = ck3.loc(key)
    name = ck3.render_text(loc) if loc else None
    if not name or name.startswith("tradition_"):
        name = key.removeprefix("tradition_").replace("_", " ").title()
    low = name.lower()
    for p in _DLC_PREFIXES:
        if low.startswith(p):
            name = name[len(p):]
            break
    return name


# Men-at-arms with no can_recruit gate in their own file — the recruit check lives in a shared
# scripted trigger keyed on a cultural parameter, so it can't be traced from the unit block.
# Resolved by hand from tgp_traditions.txt (the parameter -> tradition that grants it).
MANUAL_UNLOCK = {
    "burenjia": [{"kind": "tradition", "name": "Art of War", "era": None}],                 # unlock_burenjia
    "japanese_horse_archers": [{"kind": "tradition", "name": "Imperial Peace", "era": None}],  # Mounted Samurai, unlock_mounted_samurai_units
    "emishi_horse_archers": [{"kind": "tradition", "name": "Imperial Peace", "era": None}],   # Emishi Riders, unlock_emishi_horse_archers_units
}


def build_innovation_maps():
    """innovation_key -> era; maa_id -> unlocking innovation_key; innovation_key -> display name."""
    inno_era, unlock_by_inno, inno_name = {}, {}, {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "culture" / "innovations"):
        if isinstance(blk, Tagged):
            blk = blk.block
        if not isinstance(blk, Block):
            continue
        era = blk.get("culture_era")
        if isinstance(era, str):
            inno_era[key] = era
        inno_name[key] = ck3.render_text(ck3.loc(key) or key.removeprefix("innovation_").replace("_", " ").title())
        for uk in blk.get_all("unlock_maa"):
            if isinstance(uk, str):
                unlock_by_inno[uk] = key
    return inno_era, unlock_by_inno, inno_name


def build_tradition_param_map():
    """cultural-parameter -> tradition display name (for unlock_maa_* parameters)."""
    out = {}
    for _p, key, tb in ck3.parse_dir(ck3.COMMON / "culture" / "traditions"):
        if isinstance(tb, Tagged):
            tb = tb.block
        if not isinstance(tb, Block):
            continue
        name = trad_display_name(key)
        params = tb.get("parameters")
        if isinstance(params, Block):
            for pk in params.keys():
                if isinstance(pk, str) and pk.startswith("unlock_"):
                    out[pk] = name
    return out


def scan_can_recruit(trigger, found, negated=False):
    """Collect positive has_innovation and PARAMETER references from a can_recruit trigger,
    skipping OR / trigger_if branches (only mandatory gates)."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k in ("OR", "trigger_if", "trigger_else", "trigger_else_if"):
            continue
        neg = negated or (k in ("NOT", "NOR", "NAND"))
        if neg:
            continue
        if k in ("has_innovation",) and isinstance(v, str):
            found["innovations"].append(v)
        elif k == "has_all_innovations" and isinstance(v, Block):
            found["innovations"].extend([x for x in v.values() if isinstance(x, str)])
        elif k == "PARAMETER" and isinstance(v, str):
            found["parameters"].append(v)
        elif k == "has_cultural_parameter" and isinstance(v, str):
            found["parameters"].append(v)
        elif isinstance(v, (Block, Tagged)):
            scan_can_recruit(v, found, neg)


def raw_block(path, unit_id):
    """Extract the unit's raw script block from its source file by brace matching."""
    text = (MAA_DIR / path).read_text(encoding="utf-8-sig", errors="replace")
    m = re.search(r"(?m)^" + re.escape(unit_id) + r"\s*=\s*\{", text)
    if not m:
        return None
    i, depth = m.end() - 1, 0
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():i + 1]
        i += 1
    return None


def main():
    inno_era, unlock_by_inno, inno_name = build_innovation_maps()
    param_trad = build_tradition_param_map()

    details = {}
    for path, key, blk in ck3.parse_dir(MAA_DIR):
        if not isinstance(blk, Block):
            continue
        found = {"innovations": [], "parameters": []}
        scan_can_recruit(blk.get("can_recruit"), found)

        vias = []          # structured unlock steps
        eras = []          # candidate earliest eras

        # innovation that directly unlocks this unit
        if key in unlock_by_inno:
            ik = unlock_by_inno[key]
            vias.append({"kind": "innovation", "name": inno_name.get(ik, ik), "era": era_name(inno_era.get(ik))})
            eras.append(inno_era.get(ik))
        # innovations required by can_recruit
        for ik in dict.fromkeys(found["innovations"]):
            vias.append({"kind": "innovation", "name": inno_name.get(ik, ik.removeprefix("innovation_").replace("_", " ").title()), "era": era_name(inno_era.get(ik))})
            eras.append(inno_era.get(ik))
        # cultural traditions (via parameters)
        for pk in dict.fromkeys(found["parameters"]):
            if pk.startswith("unlock_") and pk in param_trad:
                vias.append({"kind": "tradition", "name": param_trad[pk], "era": None})
            elif pk.startswith("unlock_"):
                vias.append({"kind": "tradition", "name": pk.removeprefix("unlock_maa_").removeprefix("unlock_").replace("_", " ").title(), "era": None})

        # units whose gate lives in a shared trigger (no can_recruit): resolved by hand
        if not vias and key in MANUAL_UNLOCK:
            vias = [dict(v) for v in MANUAL_UNLOCK[key]]

        # earliest era available: highest-ranked required innovation era, else tribal
        req_eras = [e for e in eras if e]
        unlock_era = ERA_ORDER[max(ERA_RANK[e] for e in req_eras)] if req_eras else ERA_ORDER[0]

        if not vias:
            summary = "Available to any culture (base men-at-arms type)."
        else:
            parts = []
            for v in vias:
                if v["kind"] == "innovation":
                    parts.append(f"the {v['name']} innovation" + (f" ({v['era']} era)" if v["era"] else ""))
                else:
                    parts.append(f"the {v['name']} cultural tradition")
            summary = "Unlocked by " + " and ".join(parts) + "."

        details[key] = {
            "unlockEra": unlock_era,
            "unlockEraName": era_name(unlock_era),
            "unlockVia": vias,
            "unlockSummary": summary,
            "raw": raw_block(path.name, key),
            "sourceFile": path.name,
        }

    ck3.write_json("unit_details.json", details)
    # quick report
    by_era = {}
    for k, v in details.items():
        by_era.setdefault(v["unlockEraName"], []).append(k)
    for e in ["Tribal", "Early Medieval", "High Medieval", "Late Medieval"]:
        print(f"  {e}: {len(by_era.get(e, []))} units")


if __name__ == "__main__":
    main()
