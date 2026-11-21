#!/usr/bin/env python3
"""Build src/data/holy_sites.json from common/religion/holy_site_types/.

One record per site: county/barony (with localized title names), the extra
effects loc line, parameters, and — since 1.20 (By God Alone) — four modifier
tiers per _holy_site_types.info:

  county_holder_character_modifier  county holder of the same faith
                                    (regular or eminent site)
  faith_character_modifier          every character of the faith, only when
                                    the site is one of the faith's EMINENT sites
  *_scaled                          multiplied by a script value, usually
                                    holy_site_total_artifact_rarity (sum of
                                    holy-relic rarities, 1 = Common … 4 =
                                    Illustrious, per the schema doc)

Dynamic sites (is_dynamic = yes) have no fixed location. Which faiths use a
site is a reverse map computed by the page from faiths.json.

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

HANDLED_FIELDS = {"county", "barony", "parameters", "is_dynamic",
                  "county_holder_character_modifier", "faith_character_modifier",
                  "faith_character_modifier_scaled", "county_modifier_scaled"}


# Built-in scale values have no loc; the wording is _holy_site_types.info's.
SCALE_LABELS = {
    "holy_site_total_artifact_rarity":
        "per point of holy-relic rarity (sum over relics: 1 Common … 4 Illustrious)",
}


def scaled(blks):
    """Repeatable `scale = <script value>` + modifiers blocks -> [{scale, lines}]."""
    out = []
    for b in blks:
        if not isinstance(b, Block):
            continue
        sc = b.get("scale")
        inner = Block([t for t in b if t[0] != "scale"])
        lines, _ = modifier_lines(inner)
        n, _r = ck3.resolve_value(sc) if not isinstance(sc, str) else (None, None)
        out.append({"scale": sc if n is None else n,
                    "scaleName": SCALE_LABELS.get(sc) if isinstance(sc, str) else None,
                    "lines": lines})
    return out


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
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "religion" / "holy_site_types"):
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        county = blk.get("county")
        barony = blk.get("barony")
        holder_mods, _ = modifier_lines(blk.get("county_holder_character_modifier"))
        faith_mods, _ = modifier_lines(blk.get("faith_character_modifier"))

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
        dynamic = blk.get("is_dynamic") is True
        name = ck3.loc(f"holy_site_{key}_name") or (ck3.loc(county) if county else None)
        if not name and dynamic:
            # "holy_site_<key>_dynamic_name" carries the barony as $TITLE$
            name = ck3.loc(f"holy_site_{key}_dynamic_name")
        dlc, _features = ck3.dlc_tag(path, blk)
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "county": county,
            "countyName": ck3.render_text(ck3.loc(county)) if county and ck3.loc(county) else None,
            "barony": barony,
            "baronyName": ck3.render_text(ck3.loc(barony)) if barony and ck3.loc(barony) else None,
            "dynamic": dynamic,
            "holderModifiers": holder_mods,
            "eminentModifiers": faith_mods,
            "eminentModifiersScaled": scaled(blk.get_all("faith_character_modifier_scaled")),
            "countyModifiersScaled": scaled(blk.get_all("county_modifier_scaled")),
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
    unnamed = [r["id"] for r in out if not r["name"]]
    if unnamed:
        print(f"⚠ {len(unnamed)} holy sites without localized names: {unnamed[:10]}")


if __name__ == "__main__":
    main()
