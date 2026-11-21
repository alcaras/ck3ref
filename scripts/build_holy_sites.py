#!/usr/bin/env python3
"""Build src/data/holy_sites.json from common/religion/holy_site_types/.

One record per site: county/barony (with localized title names), the four
modifier blocks split by who receives them, the extra effects loc line, and
parameters. 1.21 splits holy sites into Eminent and regular per FAITH (a faith
lists `eminent_holy_sites` and `holy_sites`); the site type itself decides
which bonuses apply in which case (_holy_site_types.info):

- faith_character_modifier(_scaled): all characters of the faith, only when
  the site is Eminent for that faith and its barony holder shares the faith;
- county_holder_character_modifier: the county holder, if same faith,
  Eminent or regular;
- county_modifier_scaled: the site's county, Eminent or regular.

`_scaled` blocks multiply each value by a script value (`scale`), in practice
holy_site_total_artifact_rarity (sum of holy-relic artifact rarities). Dynamic
sites (`is_dynamic = yes`) have no fixed location; rulers create them.
Which faiths use a site is a reverse map computed by the page from faiths.json.

Schema doc: _holy_site_types.info. Loc: holy_site_<key>_name,
holy_site_<key>_effects, holy_site_parameter_<param>.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP_FIELDS = {
    # (none yet)
}

HANDLED_FIELDS = {"county", "barony", "is_dynamic", "parameters",
                  "faith_character_modifier", "faith_character_modifier_scaled",
                  "county_holder_character_modifier", "county_modifier_scaled"}


def scaled_blocks(blk, field):
    """Repeatable `{ scale = <script value> mod = x ... }` -> [{scale, scaleDesc, lines}]."""
    out = []
    for b in blk.get_all(field):
        if not isinstance(b, Block):
            continue
        scale = b.get("scale")
        mods = Block([(k, o, v) for k, o, v in b if k != "scale"])
        lines, _ = modifier_lines(mods)
        out.append({"scale": scale, "scaleName": SCALE_NAMES.get(scale), "lines": lines})
    return out


# The engine-side value is documented in _holy_site_types.info; the name we
# show is the game's own description of it, quoted.
SCALE_NAMES = {
    "holy_site_total_artifact_rarity":
        "sum of Rarity values across artifacts whose is_holy_relic trigger is true "
        "(1=Common, 2=Masterwork, 3=Famed, 4=Illustrious)",
}


def modifier_lines(blk):
    lines, label = [], None
    if not isinstance(blk, Block):
        return lines, label
    for k, _op, v in blk:
        if k is None:
            continue
        if k == "name":
            raw = ck3.loc(str(v))
            label = ck3.render_text(raw) if raw else None
            continue
        if isinstance(v, str):
            n, _r = ck3.resolve_value(v)
            v = n if n is not None else v
        if isinstance(v, (Block, Tagged)):
            lines.append(f"{ck3.modifier_name(k)}: (conditional)")
        else:
            lines.append(ck3.render_modifier(k, v))
    return lines, label


def main():
    unhandled = Counter()
    unknown_scales = Counter()
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "religion" / "holy_site_types"):
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        county = blk.get("county")
        barony = blk.get("barony")
        dynamic = bool(blk.get("is_dynamic", False))
        faith_mods, label = modifier_lines(blk.get("faith_character_modifier"))
        holder_mods, _ = modifier_lines(blk.get("county_holder_character_modifier"))

        params = []
        pblk = blk.get("parameters")
        if isinstance(pblk, Block):
            keys = [x for x in pblk.values() if isinstance(x, str)] + \
                   [k for k, _op, _v in pblk if k is not None]
            for pk in keys:
                raw = ck3.loc(f"holy_site_parameter_{pk}")
                params.append({"key": pk,
                               "text": ck3.render_text(raw) if raw else None})

        effects = ck3.loc(f"holy_site_{key}_effects")
        name = ck3.loc(f"holy_site_{key}_name") or (ck3.loc(county) if county else None)
        for sb in scaled_blocks(blk, "faith_character_modifier_scaled") + \
                scaled_blocks(blk, "county_modifier_scaled"):
            if sb["scale"] not in SCALE_NAMES:
                unknown_scales[sb["scale"]] += 1
        dlc, _features = ck3.dlc_tag(path, blk)
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "county": county,
            "countyName": ck3.render_text(ck3.loc(county)) if county and ck3.loc(county) else None,
            "barony": barony,
            "baronyName": ck3.render_text(ck3.loc(barony)) if barony and ck3.loc(barony) else None,
            "dynamic": dynamic,
            "faithModifiers": faith_mods,
            "faithModifierName": label,
            "faithModifiersScaled": scaled_blocks(blk, "faith_character_modifier_scaled"),
            "holderModifiers": holder_mods,
            "countyModifiersScaled": scaled_blocks(blk, "county_modifier_scaled"),
            "effects": ck3.render_text(effects) if effects else None,
            "parameters": params,
            "dlc": dlc,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (r["name"] or "", r["id"]))
    ck3.write_json("holy_sites.json", out)

    if unhandled:
        print("⚠ unhandled holy-site fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    if unknown_scales:
        print(f"⚠ unknown scale script values (add a SCALE_NAMES entry): {dict(unknown_scales)}")
    print(f"  ({sum(r['dynamic'] for r in out)} dynamic site types, "
          f"{sum(1 for r in out if r['faithModifiers'] or r['faithModifiersScaled'])} with Eminent-only faith bonuses)")
    unnamed = [r["id"] for r in out if not r["name"]]
    if unnamed:
        print(f"⚠ {len(unnamed)} holy sites without localized names: {unnamed[:10]}")


if __name__ == "__main__":
    main()
