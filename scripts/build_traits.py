#!/usr/bin/env python3
"""Build src/data/traits.json — all 301 traits.

Field classification is data-driven: a top-level key is a modifier line iff it
appears in modifier_definition_formats (plus a small KNOWN_MODIFIER_EXTRA set
the formats file omits); everything else must be a known meta field or it is
reported unhandled.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKILLS = ("diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess")

# Modifier-like keys missing from modifier_definition_formats but rendered by
# the game on trait tooltips.
KNOWN_MODIFIER_EXTRA = {
    "health", "elderly_health", "child_health", "negate_health_penalty_add",
}

META_HANDLED = {
    "category", "desc", "icon", "name", "opposites", "compatibility", "group",
    "group_equivalence", "level", "flag", "ruler_designer_cost",
    "shown_in_ruler_designer", "shown_in_encyclopedia", "minimum_age",
    "maximum_age", "valid_sex", "genetic", "physical", "good", "birth",
    "random_creation", "random_creation_weight", "inherit_chance",
    "both_parent_has_trait_inherit_chance", "enables_inbred",
    "inheritance_blocker", "claim_inheritance_blocker", "can_have_children",
    "incapacitating", "immortal", "genetic_constraint_all",
    "genetic_constraint_men", "genetic_constraint_women",
    "parent_inheritance_sex", "inherit_from_real_father", "bastard",
    "same_opinion", "opposite_opinion", "same_opinion_if_same_faith",
    "triggered_opinion", "culture_modifier", "faith_modifier",
    "government_modifier", "track", "tracks", "add_commander_trait",
    "disables_combat_leadership", "culture_succession_prio",
    "trait_exclusive_if_realm_contains", "index",
}

SKIP_META = {
    "portrait_extremity_shift": "portrait genetics rendering",
    "ugliness_portrait_extremity_shift": "portrait genetics rendering",
}

OPINION_FIELDS = {"same_opinion": "Same trait opinion",
                  "opposite_opinion": "Opposite trait opinion",
                  "same_opinion_if_same_faith": "Same trait & faith opinion"}


def is_modifier_key(k):
    if k.startswith("ai_"):
        return False  # AI personality weights — not player-facing
    return k in ck3.modifier_formats() or k in KNOWN_MODIFIER_EXTRA or k.endswith("_opinion")


def modifier_lines(block, skills=None, exclude=frozenset()):
    """Render every modifier triple in a Block; optionally split out skills."""
    lines = []
    for k, _op, v in block:
        if k is None or isinstance(v, (Block, Tagged)) or k in exclude:
            continue
        if skills is not None and k in SKILLS and isinstance(v, (int, float)):
            skills[k] = skills.get(k, 0) + v
            continue
        if is_modifier_key(k):
            if k.endswith("_opinion") and k not in ck3.modifier_formats():
                base = k.removesuffix("_opinion").replace("_", " ").title()
                lines.append({"t": f"{v:+g} {base} opinion",
                              "p": "good" if isinstance(v, (int, float)) and v > 0 else "bad"})
            else:
                lines.append({"t": ck3.render_modifier(k, v),
                              "p": ck3.modifier_polarity(k, v)})
    return lines


def conditional_modifiers(blk, field):
    out = []
    for cm in blk.get_all(field):
        if not isinstance(cm, Block):
            continue
        param = cm.get("parameter") or cm.get("doctrine") or cm.get("govt")
        label = None
        if isinstance(param, str):
            label = (ck3.render_text(ck3.loc(f"culture_parameter_{param}") or "")
                     or param.replace("_", " ").title())
        lines = modifier_lines(cm)
        if lines:
            out.append({"condition": label or field.replace("_", " "), "lines": lines})
    return out


def track_levels(blk):
    tracks = {}
    tr = blk.get("track")
    named = blk.get("tracks")
    sources = {}
    if isinstance(tr, Block):
        sources["default"] = tr
    if isinstance(named, Block):
        for name, _op, t in named:
            if name is not None and isinstance(t, Block):
                sources[str(name)] = t
    for tname, t in sources.items():
        levels = {}
        for lvl, _op, entry in t:
            if lvl is not None and isinstance(entry, Block):
                skills = {}
                lines = modifier_lines(entry, skills)
                lines = [{"t": f"{v:+g} {k.title()}", "p": "good" if v > 0 else "bad"}
                         for k, v in skills.items()] + lines
                if lines:
                    levels[str(lvl)] = [ln["t"] for ln in lines]
        if levels:
            tracks[tname] = levels
    return tracks


def main():
    entries = ck3.parse_dir(ck3.COMMON / "traits")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if not isinstance(blk, Block):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        skills = {}
        mods = modifier_lines(blk, skills, exclude=META_HANDLED | set(SKIP_META))

        opinions = []
        for f, label in OPINION_FIELDS.items():
            v = blk.get(f)
            if isinstance(v, (int, float)):
                opinions.append(f"{v:+g} {label}")
        for t in blk.get_all("triggered_opinion"):
            if isinstance(t, Block):
                om = t.get("opinion_modifier")
                if isinstance(om, str):
                    name = ck3.render_text(ck3.loc(om) or om.replace("_", " ").title())
                    opinions.append(name)

        genetic = {}
        for f in ("genetic", "physical", "good", "birth", "random_creation",
                  "inherit_chance", "both_parent_has_trait_inherit_chance",
                  "enables_inbred", "can_have_children", "incapacitating", "immortal"):
            v = blk.get(f)
            if v is not None and not isinstance(v, (Block, Tagged)):
                genetic[f] = v

        for k in blk.keys():
            if (k not in META_HANDLED and k not in SKIP_META
                    and not k.startswith("ai_")  # AI personality weights, skipped
                    and not is_modifier_key(k)):
                unhandled[k] += 1

        name = ck3.loc(f"trait_{key}") or ck3.loc(key)
        if not name:
            continue  # hidden/deprecated traits with no loc (hajjaj, viking, …)
        desc = ck3.loc(f"trait_{key}_desc")
        icon = blk.get("icon")
        if not isinstance(icon, str):
            icon = f"{key}"
        icon = icon.removesuffix(".dds")

        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "desc": ck3.render_text(desc) if desc else None,
            "category": blk.get("category") or "uncategorized",
            "group": blk.get("group"),
            "level": blk.get("level"),
            "skills": skills,
            "modifiers": mods,
            "opinions": opinions,
            "conditional": (conditional_modifiers(blk, "culture_modifier")
                            + conditional_modifiers(blk, "faith_modifier")
                            + conditional_modifiers(blk, "government_modifier")),
            "tracks": track_levels(blk),
            "opposites": [v for v in (blk.get("opposites").values() if isinstance(blk.get("opposites"), Block) else [])],
            "genetic": genetic,
            "rulerDesignerCost": blk.get("ruler_designer_cost"),
            "icon": icon,
            "dlc": dlc,
            "features": features,
        })

    out.sort(key=lambda r: (r["category"], r["group"] or "", r["level"] or 0, r["id"]))
    ck3.write_json("traits.json", out)

    if unhandled:
        print("⚠ unhandled trait fields:")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    hidden = len(entries) - len(out) - sum(1 for _p, _k, b in entries if not isinstance(b, Block))
    if hidden:
        print(f"  ({hidden} unlocalized hidden/deprecated traits excluded)")


if __name__ == "__main__":
    main()
