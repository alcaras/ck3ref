#!/usr/bin/env python3
"""Build src/data/epidemics.json from common/epidemics/.

Schema documented in _epidemics.info. Per disease: the disease trait
(symptoms/lethality live on the trait), character infection chance, province
infection-level modifiers, and the three outbreak intensities with chance,
spread, extent and duration numbers.

DLC provenance is negation-aware: base-game diseases mention
`legends_of_the_dead` only inside NOT-compensation branches ("make up for the
locked diseases"); the one disease locked behind the DLC (bubonic plague)
references it positively.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import world_render as wr
from ck3 import Block

SKIP_FIELDS = {
    "color": "map tint",
    "shader_data": "map shader parameters",
    "on_start": "event scripting (legitimacy hit, Black Death globals)",
    "on_end": "event scripting",
    "on_monthly": "event scripting",
    "on_character_infected": "notification scripting",
    "on_province_infected": "event scripting (development loss handled via "
                            "levels; Black Death story cycle)",
    "on_province_recovered": "cooldown bookkeeping + prosperity event",
    "can_infect_character": "generic can_contract/immunity plumbing "
                            "(uniform across diseases)",
    "priority": "map display priority",
}

HANDLED_FIELDS = {"trait", "name", "character_infection_chance",
                  "infection_levels", "outbreak_intensities"}

INTENSITY_HANDLED = {"outbreak_chance", "spread_chance", "max_provinces",
                     "infection_duration", "infection_progress_duration",
                     "infection_recovery_duration"}
INTENSITY_SKIP = {
    "notification": "custom notification routing (Black Death)",
    "global_notification": "notification routing",
}

LEVEL_MODS = ("province_modifier", "county_modifier", "realm_modifier")


def main():
    unhandled = Counter()
    out = []

    for path, key, blk in ck3.parse_dir(ck3.COMMON / "epidemics"):
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        # negation-aware DLC derivation (see module docstring)
        pos, _neg = wr.scan_dlc_features_negation_aware(blk)
        dlc = None
        for f in pos:
            if f in ck3.FEATURE_TO_DLC:
                dlc = ck3.FEATURE_TO_DLC[f]
                break

        name = wr.loc_chain(f"epidemic_{key}", f"trait_{key}")
        fallback_desc = wr.last_desc_key(blk.get("name"))
        if not name and fallback_desc:
            name = wr.loc_chain(fallback_desc)

        levels = []
        for lk, _op, lv in (blk.get("infection_levels") or Block()):
            if lk is None or not isinstance(lv, Block):
                continue
            for k in lv.keys():
                if k not in LEVEL_MODS:
                    unhandled[f"level.{k}"] += 1
            n, _r = ck3.resolve_value(lk) if isinstance(lk, str) else (lk, None)
            levels.append({
                "threshold": wr.num(n) if n is not None else lk,
                **{m.split("_")[0] + "Modifiers": wr.mods_out(lv.get(m))
                   for m in LEVEL_MODS if lv.has(m)},
            })

        intensities = []
        for ik, _op, iv in (blk.get("outbreak_intensities") or Block()):
            if ik is None or not isinstance(iv, Block):
                continue
            for k in iv.keys():
                if k not in INTENSITY_HANDLED and k not in INTENSITY_SKIP:
                    unhandled[f"intensity.{k}"] += 1
            intensities.append({
                "intensity": ik,
                "name": wr.loc_chain(f"epidemic_level_{ik}") or ik.title(),
                "outbreakChance": wr.value_out(iv.get("outbreak_chance")),
                "spreadChance": wr.value_out(iv.get("spread_chance")),
                "maxProvinces": wr.range_text(iv.get("max_provinces")),
                "infectionDuration": wr.duration_text(iv.get("infection_duration")),
                "progressDuration": wr.duration_text(iv.get("infection_progress_duration")),
                "recoveryDuration": wr.duration_text(iv.get("infection_recovery_duration")),
            })

        trait = blk.get("trait")
        rec = {
            "id": key,
            "name": name,
            "trait": trait,
            "traitName": wr.loc_chain(f"trait_{trait}") if trait else None,
            "infectionChance": wr.value_out(blk.get("character_infection_chance")),
            "levels": levels,
            "intensities": intensities,
            "icon": key,
            "dlc": dlc,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: r["id"])
    ck3.write_json("epidemics.json", out)

    if unhandled:
        print("⚠ unhandled epidemic fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ entries without localized names: {missing_names}")


if __name__ == "__main__":
    main()
