#!/usr/bin/env python3
"""Build src/data/legends.json from common/legends/ (legend_types +
legend_seeds + chronicles).

Schemas documented in _legends.info / _legend_seeds.info / _chronicles.info.
Emits {types, seeds, chronicles}: types with per-quality costs and impact
modifiers, seeds with shallow negation-aware requirements and their
chronicle's chapters, chronicles with properties/chapters/impact.

The whole legends system ships with Legends of the Dead (seeds carry
`has_dlc_feature = legends` gates; types/chronicles inherit the system).
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import world_render as wr
from ck3 import Block, Tagged

LEGENDS_DLC = "Legends of the Dead"

TYPE_SKIP = {
    "color": "map tint",
    "on_start": "event scripting (prestige grant, bookkeeping)",
    "on_end": "event scripting",
    "on_province_spread": "notification scripting",
    "on_province_recovered": "notification scripting",
    "on_legend_start_promote": "event scripting",
    "on_legend_stop_promote": "event scripting",
    "on_yearly": "event scripting",
    "ai_protagonist_weight": "AI weighting",
}
TYPE_HANDLED = {"quality", "is_valid_protagonist"}

QUALITY_SKIP = {
    "ai_chance": "AI create/promote/upgrade weighting",
    "spread_chance": "conditional spread formula (0 when unowned); "
                     "not a player-facing stat",
}
QUALITY_HANDLED = {"max_provinces", "creation_cost", "owner_cost",
                   "promoter_cost", "upgrade_cost", "removal_duration",
                   "impact"}

IMPACT_SKIP = {
    "on_complete": "event-scripted completion rewards (trait, dynasty renown, "
                   "legendary building unlock) — resolved through events, "
                   "not statically renderable",
}
IMPACT_MODS = ("province_modifier", "county_modifier", "owner_modifier",
               "promoter_modifier")

SEED_SKIP = {}
SEED_HANDLED = {"type", "quality", "is_shown", "is_valid", "chronicle",
                "chronicle_properties", "chronicle_chapters"}

CHRON_SKIP = {
    "portrait_animation": "portrait art selection",
    "name": "dynamic naming (owner/protagonist scopes); fallback key emitted",
    "description": "dynamic description (owner/protagonist scopes)",
}
CHRON_HANDLED = {"properties", "chapters", "impact"}

NEGATORS = {"NOT", "NOR", "NAND"}

# is_shown/is_valid trigger keys worth surfacing as chips (shallow +
# negation-aware, the men-at-arms pattern).
REQ_KEYS = {
    "has_cultural_pillar": "cultural_pillar",
    "has_trait": "trait",
    "has_dynasty_perk": "dynasty_perk",
    "has_government": "government",
    "prestige_level": "prestige_level",
    "piety_level": "piety_level",
    "has_religion": "religion",
    "has_faith": "faith",
    "culture": "culture_ref",
    "religion": "religion_ref",
    "is_landed": "flag",
    "is_ruler": "flag",
    "is_independent_ruler": "flag",
    "has_dlc_feature": "dlc_feature",
}


def req_name(kind, key, op):
    if kind == "cultural_pillar":
        return wr.loc_chain(str(key), f"{key}_name") or str(key).replace("_", " ").title()
    if kind == "trait":
        return wr.loc_chain(f"trait_{key}") or str(key).replace("_", " ").title()
    if kind == "dynasty_perk":
        return wr.loc_chain(f"{key}_name") or str(key).replace("_", " ").title()
    if kind in ("prestige_level", "piety_level"):
        lvl = str(key).removeprefix("high_").removeprefix("low_")
        label = "Prestige" if kind == "prestige_level" else "Piety"
        n, _ = ck3.resolve_value(key) if isinstance(key, str) else (key, None)
        shown = wr.num(n) if n is not None else str(key).replace("_", " ")
        return f"{label} level ≥ {shown}" if op in (">=", ">") else f"{label} level {shown}"
    if kind == "flag":
        return None  # caller renders the trigger key itself
    if kind == "dlc_feature":
        return None  # DLC provenance, not a requirement chip
    key = str(key).split(":")[-1]  # culture:cornish -> cornish
    return wr.loc_chain(key, f"{key}_name") or key.replace("_", " ").title()


def collect_requirements(trigger, reqs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k in REQ_KEYS and not isinstance(v, (Block, Tagged)):
            kind = REQ_KEYS[k]
            if kind == "dlc_feature":
                continue
            if kind == "flag":
                name = k.removeprefix("is_").replace("_", " ").capitalize()
            else:
                name = req_name(kind, v, op)
            if name:
                reqs.append({"kind": kind, "key": str(v), "negated": negated,
                             "name": name})
        elif k == "culture" and isinstance(v, Block):
            # culture = { has_cultural_pillar = x } — one common nesting
            collect_requirements(v, reqs, negated)
        elif k == "dynasty" and isinstance(v, Block):
            collect_requirements(v, reqs, negated)
        elif isinstance(v, (Block, Tagged)):
            collect_requirements(v, reqs, negated or (k in NEGATORS))


def main():
    unhandled = Counter()

    # --- chronicles -------------------------------------------------------
    chronicles = []
    chron_by_id = {}
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "legends" / "chronicles"):
        for k in blk.keys():
            if k not in CHRON_HANDLED and k not in CHRON_SKIP:
                unhandled[f"chronicle.{k}"] += 1
        properties = [k for k, _op, _v in (blk.get("properties") or Block())
                      if k is not None]
        chapters = []
        for k, _op, v in (blk.get("chapters") or Block()):
            ck_key = k if k is not None else (v if isinstance(v, str) else None)
            if ck_key:
                chapters.append(ck_key)
        impact = blk.get("impact")
        rec = {
            "id": key,
            "name": wr.loc_chain(f"legend_chronicle_{key}")
                    or key.replace("_", " ").title(),
            "desc": wr.loc_chain(f"legend_chronicle_{key}_desc"),
            "properties": properties,
            "chapters": chapters,
            "impact": {m: wr.mods_out(impact.get(m)) for m in IMPACT_MODS
                       if isinstance(impact, Block) and impact.has(m)} if impact else {},
        }
        chronicles.append(rec)
        chron_by_id[key] = rec

    # --- legend types -----------------------------------------------------
    types = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "legends" / "legend_types"):
        for k in blk.keys():
            if k not in TYPE_HANDLED and k not in TYPE_SKIP:
                unhandled[f"type.{k}"] += 1
        protagonist = []
        collect_requirements(blk.get("is_valid_protagonist"), protagonist)
        # age >= 16 style gates aren't in REQ_KEYS; surface the raw trigger
        ivp = blk.get("is_valid_protagonist")
        if isinstance(ivp, Block):
            for k, op, v in ivp:
                if k == "age":
                    protagonist.append({"kind": "age", "key": str(v),
                                        "negated": False, "name": f"Age {op} {v}"})
        qualities = []
        for qk, _op, qv in (blk.get("quality") or Block()):
            if qk is None or not isinstance(qv, Block):
                continue
            for k in qv.keys():
                if k not in QUALITY_HANDLED and k not in QUALITY_SKIP:
                    unhandled[f"quality.{k}"] += 1
            impact = qv.get("impact")
            if isinstance(impact, Block):
                for k in impact.keys():
                    if k not in IMPACT_MODS and k not in IMPACT_SKIP:
                        unhandled[f"impact.{k}"] += 1
            qualities.append({
                "quality": qk,
                "name": wr.loc_chain(qk) or qk.title(),
                "maxProvinces": wr.range_text(qv.get("max_provinces")),
                "creationCost": wr.cost_out(qv.get("creation_cost")),
                "ownerCost": wr.cost_out(qv.get("owner_cost")),
                "promoterCost": wr.cost_out(qv.get("promoter_cost")),
                "upgradeCost": wr.cost_out(qv.get("upgrade_cost")),
                "removalDuration": wr.duration_text(qv.get("removal_duration")),
                "impact": {m: wr.mods_out(impact.get(m)) for m in IMPACT_MODS
                           if isinstance(impact, Block) and impact.has(m)},
            })
        types.append({
            "id": key,
            "name": wr.loc_chain(f"legend_{key}") or key.title(),
            "desc": wr.loc_chain(f"legend_{key}_desc"),
            "protagonist": protagonist,
            "qualities": qualities,
            "icon": key,
            "dlc": LEGENDS_DLC,
            "sourceFile": path.name,
        })

    # --- legend seeds -----------------------------------------------------
    seeds = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "legends" / "legend_seeds"):
        for k in blk.keys():
            if k not in SEED_HANDLED and k not in SEED_SKIP:
                unhandled[f"seed.{k}"] += 1
        reqs = []
        collect_requirements(blk.get("is_shown"), reqs)
        collect_requirements(blk.get("is_valid"), reqs)
        # de-duplicate identical chips from is_shown/is_valid overlap
        seen, uniq = set(), []
        for r in reqs:
            sig = (r["kind"], r["key"], r["negated"])
            if sig not in seen:
                seen.add(sig)
                uniq.append(r)
        chron = blk.get("chronicle")
        quality = blk.get("quality")
        ltype = blk.get("type")
        # ce1_* seeds ride on the Community Pack dynasty perk, not the flag
        dlc = LEGENDS_DLC
        m = key.split("_")[0]
        if m in ck3.PREFIX_TO_DLC:
            dlc = ck3.PREFIX_TO_DLC[m]
        seeds.append({
            "id": key,
            "name": wr.loc_chain(f"legend_{key}") or key.replace("_", " ").title(),
            "desc": wr.loc_chain(f"legend_{key}_desc"),
            "quality": quality,
            "qualityName": wr.loc_chain(quality) or (quality or "").title(),
            "type": ltype,
            "typeName": wr.loc_chain(f"legend_{ltype}") or (ltype or "").title(),
            "chronicle": chron,
            "chronicleName": chron_by_id.get(chron, {}).get("name"),
            "requirements": uniq,
            "dlc": dlc,
            "sourceFile": path.name,
        })

    types.sort(key=lambda r: r["id"])
    seeds.sort(key=lambda r: (r["type"] or "", r["id"]))
    chronicles.sort(key=lambda r: r["id"])
    ck3.write_json("legends.json", {"types": types, "seeds": seeds,
                                    "chronicles": chronicles})

    if unhandled:
        print("⚠ unhandled legend fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    for label, rows in (("types", types), ("seeds", seeds), ("chronicles", chronicles)):
        missing = [r["id"] for r in rows if not r["name"]]
        if missing:
            print(f"⚠ {label} without localized names: {missing}")


if __name__ == "__main__":
    main()
