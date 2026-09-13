#!/usr/bin/env python3
"""Build src/data/genetics.json for the inheritance calculator.

Sources:

* the congenital subset of traits.json + the NChildbirth defines block — the
  chances are the game's own constants and the tiered-descent algorithm is
  documented in the defines comments, implemented client-side with provenance;
* the traits that are inherited WITHOUT being genetic (pure-blooded, inbred,
  the two poxes): they carry their own `inherit_chance` /
  `both_parent_has_trait_inherit_chance` instead of going through the
  dominant/recessive system;
* the Blood legacy perks, whose five modifiers scale those constants. The
  modifiers are multiplicative — `common/modifiers/00_event_modifiers.txt`
  documents it on `strong_blood`: "positive_random_genetic_chance = 4 # This
  will for instance cause a .2% chance to become 1%" (0.2 x (1 + 4) = 1).
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
    "TRAIT_REINFORCEMENT_CHANCE", "INBREEDING_ANCESTOR_GENERATIONS",
    "INBRED_RELATEDNESS_MULT", "PUREBLOODED_INBRED_RELATEDNESS_MULT",
]

# The modifiers the game exposes over congenital inheritance, split by what
# they touch. "inactive inheritance" is the recessive (carrier) table — the
# INACTIVE_TRAIT_CHANCE_* defines, whose ACTIVE_ACTIVE entry carries the
# comment "Deliberately over 100% so even if it is a bad trait, the modifiers
# to inheritance won't let you avoid it". There is no modifier for the active
# table. "random genetic" is the `birth` roll the game makes when inheritance
# fails; "strengthen" is TRAIT_REINFORCEMENT_CHANCE.
GENETIC_MODIFIER_KEYS = [
    "positive_random_genetic_chance", "negative_random_genetic_chance",
    "positive_inactive_inheritance_chance", "negative_inactive_inheritance_chance",
    "genetic_trait_strengthen_chance",
]

BLOOD_TRACK = "blood_legacy_track"

# Display order for the non-genetic inherited traits: the congenital pair
# first, then the inherited diseases, then the lineage honorifics.
CATEGORY_ORDER = ["physical", "health", "fame"]

# Concept text the page quotes rather than paraphrasing.
CONCEPT_KEYS = {"congenital": "game_concept_congenital_desc",
                "inbreeding": "game_concept_inbreeding_desc"}


def read_defines():
    text = (ck3.COMMON / "defines" / "00_defines.txt").read_text(encoding="utf-8-sig")
    constants = {}
    for k in DEFINE_KEYS:
        m = re.search(rf"^\s*{k}\s*=\s*([\d.]+)", text, re.M)
        if m:
            constants[k] = float(m.group(1))
    return constants


def trait_record(t):
    return {
        "id": t["id"], "name": t["name"], "level": t.get("level"),
        "good": bool(t["genetic"].get("good", False)),
        "birth": t["genetic"].get("birth"),
        "effects": [m["t"] for m in t["modifiers"]][:4]
        + [f"{v:+g} {k.title()}" for k, v in t.get("skills", {}).items()],
    }


def blood_legacy(by_id):
    """The Blood track's five perks, with the raw modifier values."""
    perks = []
    for _path, key, blk in ck3.parse_dir(ck3.COMMON / "dynasty_perks"):
        if blk.get("legacy") != BLOOD_TRACK:
            continue
        mods = {}
        for cm in blk.get_all("character_modifier"):
            for k, v in cm.items():
                if k in GENETIC_MODIFIER_KEYS:
                    mods[k] = v
        perk = {
            "id": key,
            "order": len(perks) + 1,
            "name": ck3.render_text(ck3.loc(f"{key}_name", key)),
            "mods": mods,
            "effects": [ck3.render_modifier(k, v) for k, v in mods.items()],
        }
        picks = blk.get("traits")
        if picks is not None:
            # blood_legacy_4: the dynasty picks one of these; the grant itself
            # lives in on_action/child_birth_on_actions.txt.
            chance, _ = ck3.resolve_value(ck3.script_values().get("blood_legacy_4_chance"))
            extra, _ = ck3.resolve_value(
                ck3.script_values().get("blood_legacy_4_extra_player_chance"))
            perk["pick"] = {
                "chance": chance, "playerExtra": extra,
                "traits": [{"id": k, "name": by_id.get(k, {}).get("name", k),
                            "good": bool(by_id.get(k, {}).get("genetic", {}).get("good", False))}
                           for k, _v in picks.items()],
            }
        perks.append(perk)
    perks.sort(key=lambda p: p["order"])
    return {
        "track": ck3.render_text(ck3.loc(f"{BLOOD_TRACK}_name", "Blood")),
        "perks": perks,
    }


def main():
    constants = read_defines()
    traits = json.loads((ck3.ROOT / "src/data/traits.json").read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in traits}

    genetic = [t for t in traits if t["genetic"].get("genetic")]
    # Inherited but not genetic: the game gives these a flat per-parent chance
    # instead of a dominant/recessive gene (traits/_traits.info: inherit_chance
    # "can not be set if a genetic trait").
    inherited = [t for t in traits
                 if t["genetic"].get("inherit_chance") and not t["genetic"].get("genetic")]

    families = {}
    standalone = []
    for t in genetic:
        rec = trait_record(t)
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

    inh = []
    for t in inherited:
        rec = trait_record(t)
        g = t["genetic"]
        rec["inherit"] = g["inherit_chance"]
        rec["both"] = g.get("both_parent_has_trait_inherit_chance")
        rec["sex"] = g.get("parent_inheritance_sex")
        # These traits carry no `good = yes` unless the file says so, and none
        # of them says `good = no`, so "bad" is read off the game's own
        # modifier colouring: a trait whose every modifier line is coloured bad
        # is bad, anything else stays neutral.
        pol = [m["p"] for m in by_id[t["id"]]["modifiers"]]
        rec["tone"] = ("good" if rec["good"]
                       else "bad" if pol and all(p == "bad" for p in pol)
                       else "neutral")
        rec["realFather"] = g.get("inherit_from_real_father")
        # `physical = yes` traits carry no `category`; the game files them
        # under the physical trait category all the same.
        cat = "physical" if g.get("physical") else t["category"]
        rec["category"] = cat
        rec["categoryName"] = ck3.render_text(
            ck3.loc(f"TRAIT_CATEGORY_{cat.upper()}", cat.title()))
        inh.append(rec)
    inh.sort(key=lambda r: (CATEGORY_ORDER.index(r["category"])
                            if r["category"] in CATEGORY_ORDER else 99,
                            not r["good"], r["name"]))

    ck3.write_json("genetics.json", {
        "constants": constants,
        "families": fams,
        "standalone": standalone,
        "inherited": inh,
        "bloodLegacy": blood_legacy(by_id),
        "concepts": {k: ck3.render_text(ck3.loc(v, "")) for k, v in CONCEPT_KEYS.items()},
    })


if __name__ == "__main__":
    main()
