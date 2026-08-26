#!/usr/bin/env python3
"""Build src/data/faiths.json from common/religion/.

Religions nest their faiths (religion -> faiths = { key = {...} }); we emit a
flattened structure: families, religions (with their default doctrine list and
virtue/sin traits), and every faith with its merged effective doctrine list,
tenets, holy sites, and color. Doctrine merging: a faith-level doctrine
replaces the religion-level doctrine of the same group (single-pick groups);
tenets (3-pick group) only ever come from the faith level.

Schema doc: religion_types/_religion_types.info.
"""

import colorsys
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

RELIGION = ck3.COMMON / "religion"

# Fields we deliberately do not render, with reasons.
SKIP_RELIGION_FIELDS = {
    "graphical_faith": "3D temple asset selection, not player-facing data",
    "piety_icon_group": "GUI piety icon skin",
    "doctrine_background_icon": "GUI doctrine backdrop art",
    "custom_faith_icons": "icon picker pool for the faith-creation UI",
    "holy_order_names": "random holy-order name pool (flavor)",
    "holy_order_maa": "holy order AI army composition",
    "localization": "flavor term table (god names, priest titles) — not reference data",
    "reserved_male_names": "character name pool plumbing",
    "reserved_female_names": "character name pool plumbing",
}

SKIP_FAITH_FIELDS = {
    "reformed_icon": "art variant swapped in after pagan reformation; base icon shown",
    "graphical_faith": "3D temple asset selection",
    "localization": "flavor term table override — not reference data",
    "holy_order_names": "random holy-order name pool (flavor)",
    "reserved_male_names": "character name pool plumbing",
}

SKIP_FAMILY_FIELDS = {
    "graphical_faith": "3D temple asset selection",
    "piety_icon_group": "GUI piety icon skin",
    "doctrine_background_icon": "GUI doctrine backdrop art",
}

HANDLED_RELIGION_FIELDS = {"family", "doctrine", "faiths", "traits", "pagan_roots"}
HANDLED_FAITH_FIELDS = {"color", "icon", "holy_site", "doctrine", "religious_head",
                        "doctrine_selection_pair"}
HANDLED_FAMILY_FIELDS = {"hostility_doctrine"}


# --- colors -----------------------------------------------------------------

_named_colors: dict | None = None


def named_colors():
    global _named_colors
    if _named_colors is None:
        _named_colors = {}
        nc = ck3.COMMON / "named_colors"
        def walk(blk):
            for k, _op, v in blk:
                if k is None:
                    continue
                if isinstance(v, (Block, Tagged)) and _color_triplet(v) is not None:
                    _named_colors[k] = v
                elif isinstance(v, Block):
                    walk(v)
        for p in sorted(nc.glob("*.txt")):
            if not p.name.startswith("_"):
                walk(ck3.parse_file(p))
    return _named_colors


def _color_triplet(v):
    tag = None
    if isinstance(v, Tagged):
        tag, v = v.tag, v.block
    if not isinstance(v, Block):
        return None
    vals = [x for x in v.values() if isinstance(x, (int, float))]
    if len(vals) != 3:
        return None
    return tag, vals


def color_hex(v):
    """Game color (plain 0–1/0–255 triplet, rgb/hsv tagged, or named) -> #rrggbb."""
    if isinstance(v, str):
        v = named_colors().get(v)
        if v is None:
            return None
    trip = _color_triplet(v)
    if trip is None:
        return None
    tag, vals = trip
    if tag == "hsv":
        r, g, b = colorsys.hsv_to_rgb(*vals)
    elif tag == "hsv360":
        r, g, b = colorsys.hsv_to_rgb(vals[0] / 360, vals[1] / 100, vals[2] / 100)
    elif max(vals) > 1:
        r, g, b = (x / 255 for x in vals)
    else:
        r, g, b = vals
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(x * 255))) for x in (r, g, b)))


# --- doctrine groups (for the merge rule) -----------------------------------

def doctrine_groups():
    """doctrine key -> (group key, number_of_picks)."""
    by_doctrine = {}
    for _p, gkey, blk in ck3.parse_dir(RELIGION / "doctrine_group_types"):
        picks = blk.get("number_of_picks", 1)
        dts = blk.get("doctrine_types")
        if isinstance(dts, Block):
            for d in dts.values():
                by_doctrine[d] = (gkey, picks)
    return by_doctrine


def doctrine_name(key):
    raw = ck3.loc(f"{key}_name") or ck3.loc(key)
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


def trait_list(v):
    """A virtues/sins block -> [{key, name}] (scale/weight sub-blocks ignored)."""
    out = []
    if not isinstance(v, Block):
        return out
    keys = [x for x in v.values() if isinstance(x, str)] + [k for k, _op, _v in v if k is not None]
    for t in keys:
        raw = ck3.loc(f"trait_{t}") or ck3.loc(t)
        out.append({"key": t, "name": ck3.render_text(raw) if raw else t.replace("_", " ").title()})
    return out


def main():
    d2g = doctrine_groups()
    unhandled = {"family": Counter(), "religion": Counter(), "faith": Counter()}

    families = []
    for _p, key, blk in ck3.parse_dir(RELIGION / "religion_family_types"):
        for k in blk.keys():
            if k not in HANDLED_FAMILY_FIELDS and k not in SKIP_FAMILY_FIELDS:
                unhandled["family"][k] += 1
        families.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(key) or key.removeprefix("rf_").title()),
            "hostilityDoctrine": blk.get("hostility_doctrine"),
        })

    religions, faiths = [], []
    for path, rkey, rblk in ck3.parse_dir(RELIGION / "religion_types"):
        if isinstance(rblk, Tagged):
            continue
        for k in rblk.keys():
            if k not in HANDLED_RELIGION_FIELDS and k not in SKIP_RELIGION_FIELDS:
                unhandled["religion"][k] += 1

        rel_doctrines = rblk.get_all("doctrine")
        traits = rblk.get("traits")
        religions.append({
            "id": rkey,
            "name": ck3.render_text(ck3.loc(rkey) or rkey),
            "family": rblk.get("family"),
            "doctrines": rel_doctrines,
            "virtues": trait_list(traits.get("virtues")) if isinstance(traits, Block) else [],
            "sins": trait_list(traits.get("sins")) if isinstance(traits, Block) else [],
            "paganRoots": bool(rblk.get("pagan_roots", False)),
        })

        fblock = rblk.get("faiths")
        if not isinstance(fblock, Block):
            continue
        for fkey, _op, fv in fblock:
            if fkey is None or not isinstance(fv, Block):
                continue
            for k in fv.keys():
                if k not in HANDLED_FAITH_FIELDS and k not in SKIP_FAITH_FIELDS:
                    unhandled["faith"][k] += 1

            # merge religion defaults with faith picks: faith overrides its group
            faith_doctrines = fv.get_all("doctrine")
            selection_pairs = []
            for sp in fv.get_all("doctrine_selection_pair"):
                if isinstance(sp, Block):
                    flag = sp.get("requires_dlc_flag")
                    selection_pairs.append({
                        "doctrine": sp.get("doctrine"),
                        "fallback": sp.get("fallback_doctrine"),
                        "dlc": ck3.FEATURE_TO_DLC.get(flag, flag),
                    })
            overridden_groups = {d2g[d][0] for d in faith_doctrines
                                 if d in d2g and d2g[d][1] == 1}
            effective = [d for d in rel_doctrines
                         if not (d in d2g and d2g[d][0] in overridden_groups)]
            effective += faith_doctrines
            effective += [sp["doctrine"] for sp in selection_pairs if sp["doctrine"]]

            tenets = []
            for d in faith_doctrines:
                if d in d2g and d2g[d][0] == "doctrine_core_tenets":
                    tenets.append({"key": d, "name": doctrine_name(d),
                                   "dlc": None, "fallback": None})
            for sp in selection_pairs:
                d = sp["doctrine"]
                if d in d2g and d2g[d][0] == "doctrine_core_tenets":
                    tenets.append({"key": d, "name": doctrine_name(d),
                                   "dlc": sp["dlc"],
                                   "fallback": doctrine_name(sp["fallback"]) if sp["fallback"] else None})

            head = fv.get("religious_head")
            head_name = ck3.render_text(ck3.loc(head)) if head and ck3.loc(head) else None

            name = ck3.loc(fkey)
            faiths.append({
                "id": fkey,
                "name": ck3.render_text(name) if name else None,
                "adjective": ck3.render_text(ck3.loc(f"{fkey}_adj") or "") or None,
                "adherent": ck3.render_text(ck3.loc(f"{fkey}_adherent") or "") or None,
                "religion": rkey,
                "family": rblk.get("family"),
                "color": color_hex(fv.get("color")),
                "icon": str(fv.get("icon") or fkey).removesuffix(".dds"),
                "religiousHead": {"title": head, "name": head_name} if head else None,
                "holySites": [{"key": h, "name": ck3.render_text(
                    ck3.loc(f"holy_site_{h}_name") or h.replace("_", " ").title())}
                    for h in fv.get_all("holy_site")],
                "doctrines": effective,
                "tenets": tenets,
                "sourceFile": path.name,
            })

    faiths.sort(key=lambda f: (f["family"] or "", f["religion"], f["id"]))
    religions.sort(key=lambda r: (r["family"] or "", r["id"]))
    ck3.write_json("faiths.json", {"families": families, "religions": religions,
                                   "faiths": faiths})
    print(f"  ({len(families)} families, {len(religions)} religions, {len(faiths)} faiths)")

    for level, counts in unhandled.items():
        if counts:
            print(f"⚠ unhandled {level} fields (add to HANDLED or SKIP):")
            for k, n in counts.most_common():
                print(f"    {k} ×{n}")
    missing = [f["id"] for f in faiths if not f["name"]]
    if missing:
        print(f"⚠ {len(missing)} faiths without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
