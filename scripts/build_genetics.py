#!/usr/bin/env python3
"""Build src/data/genetics.json for the inheritance calculator.

Sources: the congenital subset of traits.json + the NChildbirth defines block
(chances are the game's own constants; the tiered-descent algorithm is
documented in the defines comments and implemented client-side with
provenance notes).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

DEFINE_KEYS = [
    "ACTIVE_TRAIT_CHANCE_ACTIVE_ACTIVE", "ACTIVE_TRAIT_CHANCE_ACTIVE_INACTIVE",
    "ACTIVE_TRAIT_CHANCE_ACTIVE_NONE", "ACTIVE_TRAIT_CHANCE_INACTIVE_INACTIVE",
    "ACTIVE_TRAIT_CHANCE_INACTIVE_NONE", "INACTIVE_TRAIT_CHANCE_ACTIVE_ACTIVE",
    "INACTIVE_TRAIT_CHANCE_ACTIVE_INACTIVE", "INACTIVE_TRAIT_CHANCE_ACTIVE_NONE",
    "INACTIVE_TRAIT_CHANCE_INACTIVE_INACTIVE", "INACTIVE_TRAIT_CHANCE_INACTIVE_NONE",
    "MATCHED_TRAIT_DIFFERENCE_MULT", "TIER_TRAIT_REDUCTION_MULT",
    "TRAIT_REINFORCEMENT_CHANCE",
]


def main():
    text = (ck3.COMMON / "defines" / "00_defines.txt").read_text(encoding="utf-8-sig")
    constants = {}
    for k in DEFINE_KEYS:
        m = re.search(rf"^\s*{k}\s*=\s*([\d.]+)", text, re.M)
        if m:
            constants[k] = float(m.group(1))

    traits = json.loads((ck3.ROOT / "src/data/traits.json").read_text(encoding="utf-8"))
    genetic = [t for t in traits if t["genetic"].get("genetic")]

    families = {}
    standalone = []
    for t in genetic:
        rec = {"id": t["id"], "name": t["name"], "level": t.get("level"),
               "good": bool(t["genetic"].get("good", False)),
               "birth": t["genetic"].get("birth"),
               "effects": [m["t"] for m in t["modifiers"]][:4]
               + [f"{v:+g} {k.title()}" for k, v in t.get("skills", {}).items()]}
        g = t.get("group")
        if g:
            families.setdefault(g, {"key": g, "levels": []})["levels"].append(rec)
        else:
            standalone.append(rec)

    fams = []
    for g, f in sorted(families.items()):
        f["levels"].sort(key=lambda r: r["level"] or 0)
        f["good"] = f["levels"][0]["good"]
        f["name"] = g.replace("_", " ").title()
        fams.append(f)
    standalone.sort(key=lambda r: (not r["good"], r["name"]))

    ck3.write_json("genetics.json", {
        "constants": constants,
        "families": fams,
        "standalone": standalone,
    })


if __name__ == "__main__":
    main()
