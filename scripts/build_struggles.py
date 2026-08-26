#!/usr/bin/env python3
"""Build src/data/struggles.json from common/struggle/ (struggles + catalysts).

Schema documented in _struggles.info. Per struggle: involved cultures/faiths/
regions, phases with their per-audience parameter and modifier effects, phase
transitions with catalyst point values, and ending decisions.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import world_render as wr
from ck3 import Block

# No has_dlc_feature gates or DLC filename prefixes exist in struggle scripts;
# provenance is the DLC each struggle shipped with (hand-maintained, like
# ck3.FEATURE_TO_DLC).
STRUGGLE_DLC = {
    "iberian_struggle": "Fate of Iberia",
    "persian_struggle": "Legacy of Persia",
}

SKIP_FIELDS = {
    "illustration": "event-window art, not an icon key",
    "on_start": "event scripting (starting events / AI intents)",
    "on_end": "event scripting",
    "on_change_phase": "event scripting / debug telemetry",
    "on_join": "event scripting (supporter/detractor trait assignment)",
    "on_monthly": "event scripting",
    "situation_group_type": "GUI folder placement",
    "sort_order": "GUI sort weight",
    "save_progress": "phase-points bookkeeping flag on ending phases",
}

HANDLED_FIELDS = {
    "cultures", "faiths", "regions", "involvement_prerequisite_percentage",
    "transition_state_duration", "start_phase", "phase_list",
}

PHASE_HANDLED = {"future_phases", "war_effects", "faith_effects",
                 "culture_effects", "other_effects", "ending_decisions",
                 "duration", "on_start", "save_progress"}

EFFECT_GROUPS = ("war_effects", "faith_effects", "culture_effects", "other_effects")

# effect-group field -> (audience, kind)
AUDIENCE_FIELDS = {
    "common_parameters": ("common", "parameters"),
    "involved_parameters": ("involved", "parameters"),
    "interloper_parameters": ("interloper", "parameters"),
    "uninvolved_parameters": ("uninvolved", "parameters"),
    "involved_character_modifier": ("involved", "character"),
    "interloper_character_modifier": ("interloper", "character"),
    "all_county_modifier": ("common", "county"),
    "involved_county_modifier": ("involved", "county"),
    "interloper_county_modifier": ("interloper", "county"),
    "uninvolved_county_modifier": ("uninvolved", "county"),
    "involved_doctrine_character_modifier": ("involved", "doctrine"),
    "interloper_doctrine_character_modifier": ("interloper", "doctrine"),
}


def params_out(blk, unloc: set):
    out = []
    if not isinstance(blk, Block):
        return out
    for k, _op, v in blk:
        if k is None:
            continue
        text = wr.loc_chain(f"struggle_parameter_{k}")
        if text is None:
            unloc.add(k)
            text = k.replace("_", " ").capitalize()
        out.append({"key": k, "text": text})
    return out


def region_name(key):
    """Geographical regions mostly localize bare; unlocalized ones read best
    with their world_/ghw_region_/dlc_ plumbing prefixes stripped."""
    name = wr.loc_chain(key)
    if name:
        return name
    for pfx in ("world_", "ghw_region_", "custom_", "special_", "dlc_"):
        key = key.removeprefix(pfx)
    return key.replace("_", " ").title()


def main():
    catalyst_keys = {k for _p, k, _b in
                     ck3.parse_dir(ck3.COMMON / "struggle" / "catalysts")}
    unhandled = Counter()
    phase_unhandled = Counter()
    unloc_params = set()
    out = []

    for path, key, blk in ck3.parse_dir(ck3.COMMON / "struggle" / "struggles"):
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        phases = []
        phase_list = blk.get("phase_list")
        for pk, _op, pv in (phase_list or Block()):
            if pk is None or not isinstance(pv, Block):
                continue
            for k in pv.keys():
                if k not in PHASE_HANDLED and k not in SKIP_FIELDS:
                    phase_unhandled[k] += 1

            effects = []
            for group in EFFECT_GROUPS:
                gv = pv.get(group)
                if not isinstance(gv, Block):
                    continue
                buckets = []
                for fk, _o2, fv in gv:
                    if fk is None or fk == "name":
                        continue
                    if fk not in AUDIENCE_FIELDS:
                        phase_unhandled[f"{group}.{fk}"] += 1
                        continue
                    audience, kind = AUDIENCE_FIELDS[fk]
                    if kind == "parameters":
                        items = params_out(fv, unloc_params)
                    elif kind == "doctrine":
                        doctrine = fv.get("doctrine") if isinstance(fv, Block) else None
                        rest = Block([t for t in fv if t[0] != "doctrine"]) if isinstance(fv, Block) else fv
                        items = wr.mods_out(rest)
                        for it in items:
                            it["doctrine"] = doctrine
                    else:
                        items = wr.mods_out(fv)
                    if items:
                        buckets.append({"audience": audience, "kind": kind, "items": items})
                if buckets:
                    effects.append({
                        "group": group,
                        "name": wr.loc_chain(gv.get("name")) or group.replace("_", " ").title(),
                        "buckets": buckets,
                    })

            transitions = []
            fp = pv.get("future_phases")
            for tk, _o2, tv in (fp or Block()):
                if tk is None or not isinstance(tv, Block):
                    continue
                catalysts = []
                for ck, _o3, cv in (tv.get("catalysts") or Block()):
                    if ck is None:
                        continue
                    if ck not in catalyst_keys:
                        phase_unhandled[f"unknown_catalyst.{ck}"] += 1
                    catalysts.append({
                        "id": ck,
                        "name": wr.loc_chain(ck) or ck.removeprefix("catalyst_").replace("_", " ").capitalize(),
                        "desc": wr.loc_chain(f"{ck}_desc"),
                        "points": wr.value_out(cv),
                    })
                transitions.append({
                    "to": tk,
                    "toName": wr.loc_chain(tk) or tk.replace("_", " ").title(),
                    "default": bool(tv.get("default", False)),
                    "catalysts": catalysts,
                })

            decisions = [{"id": d, "name": wr.loc_chain(d) or d.replace("_", " ").title()}
                         for d in (pv.get("ending_decisions") or Block()).values()
                         if isinstance(d, str)]

            duration = pv.get("duration")
            phases.append({
                "id": pk,
                "name": wr.loc_chain(pk) or pk.replace("_", " ").title(),
                "desc": wr.loc_chain(f"{pk}_desc"),
                "ending": not effects and not transitions,
                "durationPoints": wr.value_out(duration.get("points")) if isinstance(duration, Block) and duration.has("points") else None,
                "effects": effects,
                "transitions": transitions,
                "endingDecisions": decisions,
            })

        def name_list(field, loc_fn):
            vals = [v for v in (blk.get(field) or Block()).values() if isinstance(v, str)]
            return [{"id": v, "name": loc_fn(v) or v.replace("_", " ").title()} for v in vals]

        rec = {
            "id": key,
            "name": wr.loc_chain(key),
            "desc": wr.loc_chain(f"game_concept_{key}_desc", f"{key}_desc"),
            "cultures": name_list("cultures", lambda v: wr.loc_chain(v, f"{v}_name")),
            "faiths": name_list("faiths", lambda v: wr.loc_chain(v)),
            "regions": name_list("regions", region_name),
            "involvementPct": blk.get("involvement_prerequisite_percentage"),
            "transitionDuration": wr.duration_text(blk.get("transition_state_duration")),
            "startPhase": blk.get("start_phase"),
            "phases": phases,
            "dlc": STRUGGLE_DLC.get(key),
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: r["id"])
    ck3.write_json("struggles.json", out)

    if unhandled:
        print("⚠ unhandled struggle fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    if phase_unhandled:
        print("⚠ unhandled struggle phase fields:")
        for k, n in phase_unhandled.most_common():
            print(f"    {k} ×{n}")
    if unloc_params:
        print(f"⚠ {len(unloc_params)} struggle parameters without loc: {sorted(unloc_params)[:8]}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ entries without localized names: {missing_names}")


if __name__ == "__main__":
    main()
