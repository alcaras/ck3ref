#!/usr/bin/env python3
"""Build src/data/faiths.json from common/religion/ (CK3 1.20+ layout).

1.20 (By God Alone) split the religion tree into three databases:

  religion_types/  religions (`religion_details` block, default doctrines,
                   virtues/sins)
  faith_types/     faiths (`faith_details.religion` names the parent), holy
                   sites (split eminent / regular), optional `main_rite`
  rite_types/      Rites (`faith =` names the parent faith), each with its
                   own tenets and doctrines

We emit families, religions, faiths and rites. Effective doctrines follow the
schema docs: faith-type doctrines override the religion's per doctrine group;
Rite doctrines override both per group. A faith's effective tenets and
doctrines are its scripted main Rite's when it has one (_faith_types.info:
"The scripted main Rite owns core tenets and Rite-specific doctrines").
Dated main-Rite changes and tenet status lists come from history/faiths.

Schema docs: _religion_types.info, _faith_types.info, _rite_types.info,
_religion_family_types.info, history/faiths/_faith_history.info.
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
_GFX = "3D temple asset selection, not player-facing data"
_NAMES = "character name pool plumbing"
_LOC = "flavor term table (god names, priest titles) — not reference data"
_ORDERS = "random holy-order name pool (flavor)"
_BANNER = "GUI tenet banner art"

SKIP_RELIGION_FIELDS = {
    "custom_faith_icons": "icon picker pool for the faith-creation UI",
    "holy_order_names": _ORDERS,
    "holy_order_maa": "holy order AI army composition",
    "localization": _LOC,
    "reserved_male_names": _NAMES,
    "reserved_female_names": _NAMES,
}
HANDLED_RELIGION_FIELDS = {"religion_details", "doctrine", "traits", "pagan_roots",
                           "main_holy_site", "eminent_holy_sites_max", "holy_sites_max",
                           "eminent_holy_sites_min", "holy_sites_min"}
SKIP_RELIGION_DETAIL_FIELDS = {
    "graphical_faith": _GFX,
    "piety_icon_group": "GUI piety icon skin",
    "tenet_background_icon": _BANNER,
    "tenet_heretical_background_icon": _BANNER,
    "tenet_neutral_background_icon": _BANNER,
    "tenet_unknown_background_icon": _BANNER,
    "theocracy_lease_contract_type": "contract plumbing; the lease itself is on the contracts page",
}
HANDLED_RELIGION_DETAIL_FIELDS = {"family", "theocracy_government_type"}

SKIP_FAITH_FIELDS = {
    "localization": _LOC,
    "holy_order_names": _ORDERS,
    "reserved_male_names": _NAMES,
    "reserved_female_names": _NAMES,
}
HANDLED_FAITH_FIELDS = {"faith_details", "origin", "holy_sites", "eminent_holy_sites",
                        "tenets", "doctrines", "tenet_selection_pair", "cultures",
                        "clerical_elector_titles", "historical", "main_rite"}
SKIP_FAITH_DETAIL_FIELDS = {
    "reformed_icon": "art variant swapped in after pagan reformation; base icon shown",
    "graphical_faith": _GFX,
}
HANDLED_FAITH_DETAIL_FIELDS = {"religion", "color", "icon", "religious_head",
                               "head_of_rite", "theocracy_government_type"}

SKIP_RITE_FIELDS = {"localization": _LOC}
HANDLED_RITE_FIELDS = {"name", "desc", "icon", "color", "founder", "faith", "cultures",
                       "convert", "create", "history", "tenets", "doctrines",
                       "tenet_selection_pair"}

SKIP_FAMILY_FIELDS = {
    "graphical_faith": _GFX,
    "piety_icon_group": "GUI piety icon skin",
    "doctrine_background_icon": _BANNER,
    "tenet_background_icon": _BANNER,
    "tenet_heretical_background_icon": _BANNER,
    "tenet_neutral_background_icon": _BANNER,
    "tenet_unknown_background_icon": _BANNER,
}
HANDLED_FAMILY_FIELDS = {"hostility_doctrine", "name"}


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


# --- doctrines ----------------------------------------------------------------

def doctrine_group_of():
    """doctrine key -> its doctrine_group_type (1.20: declared on the doctrine)."""
    out = {}
    for _p, key, blk in ck3.parse_dir(RELIGION / "doctrine_types"):
        if isinstance(blk, Block) and isinstance(blk.get("doctrine_group_type"), str):
            out[key] = blk.get("doctrine_group_type")
    return out


def overlay(base, picks, d2g):
    """Apply `picks` over `base`: a pick replaces any base doctrine of its group."""
    groups = {d2g.get(d) for d in picks if d2g.get(d)}
    return [d for d in base if d2g.get(d) not in groups] + \
           [d for d in picks if d not in base or d2g.get(d) is None]


def name_of(key, suffix=""):
    raw = ck3.loc(f"{key}{suffix}")
    return ck3.render_text(raw) if raw else None


def doctrine_name(key):
    return name_of(key, "_name") or name_of(key) or key.replace("_", " ").title()


def block_keys(v):
    if not isinstance(v, Block):
        return []
    return [x for x in v.values() if isinstance(x, str)] + \
           [k for k, _op, _v in v if k is not None]


def trait_list(v):
    """A virtues/sins block -> [{key, name, weight, scale}] (weight/scale only
    when the game sets them; defaults are 1 per _religion_types.info)."""
    out = []
    if not isinstance(v, Block):
        return out
    for t in [x for x in v.values() if isinstance(x, str)]:
        out.append({"key": t})
    for k, _op, sub in v:
        if k is None:
            continue
        rec = {"key": k}
        if isinstance(sub, Block):
            if sub.get("weight") is not None:
                rec["weight"] = sub.get("weight")
            if sub.get("scale") is not None:
                rec["scale"] = sub.get("scale")
        elif isinstance(sub, (int, float)):
            rec["scale"] = sub
        out.append(rec)
    for rec in out:
        raw = ck3.loc(f"trait_{rec['key']}") or ck3.loc(rec["key"])
        rec["name"] = ck3.render_text(raw) if raw else rec["key"].replace("_", " ").title()
    return out


def selection_pairs(blk):
    out = []
    for sp in blk.get_all("tenet_selection_pair"):
        if isinstance(sp, Block):
            flag = sp.get("requires_dlc_flag")
            out.append({"tenet": sp.get("tenet"), "fallback": sp.get("fallback_tenet"),
                        "dlc": ck3.FEATURE_TO_DLC.get(flag, flag)})
    return out


def tenet_list(keys, pairs):
    out = [{"key": t, "name": doctrine_name(t), "dlc": None, "fallback": None}
           for t in keys]
    for sp in pairs:
        if sp["tenet"]:
            out.append({"key": sp["tenet"], "name": doctrine_name(sp["tenet"]),
                        "dlc": sp["dlc"],
                        "fallback": doctrine_name(sp["fallback"]) if sp["fallback"] else None,
                        "fallbackKey": sp["fallback"]})
    return out


def dynamic_name(blk, field, default_key):
    """Name/desc honouring a dynamic block: default key if localized, else the
    untriggered fallback (last `desc` of a first_valid chain)."""
    if ck3.loc(default_key):
        return name_of(default_key)
    keys = []
    def walk(v):
        if isinstance(v, Tagged):
            v = v.block
        if isinstance(v, str):
            keys.append(v)
        elif isinstance(v, Block):
            for k, _op, val in v:
                if k == "desc" and isinstance(val, str):
                    keys.append(val)
                elif isinstance(val, (Block, Tagged)):
                    walk(val)
    walk(blk.get(field))
    for k in reversed(keys):
        if ck3.loc(k):
            return name_of(k)
    return None


def holy_site(h):
    return {"key": h, "name": name_of(f"holy_site_{h}_name") or h.replace("_", " ").title()}


def title_ref(t):
    return {"title": t, "name": name_of(t)} if t else None


def read_define(namespace, key):
    for ns, _op, blk in ck3.parse_file(ck3.COMMON / "defines" / "00_defines.txt"):
        if ns == namespace and isinstance(blk, Block):
            return blk.get(key)
    return None


def faith_history():
    """faith key -> [{date, mainRite, religiousHead, rites, permitted,
    prohibited, known}] in date order (history/faiths)."""
    out = {}
    for _p, fkey, blk in ck3.parse_dir(ck3.REF / "game" / "history" / "faiths"):
        if not isinstance(blk, Block):
            continue
        entries = []
        for date, _op, ev in blk:
            if not isinstance(ev, Block):
                continue
            e = {"date": str(date)}
            if ev.get("main_rite"):
                e["mainRite"] = ev.get("main_rite")
            if ev.get("religious_head"):
                e["religiousHead"] = ev.get("religious_head")
            if isinstance(ev.get("rites"), Block):
                e["rites"] = block_keys(ev.get("rites"))
            for f in ("permitted", "prohibited", "known"):
                if isinstance(ev.get(f), Block):
                    e[f] = block_keys(ev.get(f))
            entries.append(e)
        out[fkey] = sorted(entries, key=lambda e: [int(x) for x in e["date"].split(".")])
    return out


def main():
    d2g = doctrine_group_of()
    history = faith_history()
    unhandled = {k: Counter() for k in
                 ("family", "religion", "religion_details", "faith", "faith_details", "rite")}

    def account(level, blk, handled, skip):
        for k in blk.keys():
            if k not in handled and k not in skip:
                unhandled[level][k] += 1

    families = []
    for _p, key, blk in ck3.parse_dir(RELIGION / "religion_family_types"):
        account("family", blk, HANDLED_FAMILY_FIELDS, SKIP_FAMILY_FIELDS)
        families.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(blk.get("name") or key)
                                    or key.removeprefix("rf_").title()),
            "hostilityDoctrine": blk.get("hostility_doctrine"),
        })

    defaults = {f: read_define("NReligion", f) for f in (
        "FAITH_EMINENT_HOLY_SITES_MAX_DEFAULT", "FAITH_HOLY_SITES_MAX_DEFAULT",
        "FAITH_EMINENT_HOLY_SITES_MIN_DEFAULT", "FAITH_HOLY_SITES_MIN_DEFAULT")}

    religions, rel_by_id = [], {}
    for path, rkey, rblk in ck3.parse_dir(RELIGION / "religion_types"):
        if not isinstance(rblk, Block):
            continue
        account("religion", rblk, HANDLED_RELIGION_FIELDS, SKIP_RELIGION_FIELDS)
        det = rblk.get("religion_details") if isinstance(rblk.get("religion_details"), Block) \
            else Block()
        account("religion_details", det, HANDLED_RELIGION_DETAIL_FIELDS,
                SKIP_RELIGION_DETAIL_FIELDS)
        traits = rblk.get("traits")
        theo = det.get("theocracy_government_type")
        rec = {
            "id": rkey,
            "name": name_of(rkey) or rkey,
            "family": det.get("family"),
            "doctrines": rblk.get_all("doctrine"),
            "virtues": trait_list(traits.get("virtues")) if isinstance(traits, Block) else [],
            "sins": trait_list(traits.get("sins")) if isinstance(traits, Block) else [],
            "paganRoots": rblk.get("pagan_roots") is True,
            "theocracyGovernment": {"key": theo, "name": name_of(theo)} if theo else None,
            "mainHolySite": holy_site(rblk.get("main_holy_site"))
                            if rblk.get("main_holy_site") else None,
            "holySiteLimits": {
                "eminentMax": rblk.get("eminent_holy_sites_max",
                                       defaults["FAITH_EMINENT_HOLY_SITES_MAX_DEFAULT"]),
                "totalMax": rblk.get("holy_sites_max", defaults["FAITH_HOLY_SITES_MAX_DEFAULT"]),
                "eminentMin": rblk.get("eminent_holy_sites_min",
                                       defaults["FAITH_EMINENT_HOLY_SITES_MIN_DEFAULT"]),
                "totalMin": rblk.get("holy_sites_min", defaults["FAITH_HOLY_SITES_MIN_DEFAULT"]),
            },
            "sourceFile": path.name,
        }
        religions.append(rec)
        rel_by_id[rkey] = rec

    # rites, grouped by their parent faith ------------------------------------
    rite_blocks = {}
    for path, key, blk in ck3.parse_dir(RELIGION / "rite_types"):
        if isinstance(blk, Block):
            account("rite", blk, HANDLED_RITE_FIELDS, SKIP_RITE_FIELDS)
            rite_blocks[key] = (path, blk)

    faiths, rites = [], []
    for path, fkey, fblk in ck3.parse_dir(RELIGION / "faith_types"):
        if not isinstance(fblk, Block):
            continue
        account("faith", fblk, HANDLED_FAITH_FIELDS, SKIP_FAITH_FIELDS)
        det = fblk.get("faith_details") if isinstance(fblk.get("faith_details"), Block) \
            else Block()
        account("faith_details", det, HANDLED_FAITH_DETAIL_FIELDS, SKIP_FAITH_DETAIL_FIELDS)
        rkey = det.get("religion")
        rel = rel_by_id.get(rkey, {})
        faith_level = overlay(rel.get("doctrines", []), block_keys(fblk.get("doctrines")), d2g)
        faith_tenets = tenet_list(block_keys(fblk.get("tenets")), selection_pairs(fblk))
        main_rite = fblk.get("main_rite")

        def make_rite(rite_key):
            rpath, rblk = rite_blocks[rite_key]
            # rite doctrines override faith (and religion) doctrines group-wise
            eff = overlay(faith_level, block_keys(rblk.get("doctrines")), d2g)
            r_tenets = tenet_list(block_keys(rblk.get("tenets")), selection_pairs(rblk))
            return {
                "id": rite_key,
                "name": dynamic_name(rblk, "name", rite_key) or rite_key.replace("_", " ").title(),
                "adjective": name_of(f"{rite_key}_adj"),
                "adherent": name_of(f"{rite_key}_adherent"),
                "desc": dynamic_name(rblk, "desc", f"{rite_key}_desc"),
                "faith": fkey,
                "religion": rkey,
                "family": rel.get("family"),
                "isMain": rite_key == main_rite,
                "color": color_hex(rblk.get("color")),
                "icon": str(rblk.get("icon") or rite_key).removesuffix(".dds"),
                "founder": title_ref(rblk.get("founder")),
                "cultures": block_keys(rblk.get("cultures")),
                "convertible": rblk.get("convert", True) is not False
                               and rblk.get("history") is not True,
                "createdAtStart": rblk.get("create", True) is not False,
                "historical": rblk.get("history") is True,
                "doctrines": eff,
                "tenets": r_tenets,
                "sourceFile": rpath.name,
            }

        my_rites = [make_rite(k) for k, (_p, b) in rite_blocks.items() if b.get("faith") == fkey]
        main = next((r for r in my_rites if r["isMain"]), None)
        if main is None and main_rite in rite_blocks:
            # a main Rite whose default parent is another faith, handed over in
            # history (e.g. roman_rite: christian_faith -> catholic at 1054.7.16)
            main = make_rite(main_rite)
            main["faith"] = rite_blocks[main_rite][1].get("faith")
            main["viaHistory"] = True
        elif main is None and main_rite:
            print(f"⚠ {fkey}: main_rite {main_rite} is not a rite_type")
        my_rites.sort(key=lambda r: (not r["isMain"], r["name"]))
        rites.extend(my_rites)

        head = det.get("religious_head")
        faiths.append({
            "id": fkey,
            "name": name_of(fkey),
            "adjective": name_of(f"{fkey}_adj"),
            "adherent": name_of(f"{fkey}_adherent"),
            "religion": rkey,
            "family": rel.get("family"),
            "color": color_hex(det.get("color")),
            "icon": str(det.get("icon") or fkey).removesuffix(".dds"),
            "religiousHead": title_ref(head),
            "headOfRite": title_ref(det.get("head_of_rite")),
            "theocracyGovernment": {"key": det.get("theocracy_government_type"),
                                    "name": name_of(det.get("theocracy_government_type"))}
                                   if det.get("theocracy_government_type") else None,
            "origin": fblk.get("origin"),
            "historical": fblk.get("historical") is True,
            "eminentHolySites": [holy_site(h) for h in block_keys(fblk.get("eminent_holy_sites"))],
            "holySites": [holy_site(h) for h in block_keys(fblk.get("holy_sites"))],
            "mainRite": main_rite,
            # the faith's effective properties are its main Rite's (faith-type
            # doctrines fill only the groups the Rite leaves open)
            "doctrines": main["doctrines"] if main else faith_level,
            "tenets": main["tenets"] if main else faith_tenets,
            "rites": [r["id"] for r in my_rites],
            # rites handed to this faith by dated history (e.g. at the Schism)
            "historyRites": sorted({r for e in history.get(fkey, []) for r in e.get("rites", [])}
                                   - {r["id"] for r in my_rites}),
            "clericalElectorTitles": len(block_keys(fblk.get("clerical_elector_titles"))),
            "cultures": block_keys(fblk.get("cultures")),
            "history": history.get(fkey, []),
            "sourceFile": path.name,
        })

    orphan_rites = sorted(k for k, (_p, b) in rite_blocks.items()
                          if b.get("faith") not in {f["id"] for f in faiths})
    if orphan_rites:
        print(f"⚠ rites whose parent faith is not in faith_types: {orphan_rites}")
    faiths.sort(key=lambda f: (f["family"] or "", f["religion"] or "", f["id"]))
    religions.sort(key=lambda r: (r["family"] or "", r["id"]))
    ck3.write_json("faiths.json", {"families": families, "religions": religions,
                                   "faiths": faiths, "rites": rites})
    print(f"  ({len(families)} families, {len(religions)} religions, {len(faiths)} faiths, "
          f"{len(rites)} rites)")

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
