#!/usr/bin/env python3
"""Constants that govern changing a culture, read from the game.

Sources (every value is traced, none invented):
  defines NCulture   — DEFAULT_MAX_TRADITIONS, reformation progress + cap
  script_values/00_culture_values.txt — hybridization threshold chain,
                       hybrid/divergence/tradition cooldowns, tradition costs
  culture/traditions  — which traditions carry the hybridization parameters
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

DEFINES = ck3.COMMON / "defines" / "00_defines.txt"
CULTURE_VALUES = ck3.COMMON / "script_values" / "00_culture_values.txt"

DEFINE_KEYS = [
    "DEFAULT_MAX_TRADITIONS",
    "REFORMATION_PROGRESS_GAIN_BASE",
    "REFORMATION_PROGRESS_SLOWDOWN_PER_COUNTY_WITH_CULTURE",
    "REFORMATION_PROGRESS_REPLACE_TRADITION_MULT",
    "REFORMATION_MAX_YEARS",
]
# script_value name -> the flat number it resolves to
VALUE_KEYS = [
    "hybridization_threshold_flat_number_value",
    "tradition_base_cost", "tradition_incompatible_ethos_penalty",
    "tradition_unfulfilled_criteria_penalty",
]


def main():
    text = DEFINES.read_text(encoding="utf-8-sig", errors="replace")
    defines = {}
    for k in DEFINE_KEYS:
        m = re.search(rf"^\s*{k}\s*=\s*([\d.]+)", text, re.M)
        if m:
            defines[k] = float(m.group(1))

    cv = CULTURE_VALUES.read_text(encoding="utf-8-sig", errors="replace")
    values = {}
    for k in VALUE_KEYS:
        m = re.search(rf"^{k}\s*=\s*([\d.]+)", cv, re.M)
        if m:
            values[k] = float(m.group(1))
        else:
            n, _r = ck3.resolve_value(k)
            if n is not None:
                values[k] = n

    def cooldown(name):
        """base value of a *_cooldown script value (game-rule branches aside)"""
        m = re.search(rf"^{name}\s*=\s*\{{\s*\n\s*value\s*=\s*([\d.]+)", cv, re.M)
        return float(m.group(1)) if m else None

    cooldowns = {
        "hybrid": cooldown("culture_hybrid_cooldown"),
        "divergence": cooldown("culture_divergence_cooldown"),
        "addTradition": cooldown("add_tradition_cooldown"),
    }

    # Which traditions move the hybridization threshold, and by how much —
    # the multipliers come from hybridization_threshold_value's own branches.
    tags = {"easier_to_hybridize": 0.5, "harder_to_hybridize": 2.0}
    by_param = {p: [] for p in tags}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "culture" / "traditions"):
        params = blk.get("parameters")
        if not hasattr(params, "items"):
            continue
        for pk, pv in params.items():
            if pk in tags and pv is True:
                by_param[pk].append({
                    "id": key,
                    "name": ck3.render_text(ck3.loc(f"{key}_name") or key),
                })

    ck3.write_json("culture-rules.json", {
        "defines": defines,
        "values": values,
        "cooldownYears": cooldowns,
        "hybridization": {
            "base": values.get("hybridization_threshold_flat_number_value"),
            "multipliers": tags,
            "traditions": by_param,
            "note": ("Threshold is cultural acceptance between the two cultures. "
                     "Multipliers stack: your culture's own parameter, the target "
                     "culture's, struggle phases, and Kurultai influence all apply, "
                     "clamped to 0-100."),
        },
    })
    print(f"  defines {len(defines)}, values {len(values)}, "
          f"easier {len(by_param['easier_to_hybridize'])}, "
          f"harder {len(by_param['harder_to_hybridize'])}")


if __name__ == "__main__":
    main()
