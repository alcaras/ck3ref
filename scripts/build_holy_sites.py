#!/usr/bin/env python3
"""Build src/data/holy_sites.json from common/religion/holy_site_types/.

One record per site: county/barony (with localized title names), rendered
character modifiers, the extra effects loc line, and parameters. Which faiths
use a site is a reverse map computed by the page from faiths.json.

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

HANDLED_FIELDS = {"county", "barony", "character_modifier", "parameters"}


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
        mods, _label = modifier_lines(blk.get("character_modifier"))

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
        dlc, _features = ck3.dlc_tag(path, blk)
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "county": county,
            "countyName": ck3.render_text(ck3.loc(county)) if county and ck3.loc(county) else None,
            "barony": barony,
            "baronyName": ck3.render_text(ck3.loc(barony)) if barony and ck3.loc(barony) else None,
            "modifiers": mods,
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
