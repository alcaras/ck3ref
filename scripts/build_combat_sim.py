#!/usr/bin/env python3
"""Build src/data/combat_sim.json — machine-readable combat inputs for the battle simulator.

Unlike traits.json (which renders commander bonuses as prose for the traits page),
the simulator needs the *raw numeric* combat modifier blocks. This script extracts:

- commanderTraits: per commander trait, the raw combat modifier leaves, split into
  `base` (unconditional), `cultureParams` (gated on a culture parameter), and
  `track` (cumulative XP-track steps 33/66/100). Only combat-relevant keys are kept
  (advantage family, combat-roll family, casualty/damage mults, martial/prowess, …).
- combatEffects: the common/combat_effects advantage table (rivers, straits, supply
  states, disembark, debt, gathering) — extracted for completeness; v1 UI may not use all.
- advantageDamageLadder: the advantage_damage_effect game-rule options (%/advantage point).
- namedModifiers: hardcoded combat modifiers applied by code (e.g. leading_own_troops = +5 adv).

Every emitted value carries no invented numbers — all sourced from the files below.
The `provenance` block records exactly where each dataset came from.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# ---------------------------------------------------------------------------
# Which modifier keys matter to battle resolution. Terrain-prefixed variants
# (hills_advantage, mountains_max_combat_roll, …) are matched by suffix.
# ---------------------------------------------------------------------------
COMBAT_KEY_SUFFIXES = ("_advantage", "_combat_roll", "_attrition_mult")
COMBAT_KEY_EXACT = {
    "advantage",
    "min_combat_roll", "max_combat_roll",
    "martial", "prowess",
    "enemy_hard_casualty_modifier", "hard_casualty_modifier", "hard_casualty_winter",
    "retreat_losses",
    "army_damage_mult", "army_toughness_mult", "army_pursuit_mult", "army_screen_mult",
    "knight_effectiveness_mult",
    "winter_movement_speed", "movement_speed", "character_travel_speed",
    "siege_phase_time",
    "no_water_crossing_penalty", "no_disembark_penalty",
    "counter_efficiency", "counter_resistance", "pursue_efficiency",
}


def is_combat_key(key):
    if key in COMBAT_KEY_EXACT:
        return True
    return any(key.endswith(sfx) for sfx in COMBAT_KEY_SUFFIXES)


def num(v):
    """Coerce a leaf to a number if it is one; yes/no -> True/False; else None."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(v, 4) if isinstance(v, float) else v
    if isinstance(v, str) and v in ("yes", "no"):
        return v == "yes"
    return None


def combat_leaves(blk):
    """Flat dict of {combat_key: number} directly under blk (non-recursive)."""
    out = {}
    if not isinstance(blk, Block):
        return out
    for k, _op, v in blk:
        if k is None or not is_combat_key(k):
            continue
        n = num(v)
        if n is not None:
            out[k] = n
    return out


def is_commander_trait(blk):
    if not isinstance(blk, Block):
        return False
    if blk.get("category") in ("commander", "winter_commander"):
        return True
    for _k, _op, v in blk:
        if _k == "flag" and v == "commander_trait_flag":
            return True
    return False


def extract_commander_trait(tid, blk):
    """base combat leaves + culture-parameter-gated leaves + cumulative track steps."""
    base = combat_leaves(blk)

    culture_params = {}
    for _k, _op, v in blk:
        if _k == "culture_modifier" and isinstance(v, Block):
            param = v.get("parameter")
            leaves = combat_leaves(v)
            if isinstance(param, str) and leaves:
                culture_params.setdefault(param, {}).update(leaves)

    track = {}
    tr = blk.get("track")
    if isinstance(tr, Block):
        for lvl, _op, lblk in tr:
            if lvl is not None and isinstance(lblk, Block):
                leaves = combat_leaves(lblk)
                if leaves:
                    track[str(lvl)] = leaves

    rec = {"id": tid, "name": ck3.render_text(ck3.loc(f"trait_{tid}") or tid),
           "category": blk.get("category") or "commander"}
    if base:
        rec["base"] = base
    if culture_params:
        rec["cultureParams"] = culture_params
    if track:
        rec["track"] = track
    return rec


def build_commander_traits():
    traits = ck3.parse_file(ck3.COMMON / "traits" / "00_traits.txt")
    out = []
    for tid, _op, blk in traits:
        if tid is None or not isinstance(blk, Block):
            continue
        if not is_commander_trait(blk):
            continue
        rec = extract_commander_trait(tid, blk)
        # keep only traits that actually carry combat numbers somewhere
        if any(k in rec for k in ("base", "cultureParams", "track")):
            out.append(rec)
    out.sort(key=lambda r: r["id"])
    return out


def build_combat_effects():
    blk = ck3.parse_file(ck3.COMMON / "combat_effects" / "00_combat_effects.txt")
    out = {}
    for key, _op, eff in blk:
        if key is None or not isinstance(eff, Block):
            continue
        adv = num(eff.get("advantage"))
        rec = {"advantage": adv if adv is not None else 0}
        if eff.get("adjacency") == "yes":
            rec["adjacency"] = True
        if eff.get("visible") == "no":
            rec["visible"] = False
        out[key] = rec
    return out


def build_advantage_ladder():
    """advantage_damage_effect_{1,2,5,7,10}: % extra damage per advantage point."""
    rules = ck3.parse_file(ck3.COMMON / "game_rules" / "00_game_rules.txt")
    blk = rules.get("advantage_damage_effect")
    options, default = [], None
    if isinstance(blk, Block):
        default_opt = blk.get("default")
        for k, _op, _v in blk:
            if isinstance(k, str) and k.startswith("advantage_damage_effect_"):
                pct = int(k.rsplit("_", 1)[1])
                options.append(pct)
        if isinstance(default_opt, str):
            default = int(default_opt.rsplit("_", 1)[1])
    options.sort()
    return {"pctPerAdvantageOptions": options, "default": default}


# Combat defines the simulator reads, by namespace. Values + dev comments are
# carried through verbatim so the engine never hardcodes a game number.
SIM_DEFINES = {
    "NCombat": [
        "MANEUVER_PHASE_DAYS", "COMBAT_ROLL_DAYS", "PURSUIT_PHASE_DAYS",
        "COMBAT_EVENT_DAYS", "MIN_DAYS_BEFORE_MANUAL_RETREAT",
        "DAMAGE_SCALING_FACTOR", "ADVANTAGE_DAMAGE_SCALING_FACTOR",
        "BASE_RATIO_CASUALTIES_CONVERSION", "BASE_RATIO_CASUALTIES_CONVERSION_PURSUIT",
        "BASE_WIDTH_RATIO", "MINIMUM_COMBAT_WIDTH",
        "COMMANDER_MIN_ROLL", "COMMANDER_MAX_ROLL",
        "MEN_AT_ARMS_MAX_COUNTER", "RATIO_FOR_MAX_COUNTER",
        "PURSUIT_STAT_TO_PURSUIT_DAMAGE", "BASE_TOUGHNESS_TO_PURSUIT",
        "MINIMUM_PURSUIT_DAMAGE",
        "LEVY_ATTACK", "LEVY_TOUGHNESS", "LEVY_SIEGE", "LEVY_PURSUIT", "LEVY_SCREEN",
        "KNIGHT_DAMAGE_PER_PROWESS", "KNIGHT_TOUGHNESS_PER_PROWESS",
    ],
    "NArmy": ["REGIMENT_DEFAULT_STACK_SIZE"],
}


def build_defines():
    rows = ck3.parse_file(ck3.COMMON / "defines" / "00_defines.txt")
    # 00_defines.txt is namespaced: top-level blocks keyed by NCombat, NArmy, ...
    out = {}
    missing = []
    for ns, keys in SIM_DEFINES.items():
        blk = rows.get(ns)
        for key in keys:
            val = blk.get(key) if isinstance(blk, Block) else None
            if val is None:
                missing.append(f"{ns}.{key}")
                continue
            n = num(val)
            out[key] = {"ns": ns, "value": n if n is not None else val}
    if missing:
        raise SystemExit(f"build_combat_sim: defines not found (game update?): {missing}")
    return out


# ---------------------------------------------------------------------------
# Era / innovation men-at-arms upgrades. Men-at-arms scale as a culture advances:
# both the culture eras themselves and individual innovations carry `maa_upgrade`
# blocks that add flat stat deltas to a base type or a specific unit. These are
# CUMULATIVE across eras (e.g. longbowmen gain +10 damage in each medieval era).
# ---------------------------------------------------------------------------
UPGRADE_STAT_KEYS = {
    "damage": "damage", "toughness": "toughness",
    "pursue": "pursuit", "pursuit": "pursuit",  # schema uses `pursue`; accept both
    "screen": "screen", "siege_value": "siege_value", "max_size": "max_size",
}


def parse_upgrade(blk):
    """A maa_upgrade block -> {target key, deltas}. Target is a unit id or a base type."""
    if not isinstance(blk, Block):
        return None
    rec = {}
    maa = blk.get("men_at_arms")
    typ = blk.get("type")
    if isinstance(maa, str):
        rec["men_at_arms"] = maa
    elif isinstance(typ, str):
        rec["type"] = typ
    else:
        return None
    for src, dst in UPGRADE_STAT_KEYS.items():
        v = num(blk.get(src))
        if isinstance(v, (int, float)):
            rec[dst] = v
    # keep only if it carries at least one stat delta
    return rec if len(rec) > 1 else None


def build_era_upgrades():
    """Ordered eras + the maa_upgrades introduced at each (era blocks + innovations)."""
    eras_file = ck3.parse_file(ck3.COMMON / "culture" / "eras" / "00_culture_eras.txt")
    order = []          # [(year, era_key)]
    by_era = {}         # era_key -> [upgrade, ...]
    for key, _op, blk in eras_file:
        if key is None or not isinstance(blk, Block):
            continue
        year = num(blk.get("year"))
        order.append((year if isinstance(year, (int, float)) else 9999, key))
        ups = [u for u in (parse_upgrade(b) for b in blk.get_all("maa_upgrade")) if u]
        by_era.setdefault(key, []).extend(ups)

    # innovation upgrades, filed under the innovation's culture_era. Only GLOBAL
    # innovations are applied: regional ones (silk-road / region-gated, flagged
    # *_regional) require a specific region/culture and would over-buff a generic
    # army, so they are skipped. The era model thus represents a standard,
    # fully-teched culture. (Era-block upgrades above are unconditional and always apply.)
    for _path, _iid, blk in ck3.parse_dir(ck3.COMMON / "culture" / "innovations"):
        if isinstance(blk, Tagged):
            blk = blk.block
        if not isinstance(blk, Block):
            continue
        era = blk.get("culture_era")
        if not isinstance(era, str):
            continue
        flags = [f for f in blk.get_all("flag") if isinstance(f, str)]
        if any("regional" in f for f in flags):
            continue  # region/silk-road-gated, not universal
        ups = [u for u in (parse_upgrade(b) for b in blk.get_all("maa_upgrade")) if u]
        if ups:
            by_era.setdefault(era, []).extend(ups)

    order.sort()
    era_order = [k for _y, k in order]
    # ensure every era key referenced has a (possibly empty) list, in order
    return {
        "order": era_order,
        "byEra": {k: by_era.get(k, []) for k in era_order},
    }


def build_terrain_weights():
    """Province counts per terrain — the CK3 map's terrain distribution.

    Source: common/province_terrain/00_province_terrain.txt (`<province_id>=<terrain>`).
    Only real numbered provinces are counted (the `default_*` fallbacks are skipped);
    sea/coastal_sea don't appear among land provinces. Used to weight a battle's outcome
    by how common each terrain actually is on the map.
    """
    path = ck3.COMMON / "province_terrain" / "00_province_terrain.txt"
    counts = {}
    # `<id>=<terrain>`, tolerating trailing whitespace or a `#comment` (309 lines have one)
    line_re = re.compile(r"^\s*(\d+)\s*=\s*([a-z_]+)\s*(?:#.*)?$")
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = line_re.match(line)
        if not m:
            continue
        terrain = m.group(2)
        if terrain in ("sea", "coastal_sea", "lakes"):
            continue
        counts[terrain] = counts.get(terrain, 0) + 1
    total = sum(counts.values())
    return {"counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])), "total": total}


def build_named_modifiers():
    """Hardcoded combat modifiers applied by engine code (not by any entity)."""
    blk = ck3.parse_file(ck3.COMMON / "modifiers" / "00_war_and_combat_modifiers.txt")
    out = {}
    for key, _op, mblk in blk:
        if key is None or not isinstance(mblk, Block):
            continue
        leaves = combat_leaves(mblk)
        if leaves:
            out[key] = leaves
    return out


def main():
    data = {
        "defines": build_defines(),
        "eraUpgrades": build_era_upgrades(),
        "terrainWeights": build_terrain_weights(),
        "commanderTraits": build_commander_traits(),
        "combatEffects": build_combat_effects(),
        "advantageDamageLadder": build_advantage_ladder(),
        "namedModifiers": build_named_modifiers(),
        "provenance": {
            "defines": "defines:common/defines/00_defines.txt (NCombat, NArmy)",
            "eraUpgrades": "script:common/culture/eras/00_culture_eras.txt + common/culture/innovations/*.txt (maa_upgrade, cumulative)",
            "terrainWeights": "map:common/province_terrain/00_province_terrain.txt (land province counts)",
            "commanderTraits": "script:common/traits/00_traits.txt (category=commander/winter_commander)",
            "combatEffects": "script:common/combat_effects/00_combat_effects.txt",
            "advantageDamageLadder": "script:common/game_rules/00_game_rules.txt#advantage_damage_effect",
            "namedModifiers": "script:common/modifiers/00_war_and_combat_modifiers.txt",
        },
    }
    ck3.write_json("combat_sim.json", data)
    print(f"  defines: {len(data['defines'])}"
          f"  commanderTraits: {len(data['commanderTraits'])}"
          f"  combatEffects: {len(data['combatEffects'])}"
          f"  namedModifiers: {len(data['namedModifiers'])}"
          f"  advantageLadder: {data['advantageDamageLadder']['pctPerAdvantageOptions']}")


if __name__ == "__main__":
    main()
