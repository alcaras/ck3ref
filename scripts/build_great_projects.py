#!/usr/bin/env python3
"""Build src/data/great_projects.json from common/great_projects/types/.

The Great Projects system (All Under Heaven): collaboratively funded works —
wonders, ministry undertakings, disaster relief — where a founder plans the
project and rulers fund contribution line-items until it completes.

Several projects construct actual buildings on completion (Mandala capitals,
the Great Wall sections, the Great Barracks). Those buildings are already
rendered by build_buildings.py (buildings.json category "Great projects"),
so this dataset cross-references them by id instead of duplicating stats.

DLC provenance: has_*_dlc_trigger scripted triggers where present (the game's
own 00_has_dlc_scripted_triggers.txt maps has_tgp_dlc_trigger to the
all_under_heaven feature); projects without one inherit provenance from the
building they construct.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

HANDLED_FIELDS = {
    "icon", "name", "is_shown", "can_start_planning", "is_location_valid",
    "cost", "construction_time", "contribution_threshold", "contributor_cooldown",
    "province_filter", "province_filter_target", "owner", "target_title_tier",
    "allowed_contributor_filter", "project_contributions", "group",
    "show_in_list", "is_important", "on_complete",
}

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "illustration": "art selection triggers; icon derivation covers display",
    "is_valid": "mid-flight invalidation triggers, not planning-facing",
    "can_cancel": "cancellation plumbing",
    "on_plan_build": "scripted ceremony effects (memories, variables)",
    "on_start_build": "scripted ceremony effects (prestige nudges)",
    "on_cancel": "scripted fallout effects (opinion penalties)",
    "on_invalidated": "scripted fallout effects",
    "invite_interaction": "interaction wiring, uniform default",
    "completion_sound_effect": "audio plumbing",
    "ai_will_do": "AI planning weight, not player-facing",
    "ai_check_interval": "AI pacing detail",
    "ai_check_interval_by_tier": "AI pacing detail",
    "ai_province_filter": "AI targeting detail",
    "ai_target_quick_trigger": "AI targeting detail",
}

CONTRIB_HANDLED = {"cost", "is_required", "allowed_contributor_filter", "on_complete"}
CONTRIB_SKIP = {
    "is_shown": "GUI visibility triggers",
    "show_in_planning_phase": "GUI visibility detail",
    "contributor_is_valid": "deep per-contributor trigger scripts (house aspects etc.)",
    "context_allows_contributions": "situation-phase timing triggers",
    "contributor_cooldown": "funding pacing detail",
    "on_contribution_funded": "scripted reward effects",
    "ai_will_do": "AI funding weight",
    "ai_check_interval": "AI pacing detail",
    "ai_check_interval_by_tier": "AI pacing detail",
}

OWNER_LABEL = {
    "province_owner_top_liege": "top liege of the province",
    "province_owner": "direct owner of the province",
    "founder_primary_title_owner": "holder of the founder's primary title",
    "founder_top_liege_title_owner": "holder of the founder's top liege title",
}

# The game's own file equates the tgp trigger with the all_under_heaven DLC
# feature; buildings tagged by the tgp_ filename prefix carry the same DLC.
_dlc_triggers: dict | None = None


def dlc_trigger_map():
    """has_*_dlc_trigger scripted-trigger name -> DLC display name."""
    global _dlc_triggers
    if _dlc_triggers is None:
        _dlc_triggers = {}
        p = ck3.COMMON / "scripted_triggers" / "00_has_dlc_scripted_triggers.txt"
        if p.exists():
            for key, _op, blk in ck3.parse_file(p):
                if isinstance(blk, Block):
                    feat = blk.get("has_dlc_feature")
                    if isinstance(feat, str):
                        _dlc_triggers[key] = ck3.FEATURE_TO_DLC.get(feat, feat)
    return _dlc_triggers


def scan_keys(blk, wanted, found):
    """Collect all values of `wanted` keys anywhere inside blk."""
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return
    for k, _op, v in blk:
        if k in wanted and isinstance(v, str):
            found.append((k, v))
        if isinstance(v, (Block, Tagged)):
            scan_keys(v, wanted, found)


def rules_text(rules, depth=0):
    """Flatten a resolve_value rules structure into one tooltip line."""
    if not isinstance(rules, list):
        return str(rules)
    parts = []
    for r in rules:
        if not isinstance(r, dict):
            parts.append(str(r))
            continue
        for k, v in r.items():
            if k == "if":
                parts.append(f"if {v}: {'; '.join(str(x) for x in r.get('then', []))}")
                break
            if k == "then":
                continue
            v = f"({rules_text(v, depth + 1)})" if isinstance(v, list) else v
            parts.append(f"{k} {v}")
    return "; ".join(parts)


def resolved(v):
    """-> {"n": number} for static values, {"rules": text} for conditional."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return {"n": round(n, 2) if isinstance(n, float) else n}
    return {"rules": rules_text(rules)}


COST_LABEL = {"treasury_or_gold": "gold", "gold": "gold", "piety": "piety",
              "prestige": "prestige", "influence": "influence", "herd": "herd",
              "treasury": "treasury"}


def cost_block(blk):
    if blk is None:
        return None
    out = {}
    for k, _op, v in blk:
        if k is None:
            continue
        rec = resolved(v)
        if k == "treasury_or_gold":
            rec["fromTreasury"] = True
        out[COST_LABEL.get(k, k)] = rec
    return out or None


# --- planning requirements (curated, MAA-style, negation-tracked) -----------

NEGATORS = {"NOT", "NOR", "NAND"}

REQ_KEYS = {
    "has_title": "title",
    "has_government": "government",
    "government_has_flag": "government_flag",
    "has_innovation": "innovation",
    "has_diarchy_type": "diarchy",
    "has_building": "building",
}

# Trigger plumbing whose presence is self-referential, not a real gate.
IGNORE_KEYS = {"is_planning_great_project", "great_project_type", "has_great_building",
               "has_building_with_flag", "has_ruined_great_building"}

SIMPLE_FACTS = {
    "is_independent_ruler": "Independent ruler",
    "is_tributary": "Tributary",
}


def req_name(kind, key):
    key = key.removeprefix("title:")
    if kind == "government_flag":
        stem = key.removeprefix("government_is_")
        raw = ck3.loc(f"{stem}_government_name") or ck3.loc(f"{stem}_government")
        return (f"{ck3.render_text(raw)} government" if raw
                else stem.replace("_", " ").title() + " government")
    if kind == "government":
        raw = ck3.loc(f"{key}_name") or ck3.loc(key)
        return f"{ck3.render_text(raw)} government" if raw else key.replace("_", " ").title()
    if kind == "building":
        b = _buildings_by_id.get(key)
        return b["name"] if b else key.replace("_", " ").title()
    raw = ck3.loc(key) or ck3.loc(f"{key}_name")
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


_INVERT_OP = {"<": ">=", ">": "<=", "<=": ">", ">=": "<", "=": "≠"}

# Conditional branches (trigger_if / trigger_else) express situational
# alternates a flat chip list cannot represent honestly — not descended into.
_BRANCH_KEYS = {"trigger_if", "trigger_else_if", "trigger_else", "limit"}


def collect_requirements(trigger, reqs, dlcs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k is None or k in _BRANCH_KEYS:
            continue
        if k in dlc_trigger_map():
            dlcs.add(dlc_trigger_map()[k])
        elif k in REQ_KEYS and isinstance(v, str) and v not in IGNORE_KEYS:
            kind = REQ_KEYS[k]
            reqs.append({"kind": kind, "key": v, "negated": negated,
                         "name": req_name(kind, v),
                         "building": v if kind == "building" else None})
        elif k in SIMPLE_FACTS and isinstance(v, bool):
            reqs.append({"kind": "fact", "key": k, "negated": negated != (not v),
                         "name": SIMPLE_FACTS[k], "building": None})
        elif k in ("piety_level", "legitimacy_level", "number_of_tributaries",
                   "highest_held_title_tier") and not isinstance(v, (Block, Tagged)):
            val = (str(v).removeprefix("tier_").removesuffix("_piety_level")
                   .replace("_", " "))
            shown_op = _INVERT_OP.get(op, f"not {op}") if negated else op
            reqs.append({"kind": "threshold", "key": k, "negated": False,
                         "name": f"{k.replace('_', ' ').capitalize()} {shown_op} {val}",
                         "building": None})
        elif k == "custom_tooltip" and isinstance(v, Block):
            txt = v.get("text")
            raw = ck3.loc(txt) if isinstance(txt, str) else None
            if raw:
                # tooltip texts are already phrased as the condition itself
                reqs.append({"kind": "condition", "key": txt, "negated": False,
                             "name": ck3.render_text(raw), "building": None})
        elif isinstance(v, (Block, Tagged)):
            collect_requirements(v, reqs, dlcs, negated or (k in NEGATORS))


def dedup(reqs):
    seen, out = set(), []
    for r in reqs:
        sig = (r["kind"], r["negated"], r["name"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


# --- names ------------------------------------------------------------------

def desc_keys(blk, out):
    """All desc loc refs inside a name block, in file order."""
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return
    for k, _op, v in blk:
        if k == "desc" and isinstance(v, str):
            out.append(v)
        elif isinstance(v, (Block, Tagged)):
            desc_keys(v, out)


def project_name(key, blk):
    refs = []
    for nb in blk.get_all("name"):
        desc_keys(nb, refs)
    # last entry = the untriggered fallback (dynamic-name quirk)
    raw = ck3.loc(refs[-1]) if refs else ck3.loc(f"great_project_type_{key}")
    return ck3.render_text(raw) if raw else None


def icon_key(blk, key):
    """First icon reference path -> path relative to gfx/interface/icons/."""
    for ib in blk.get_all("icon"):
        if isinstance(ib, Block):
            ref = ib.get("reference")
            if isinstance(ref, str):
                return (ref.removeprefix("gfx/interface/icons/")
                           .removesuffix(".dds"))
    return f"great_projects/{key}"


_buildings_by_id: dict = {}


def main():
    global _buildings_by_id
    buildings = json.loads(
        (ck3.ROOT / "src" / "data" / "buildings.json").read_text(encoding="utf-8"))
    _buildings_by_id = {b["id"]: b for b in buildings}

    GROUP_ORDER = {"major": 0, "minor": 1, "environmental_project": 2}
    entries = ck3.parse_dir(ck3.COMMON / "great_projects" / "types")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if not isinstance(blk, Block):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        reqs, dlcs = [], set()
        for gate in ("is_shown", "can_start_planning", "is_location_valid"):
            collect_requirements(blk.get(gate), reqs, dlcs)
        reqs = dedup(reqs)

        granted = []
        scan_keys(blk, {"add_building", "set_great_building", "add_great_building"},
                  granted)
        granted_ids = sorted({v for _k, v in granted})
        grants = [{"id": b, "name": _buildings_by_id[b]["name"]}
                  for b in granted_ids if b in _buildings_by_id]

        contributions = []
        pc = blk.get("project_contributions")
        if isinstance(pc, Block):
            for ck, _op, cb in pc:
                if ck is None or not isinstance(cb, Block):
                    continue
                for f in cb.keys():
                    if f not in CONTRIB_HANDLED and f not in CONTRIB_SKIP:
                        unhandled[f"contribution.{f}"] += 1
                cname = ck3.loc(f"great_project_type_{key}_contribution_{ck}")
                cdesc = ck3.loc(f"great_project_type_{key}_contribution_{ck}_desc")
                cfilter = cb.get("allowed_contributor_filter")
                contributions.append({
                    "id": ck,
                    "name": ck3.render_text(cname) if cname
                            else ck.replace("_", " ").title(),
                    "desc": ck3.render_text(cdesc) if cdesc else None,
                    "cost": cost_block(cb.get("cost")),
                    "required": bool(cb.get("is_required", True)),
                    "contributors": sorted(k for k, _o, v in cfilter if v is True)
                                    if isinstance(cfilter, Block) else None,
                })

        dlc = sorted(dlcs)[0] if dlcs else None
        if dlc is None and grants:
            # inherit provenance from the building this project constructs
            bdlc = _buildings_by_id[grants[0]["id"]]["dlc"]
            # buildings' tgp_ filename prefix and the has_tgp_dlc_trigger both
            # denote the all_under_heaven feature (00_has_dlc_scripted_triggers)
            dlc = "All Under Heaven" if bdlc == "The Great People" else bdlc

        csp = blk.get("can_start_planning")
        plannable = not (isinstance(csp, Block) and csp.get("always") is False)

        cfilter = blk.get("allowed_contributor_filter")
        out.append({
            "id": key,
            "name": project_name(key, blk),
            "plannable": plannable,
            "group": blk.get("group", "major"),
            "isImportant": bool(blk.get("is_important", False)),
            "showInList": bool(blk.get("show_in_list", True)),
            "cost": cost_block(blk.get("cost")),
            "constructionTime": resolved(blk.get("construction_time"))
                                if blk.has("construction_time") else None,
            "contributionThreshold": blk.get("contribution_threshold"),
            "contributorCooldown": resolved(blk.get("contributor_cooldown"))
                                   if blk.has("contributor_cooldown") else None,
            "provinceFilter": blk.get("province_filter"),
            "provinceFilterTarget": blk.get("province_filter_target"),
            "owner": OWNER_LABEL.get(blk.get("owner", "province_owner_top_liege"),
                                     blk.get("owner")),
            "targetTitleTier": blk.get("target_title_tier"),
            "contributors": sorted(k for k, _o, v in cfilter if v is True)
                            if isinstance(cfilter, Block) else ["owner", "vassals"],
            "requirements": reqs,
            "grantsBuildings": grants,
            "contributions": contributions,
            "icon": icon_key(blk, key),
            "dlc": dlc,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (GROUP_ORDER.get(r["group"], 9),
                            r["sourceFile"], r["id"]))
    ck3.write_json("great_projects.json", out)

    if unhandled:
        print("⚠ unhandled great-project fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing}")


if __name__ == "__main__":
    main()
