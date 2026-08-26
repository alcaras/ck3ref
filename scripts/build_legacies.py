#!/usr/bin/env python3
"""Build src/data/legacies.json from common/dynasty_legacies + common/dynasty_perks.

Tracks are containers (is_shown gate only); each perk names its track via
`legacy =`. Perk order within a track is definition order in the script files
(the game relies on it: ep2 defines perk 2 before perk 1 to reorder them), so
we number 1..5 by position, not by key suffix.

Perk effect text: `custom_description*` / `custom_tooltip` keys resolve either
directly in loc or through common/effect_localization (key -> global/first/
third -> loc). There is no generated `<perk>_desc` loc key — the effect texts
ARE the perk description.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Track fields we deliberately do not render, with reasons.
TRACK_SKIP_FIELDS = {}
TRACK_HANDLED_FIELDS = {"is_shown"}

PERK_SKIP_FIELDS = {
    "ai_chance": "AI selection weight, not player-facing",
    "can_be_picked": "scripted-trigger macro mirroring the track's is_shown gate / DLC check",
    "trait": "single-trait grant form; unused by any shipped perk",
}
PERK_HANDLED_FIELDS = {
    "legacy", "character_modifier", "doctrine_character_modifier", "effect", "traits",
}

# Modifier-block keys that are not display modifiers.
MOD_SKIP_KEYS = {"name"}  # internal modifier identity, no display value
AI_MOD_PREFIX = "ai_"     # ai_boldness etc. — AI personality weights, hidden in game

# government_has_flag values have no loc (CLAUDE.md quirk); hand-labelled.
GOV_FLAG_LABELS = {
    "government_is_nomadic": "Nomadic government",
    "government_is_administrative": "Administrative government",
    "government_is_mandala": "Mandala government",
    "government_is_wanua": "Wanua government",
    "government_is_japan_administrative": "Japanese administrative government",
    "government_is_japan_feudal": "Japanese feudal government",
    "government_is_celestial": "Celestial government",
    "government_has_merit": "Meritocratic or Celestial government",
}

# The three head-of-faith doctrines localize as bare "None/Spiritual/Temporal".
HEAD_DOCTRINE_LABELS = {
    "doctrine_no_head": "No Head of Faith",
    "doctrine_spiritual_head": "Spiritual Head of Faith",
    "doctrine_temporal_head": "Temporal Head of Faith",
}

# Data functions with no static answer that we substitute editorially
# (ep2_activities_legacy_2_name reads "Traditional <dynasty> Weddings").
_DYNASTY_NAME_FN = re.compile(r"\[GetPlayer\.GetDynasty\.GetBaseName\w*\]")

_unresolved_texts: list[str] = []


def render_loc(s):
    if not isinstance(s, str):
        return None
    return ck3.render_text(_DYNASTY_NAME_FN.sub("Dynasty", s)) or None


# --- effect_localization chain ---------------------------------------------

_effect_loc: dict | None = None


def effect_loc_map():
    global _effect_loc
    if _effect_loc is None:
        _effect_loc = {}
        for _p, key, blk in ck3.parse_dir(ck3.COMMON / "effect_localization"):
            if isinstance(blk, Block):
                _effect_loc[key] = blk
    return _effect_loc


def effect_text(key):
    """A custom_description/custom_tooltip text key -> rendered display text."""
    raw = ck3.loc(key)
    if raw is None:
        el = effect_loc_map().get(key)
        if isinstance(el, Block):
            for slot in ("global", "first", "third"):
                v = el.get(slot)
                if isinstance(v, str) and ck3.loc(v) is not None:
                    raw = ck3.loc(v)
                    break
    if raw is None:
        # implicit effect-localization: loc keys named <key>_global/_first/_third
        for slot in ("global", "first", "third"):
            raw = ck3.loc(f"{key}_{slot}")
            if raw is not None:
                break
    if raw is None:
        _unresolved_texts.append(key)
        return None
    return render_loc(raw)


# --- trigger description (shallow, for gates and effect `if` limits) --------

def describe_limit(limit):
    """Short display text for an effect `if = { limit = … }` condition."""
    parts = []
    if isinstance(limit, Block):
        for k, _op, v in limit:
            if k == "government_has_flag" and v in GOV_FLAG_LABELS:
                parts.append(GOV_FLAG_LABELS[v])
            elif k == "has_dlc_feature" and v in ck3.FEATURE_TO_DLC:
                parts.append(f"with {ck3.FEATURE_TO_DLC[v]}")
            elif isinstance(v, (Block, Tagged)):
                parts.append(f"{k} …")
            else:
                parts.append(f"{k} {v}")
    return ", ".join(parts) if parts else None


def gate_atoms(trigger, atoms):
    """Collect the player-meaningful availability conditions from is_shown.

    Uniformly skipped escape valves (reported once, not per track): the
    unrestricted_dynasty_legacies game rules, is_ai, and the
    has_dynasty_perk self-reference that keeps a started track visible.
    """
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k == "government_has_flag" and v in GOV_FLAG_LABELS:
            atoms.append(GOV_FLAG_LABELS[v])
        elif k == "has_cultural_pillar" and isinstance(v, str):
            name = render_loc(ck3.loc(v)) or v.removeprefix("heritage_").replace("_", " ").title()
            atoms.append(f"{name} heritage")
        elif k == "this" and isinstance(v, str) and v.startswith("culture:"):
            atoms.append(f"{v.removeprefix('culture:').title()} culture")
        elif k == "is_struggle_type" and isinstance(v, str):
            stem = v.removesuffix("_struggle").replace("_", " ").title()
            atoms.append(f"involved in the {stem} Struggle")
        elif k == "geographical_region" and isinstance(v, str):
            stem = v.rsplit("_", 1)[-1].title()
            atoms.append(f"capital in {stem}")
        elif isinstance(v, (Block, Tagged)):
            gate_atoms(v, atoms)


def track_gate(is_shown):
    atoms = []
    gate_atoms(is_shown, atoms)
    seen, out = set(), []
    for a in atoms:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return " or ".join(out) or None


# --- perk effect lines -------------------------------------------------------

_ZERO_MAG = re.compile(r"^([+-])0(%?) ")


def modifier_line(k, v):
    line = ck3.render_modifier(k, v)
    # a nonzero float squashed to "+0"/"-0" by a 0-decimals format: re-render
    if isinstance(v, float) and v != 0 and _ZERO_MAG.match(line):
        fmt = ck3.modifier_formats().get(k, {})
        num = v * 100 if fmt.get("percent") and not fmt.get("already_percent") else v
        mag = f"{num:+.2f}".rstrip("0").rstrip(".")
        pct = "%" if fmt.get("percent") or fmt.get("already_percent") else ""
        line = f"{mag}{pct} {ck3.modifier_name(k)}"
    return line


def modifier_lines(blk, skipped):
    lines = []
    if not isinstance(blk, Block):
        return lines
    for k, _op, v in blk:
        if k is None or k in MOD_SKIP_KEYS:
            continue
        if k.startswith(AI_MOD_PREFIX):
            skipped[f"modifier:{k}"] += 1
            continue
        if isinstance(v, str):
            n, _rules = ck3.resolve_value(v)
            if n is not None:
                v = n
        lines.append(modifier_line(k, v))
    return lines


def doctrine_label(key):
    if key in HEAD_DOCTRINE_LABELS:
        return HEAD_DOCTRINE_LABELS[key]
    return render_loc(ck3.loc(f"{key}_name") or ck3.loc(key)) or key


def effect_lines(blk, skipped, prefix=None):
    """Walk an effect block collecting player-facing text lines."""
    lines = []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return lines

    def add(text):
        if not text:
            return
        # multi-line loc strings are separate bullet lines in the game tooltip
        for part in (s.strip() for s in text.split("\n")):
            if part:
                lines.append(f"{prefix}: {part}" if prefix else part)

    for k, _op, v in blk:
        if k in ("custom_description_no_bullet", "custom_description"):
            key = v.get("text") if isinstance(v, Block) else v
            if isinstance(key, str):
                add(effect_text(key))
        elif k == "custom_tooltip":
            key = v.get("text") if isinstance(v, Block) else v
            if isinstance(key, str):
                add(effect_text(key))
        elif k == "if" and isinstance(v, Block):
            cond = describe_limit(v.get("limit"))
            sub_prefix = cond if not prefix else f"{prefix}; {cond}"
            inner = Block([t for t in v.triples if t[0] != "limit"])
            lines.extend(effect_lines(inner, skipped, sub_prefix))
        elif k == "else" and isinstance(v, Block):
            lines.extend(effect_lines(v, skipped, "Otherwise"))
        elif k == "show_as_tooltip":
            lines.extend(effect_lines(v, skipped, prefix))
        elif k == "create_legend_seed" and isinstance(v, Block):
            quality = str(v.get("quality", "")).title()
            ltype = str(v.get("type", "")).title()
            add(f"Create a {quality} {ltype} legend seed about the dynasty".replace("  ", " "))
        elif k in ("hidden_effect",):
            skipped[f"effect:{k}"] += 1  # not shown in the game tooltip either
        elif k == "root" and isinstance(v, Block):
            lines.extend(effect_lines(v, skipped, prefix))
        elif k is not None:
            skipped[f"effect:{k}"] += 1
    return lines


def trait_line(traits):
    """`traits = { x = weight … }` — selectable trait on unlock; weights are AI-only."""
    names = []
    for k, _op, _v in traits:
        if k is None:
            continue
        name = render_loc(ck3.loc(f"trait_{k}") or ck3.loc(k)) or k.replace("_", " ").title()
        if name not in names:
            names.append(name)
    return "Selectable trait: " + ", ".join(names) if names else None


def main():
    unhandled = Counter()
    skipped_inner = Counter()

    # tracks, keyed; definition order preserved (files load alphabetically)
    tracks = []
    track_by_id = {}
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "dynasty_legacies"):
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in TRACK_HANDLED_FIELDS and k not in TRACK_SKIP_FIELDS:
                unhandled[f"track:{k}"] += 1
        dlc, features = ck3.dlc_tag(path, blk)
        rec = {
            "id": key,
            "name": render_loc(ck3.loc(f"{key}_name")),
            "desc": render_loc(ck3.loc(f"{key}_desc")),
            "dlc": dlc,
            "features": features,
            "gate": track_gate(blk.get("is_shown")),
            "icon": key,  # gfx/interface/icons/dynasty/<track>.dds, 1:1
            "perks": [],
            "sourceFile": path.name,
        }
        tracks.append(rec)
        track_by_id[key] = rec

    for path, key, blk in ck3.parse_dir(ck3.COMMON / "dynasty_perks"):
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in PERK_HANDLED_FIELDS and k not in PERK_SKIP_FIELDS:
                unhandled[f"perk:{k}"] += 1
        track = track_by_id.get(blk.get("legacy"))
        if track is None:
            unhandled[f"perk-orphan:{key}"] += 1
            continue
        effects = []
        for mod in blk.get_all("character_modifier"):
            effects.extend(modifier_lines(mod, skipped_inner))
        for mod in blk.get_all("doctrine_character_modifier"):
            if not isinstance(mod, Block):
                continue
            label = doctrine_label(str(mod.get("doctrine")))
            inner = Block([t for t in mod.triples if t[0] not in ("doctrine",)])
            effects.extend(f"If {label} doctrine: {line}"
                           for line in modifier_lines(inner, skipped_inner))
        for eff in blk.get_all("effect"):
            effects.extend(effect_lines(eff, skipped_inner))
        traits = blk.get("traits")
        if isinstance(traits, Block):
            line = trait_line(traits)
            if line:
                effects.append(line)
        track["perks"].append({
            "id": key,
            "name": render_loc(ck3.loc(f"{key}_name")),
            "desc": None,  # the game generates no <perk>_desc key; effects carry the text
            "order": len(track["perks"]) + 1,
            "effects": effects,
        })

    # display order: the seven base-game tracks first, then DLC tracks,
    # each group in definition order
    out = [t for t in tracks if not t["dlc"]] + [t for t in tracks if t["dlc"]]

    # Perk cost is global across ALL tracks, not per track:
    #   COST = PERK_COST_BASE + (perks already unlocked * PERK_COST_MULTIPLIER)
    # (the game states this formula in the defines comment itself)
    import re as _re
    _defines = (ck3.COMMON / "defines" / "00_defines.txt").read_text(
        encoding="utf-8-sig", errors="replace")
    def _define(name, fallback):
        m = _re.search(rf"^\s*{name}\s*=\s*([\d.]+)", _defines, _re.M)
        return float(m.group(1)) if m else fallback
    ck3.write_json("legacy-costs.json", {
        "base": _define("PERK_COST_BASE", 250),
        "perStep": _define("PERK_COST_MULTIPLIER", 500),
        "formula": "base + (perks already unlocked x perStep), counted across every track",
    })
    ck3.write_json("legacies.json", out)

    problems = False
    for t in out:
        if len(t["perks"]) != 5:
            print(f"⚠ track {t['id']} has {len(t['perks'])} perks (expected 5)")
            problems = True
    missing = [t["id"] for t in out if not t["name"]] + \
              [p["id"] for t in out for p in t["perks"] if not p["name"]]
    if missing:
        print(f"⚠ entries without localized names: {missing}")
        problems = True
    empty = [p["id"] for t in out for p in t["perks"] if not p["effects"]]
    if empty:
        print(f"⚠ perks with no rendered effects: {empty}")
    if unhandled:
        print("⚠ unhandled legacy fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
        problems = True
    if skipped_inner:
        print("  (consciously skipped inner keys: "
              + ", ".join(f"{k}×{n}" for k, n in sorted(skipped_inner.items())) + ")")
    if _unresolved_texts:
        print(f"⚠ unresolved effect text keys: {_unresolved_texts}")
        problems = True
    unres = ck3.unresolved_report()
    if unres:
        print(f"  ({len(unres)} unresolved loc functions inside rendered text)")
    missing_fmt = ck3.missing_modifier_report()
    if missing_fmt:
        print(f"  (modifier keys without format/loc, generic fallback: {missing_fmt})")
    if not problems:
        print("  legacy build clean")


if __name__ == "__main__":
    main()
