#!/usr/bin/env python3
"""Build src/data/situations.json from common/situation/ (situations +
situation_group_types + catalysts).

Schema documented in _situations.info (the live data uses `modifier_sets`, not
the .info's `modifier_named_sets`). Per situation: sub-regions, participant
groups, phases with per-group modifier sets and parameters, and phase
transitions with takeover rules and catalyst point values.

`debug_situation` is excluded, as the game hides its debug group.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import world_render as wr
from ck3 import Block, Tagged

# No has_dlc_feature gates exist in situation scripts; tgp_* files carry a
# filename prefix, the steppe situations do not. Hand-maintained like
# ck3.FEATURE_TO_DLC (the nomad game-rule variants ride on the nomad
# government from Khans of the Steppe).
SITUATION_DLC = {
    "the_great_steppe": "Khans of the Steppe",
    "game_rule_extra_nomads_arabs": "Khans of the Steppe",
    "game_rule_extra_nomads_horn": "Khans of the Steppe",
    "game_rule_extra_nomads_sahel": "Khans of the Steppe",
    "game_rule_extra_nomads_sami": "Khans of the Steppe",
    "game_rule_extra_nomads_tibet": "Khans of the Steppe",
}

SKIP_FIELDS = {
    "illustration": "event-window art",
    "icon": "triggered icon selection; situation_types/<id>.dds covers display",
    "window": "GUI code-window binding",
    "gui_window_name": "GUI window binding",
    "gui_participation_window_name": "GUI window binding",
    "gui_tooltip_group_focused": "GUI tooltip layout flag",
    "map_mode": "map-mode plumbing",
    "sort_order": "GUI sort weight",
    "use_situation_phase_flat_icons": "GUI icon style flag",
    "keep_full_history": "catalyst-history memory flag",
    "on_start": "event scripting",
    "on_end": "event scripting",
    "on_monthly": "event scripting",
    "on_yearly": "event scripting",
    "on_join": "event scripting",
    "on_leave": "event scripting",
}

HANDLED_FIELDS = {
    "situation_group_type", "is_unique", "migration", "sub_regions",
    "participant_groups", "start_phase", "phases",
}

PHASE_SKIP = {
    "illustration": "event-window art",
    "icon": "phase icon path (seasons/… art)",
    "on_start": "event scripting",
    "on_end": "event scripting",
    "map_province_effect": "map shader effect",
    "map_province_effect_intensity": "map shader effect",
}
PHASE_HANDLED = {"max_duration", "max_duration_next_phase", "future_phases",
                 "modifier_sets", "parameters"}

GROUP_SKIP = {
    "icon": "GUI group icon",
    "map_color": "map-mode color",
    "on_join": "event scripting",
    "on_leave": "event scripting",
}
GROUP_HANDLED = {"is_character_valid", "require_capital_in_sub_region",
                 "require_realm_in_sub_region", "require_domain_in_sub_region",
                 "require_domicile_in_sub_region", "auto_add_rulers",
                 "auto_add_landless_rulers"}

NEGATORS = {"NOT", "NOR", "NAND"}

# is_character_valid trigger keys worth surfacing as chips (shallow +
# negation-aware, the men-at-arms pattern).
REQ_KEYS = {
    "has_government": "government",
    "has_trait": "trait",
    "highest_held_title_tier": "tier",
    "has_cultural_pillar": "cultural_pillar",
}


def req_name(kind, key, op):
    if kind == "government":
        return wr.loc_chain(key, f"{key}_name") or key.replace("_", " ").title()
    if kind == "trait":
        return wr.loc_chain(f"trait_{key}") or key.replace("_", " ").title()
    if kind == "tier":
        tier = str(key).removeprefix("tier_")
        return f"{tier.title()} tier or higher" if op in (">=", ">") else f"{tier.title()} tier"
    return wr.loc_chain(key) or str(key).replace("_", " ").title()


def collect_requirements(trigger, reqs, negated=False):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, op, v in trigger:
        if k in REQ_KEYS and isinstance(v, (str, int)):
            reqs.append({"kind": REQ_KEYS[k], "key": str(v), "negated": negated,
                         "name": req_name(REQ_KEYS[k], v, op)})
        elif isinstance(v, (Block, Tagged)):
            collect_requirements(v, reqs, negated or (k in NEGATORS))


def deplaceholder(name, key, *strip_prefixes):
    """Dynamic loc names ([Situation.Var…]) render with … placeholders; a
    prettified key reads better on a static reference page."""
    if name and "…" not in name:
        return name
    for pfx in strip_prefixes:
        key = key.removeprefix(pfx)
    return key.replace("_", " ").title()


def params_out(blk, unloc, drop_unloc=False):
    out = []
    if not isinstance(blk, Block):
        return out
    for k, _op, v in blk:
        if k is None:
            continue
        text = wr.loc_chain(f"situation_parameter_{k}")
        if text is None:
            # phase-type parameters without situation_parameter_ loc are
            # internal classification flags (era_type_*, hide_in_phases_list)
            if drop_unloc:
                continue
            unloc.add(k)
            text = k.replace("_", " ").capitalize()
        out.append({"key": k, "text": text})
    return out


def main():
    catalyst_keys = {k for _p, k, _b in
                     ck3.parse_dir(ck3.COMMON / "situation" / "catalysts")}
    group_types = {}
    for _p, k, b in ck3.parse_dir(ck3.COMMON / "situation" / "situation_group_types"):
        group_types[k] = wr.loc_chain(f"situation_group_type_{k}") or k.title()

    unhandled = Counter()
    unloc_params = set()
    out = []

    for path, key, blk in ck3.parse_dir(ck3.COMMON / "situation" / "situations"):
        if key == "debug_situation":
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        def sit_loc(*suffixes):
            return wr.loc_chain(*[s.format(k=key) for s in suffixes])

        sub_regions = []
        for sk, _op, sv in (blk.get("sub_regions") or Block()):
            if sk is None or not isinstance(sv, Block):
                continue
            regions = [v for v in (sv.get("geographical_regions") or Block()).values()
                       if isinstance(v, str)]
            sub_regions.append({
                "id": sk,
                "name": wr.loc_chain(f"{key}_sub_region_{sk}", sk) or sk.replace("_", " ").title(),
                "regions": regions,
            })

        groups = []
        group_ids = []
        for gk, _op, gv in (blk.get("participant_groups") or Block()):
            if gk is None or not isinstance(gv, Block):
                continue
            group_ids.append(gk)
            for k in gv.keys():
                if k not in GROUP_HANDLED and k not in GROUP_SKIP:
                    unhandled[f"group.{k}"] += 1
            reqs = []
            collect_requirements(gv.get("is_character_valid"), reqs)
            groups.append({
                "id": gk,
                "name": deplaceholder(
                    wr.loc_chain(f"{key}_participant_group_{gk}",
                                 f"the_great_steppe_participant_group_{gk}"), gk),
                "capitalInRegion": bool(gv.get("require_capital_in_sub_region", False)),
                "realmInRegion": bool(gv.get("require_realm_in_sub_region", True)),
                "domainInRegion": bool(gv.get("require_domain_in_sub_region", False)),
                "autoAddRulers": bool(gv.get("auto_add_rulers", True)),
                "autoAddLandless": bool(gv.get("auto_add_landless_rulers", True)),
                "requirements": reqs,
            })

        def group_name(g):
            for grp in groups:
                if grp["id"] == g:
                    return grp["name"]
            return g.replace("_", " ").title() if isinstance(g, str) else g

        def phase_name(pk):
            return deplaceholder(
                wr.loc_chain(pk, f"{pk}_situation_phase",
                             f"{key}_{pk}_situation_phase"),
                pk, f"situation_{key}_phase_", "situation_", "natural_disaster_")

        phases = []
        for pk, _op, pv in (blk.get("phases") or Block()):
            if pk is None or not isinstance(pv, Block):
                continue
            for k in pv.keys():
                if k not in PHASE_HANDLED and k not in PHASE_SKIP:
                    unhandled[f"phase.{k}"] += 1

            sets = []
            for sk, _op2, sv in (pv.get("modifier_sets") or Block()):
                if sk is None or not isinstance(sv, Block):
                    continue
                per_group = []
                for tk, _op3, tv in sv:
                    if tk is None or tk == "icon" or not isinstance(tv, (Block, Tagged)):
                        continue
                    if tk != "all" and tk not in group_ids:
                        unhandled[f"set_target.{tk}"] += 1
                    tvb = tv.block if isinstance(tv, Tagged) else tv
                    entry = {
                        "group": tk,
                        "groupName": "Everyone" if tk == "all" else group_name(tk),
                        "characterModifiers": wr.mods_out(tvb.get("character_modifier")),
                        "countyModifiers": wr.mods_out(tvb.get("county_modifier")),
                        "parameters": params_out(tvb.get("parameters"), unloc_params),
                    }
                    for dk, _op4, dv in tvb:
                        if dk == "doctrine_character_modifier" and isinstance(dv, Block):
                            doctrine = dv.get("doctrine")
                            rest = Block([t for t in dv if t[0] not in ("doctrine", "name")])
                            for m in wr.mods_out(rest):
                                m["doctrine"] = doctrine
                                entry["characterModifiers"].append(m)
                        elif dk not in ("character_modifier", "county_modifier",
                                        "parameters", None):
                            unhandled[f"set_field.{dk}"] += 1
                    if entry["characterModifiers"] or entry["countyModifiers"] or entry["parameters"]:
                        per_group.append(entry)
                if per_group:
                    sets.append({
                        "id": sk,
                        "name": wr.loc_chain(sk) or sk.replace("_", " ").title(),
                        "perGroup": per_group,
                    })

            transitions = []
            for tk, _op2, tv in (pv.get("future_phases") or Block()):
                if tk is None or not isinstance(tv, Block):
                    continue
                catalysts = []
                for ck, _op3, cv in (tv.get("catalysts") or Block()):
                    if ck is None:
                        continue
                    if ck not in catalyst_keys:
                        unhandled[f"unknown_catalyst.{ck}"] += 1
                    catalysts.append({
                        "id": ck,
                        "name": wr.loc_chain(ck) or ck.removeprefix("catalyst_").replace("_", " ").capitalize(),
                        "desc": wr.loc_chain(f"{ck}_desc"),
                        "points": wr.value_out(cv),
                    })
                takeover = tv.get("takeover_type")
                transitions.append({
                    "to": tk,
                    "toName": phase_name(tk),
                    "takeoverType": takeover,
                    "takeoverPoints": wr.value_out(tv.get("takeover_points")) if tv.has("takeover_points") else None,
                    "takeoverDuration": wr.duration_text(tv.get("takeover_duration")),
                    "weight": wr.value_out(tv.get("weight")) if tv.has("weight") else None,
                    "catalysts": catalysts,
                })
                for k in tv.keys():
                    if k not in ("takeover_type", "takeover_points",
                                 "takeover_duration", "weight", "catalysts"):
                        unhandled[f"future.{k}"] += 1

            phases.append({
                "id": pk,
                "name": phase_name(pk),
                "desc": wr.loc_chain(f"{pk}_desc", f"{pk}_situation_phase_desc",
                                     f"{key}_{pk}_situation_phase_desc"),
                "maxDuration": wr.duration_text(pv.get("max_duration")),
                "nextSelection": pv.get("max_duration_next_phase", "highest_points"),
                "parameters": params_out(pv.get("parameters"), unloc_params, drop_unloc=True),
                "sets": sets,
                "transitions": transitions,
            })

        gt = blk.get("situation_group_type", "minor")
        rec = {
            "id": key,
            "name": deplaceholder(
                wr.loc_chain(f"situation_type_{key}", key, f"game_concept_{key}"),
                key, "natural_disaster_", "game_rule_extra_"),
            "desc": wr.loc_chain(f"situation_type_{key}_desc", f"{key}_desc",
                                 f"game_concept_{key}_desc"),
            "groupType": gt,
            "groupTypeName": group_types.get(gt, gt.title()),
            "unique": bool(blk.get("is_unique", False)),
            "migration": bool(blk.get("migration", False)),
            "subRegions": sub_regions,
            "groups": groups,
            "startPhase": blk.get("start_phase"),
            "phases": phases,
            "dlc": SITUATION_DLC.get(key) or ck3.dlc_tag(path, blk)[0],
            "icon": key,
            "sourceFile": path.name,
        }
        out.append(rec)

    order = {"major": 0, "struggles": 1, "story_cycles": 2, "natural_disasters": 3, "minor": 4}
    out.sort(key=lambda r: (order.get(r["groupType"], 9), r["id"]))
    ck3.write_json("situations.json", out)

    if unhandled:
        print("⚠ unhandled situation fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    if unloc_params:
        print(f"⚠ {len(unloc_params)} situation parameters without loc: {sorted(unloc_params)[:8]}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ entries without localized names: {missing_names}")


if __name__ == "__main__":
    main()
