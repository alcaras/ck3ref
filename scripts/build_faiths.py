#!/usr/bin/env python3
"""Build src/data/faiths.json from common/religion/ (1.21 three-tier model).

Religion -> faith -> rite. Religions (religion_types/) carry a
`religion_details` block, default doctrines and virtue/sin traits. Faiths
(faith_types/) carry `faith_details`, eminent and regular holy sites, and
usually name a scripted `main_rite`. Rites (rite_types/) carry core tenets
and rite-specific doctrines. history/faiths/ moves rites between faiths by
date, sets dated main rites, and records each faith's tenet statuses
(known / permitted / prohibited).

Effective doctrines merge by doctrine group, later layer wins:
religion -> faith -> rite (_rite_types.info: "Rite doctrines override
parent-religion and faith doctrines from the same doctrine group").
A faith's effective tenets are its main rite's (_faith_types.info: "the
Rite's tenets override these").

Schema docs: religion_types/_religion_types.info, faith_types/_faith_types.info,
rite_types/_rite_types.info, history/faiths/_faith_history.info.
"""

import colorsys
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import ck3_religion as R
from ck3 import Block, Tagged

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




# --- traits ------------------------------------------------------------------

def trait_list(v):
    """virtues/sins block -> [{key, name, scale, weight}].

    Entries are bare (`brave`), scaled (`brave = 0.5`) or a block
    (`forgiving = { weight = 50 scale = 1.5 }`); scale and weight default to
    1 per _religion_types.info."""
    out = []
    if not isinstance(v, Block):
        return out
    for k, _op, val in v:
        if k is None:
            if not isinstance(val, str):
                continue
            key, scale, weight = val, 1, 1
        else:
            key = k
            if isinstance(val, Block):
                scale = val.get("scale", 1)
                weight = val.get("weight", 1)
            else:
                scale, weight = (val if isinstance(val, (int, float)) else 1), 1
        raw = ck3.loc(f"trait_{key}") or ck3.loc(key)
        out.append({"key": key,
                    "name": ck3.render_text(raw) if raw else key.replace("_", " ").title(),
                    "scale": scale, "weight": weight})
    return out


def selection_pairs(blk):
    """tenet_selection_pair blocks -> [{tenet, fallback, dlc}]."""
    out = []
    for sp in blk.get_all("tenet_selection_pair"):
        if isinstance(sp, Block):
            flag = sp.get("requires_dlc_flag")
            out.append({"tenet": sp.get("tenet"), "fallback": sp.get("fallback_tenet"),
                        "dlc": ck3.FEATURE_TO_DLC.get(flag, flag)})
    return out


def tenet_entries(plain, pairs):
    out = [{"key": t, "name": R.tenet_name(t), "dlc": None, "fallback": None,
            "fallbackName": None} for t in plain]
    for sp in pairs:
        out.append({"key": sp["tenet"], "name": R.tenet_name(sp["tenet"]),
                    "dlc": sp["dlc"], "fallback": sp["fallback"],
                    "fallbackName": R.tenet_name(sp["fallback"]) if sp["fallback"] else None})
    return out


# --- faith history -----------------------------------------------------------

def faith_history(unhandled):
    """faith key -> [dated entry]. Schema: history/faiths/_faith_history.info."""
    out = {}
    for _p, fkey, blk in ck3.parse_dir(R.FAITH_HISTORY):
        if not isinstance(blk, Block):
            continue
        entries = []
        for date, _op, e in blk:
            if not isinstance(e, Block):
                continue
            for k in e.keys():
                if k not in HANDLED_HISTORY_FIELDS:
                    unhandled["history"][k] += 1
            rites = []
            rb = e.get("rites")
            if isinstance(rb, Block):
                for rk, _o, rv in rb:
                    if rk is None:
                        continue
                    rec = {"id": rk, "enabled": None, "tenetSetups": [], "doctrines": []}
                    if isinstance(rv, Block):
                        for k in rv.keys():
                            if k not in HANDLED_HISTORY_RITE_FIELDS:
                                unhandled["history rite"][k] += 1
                        if rv.get("enabled") is not None:
                            rec["enabled"] = bool(rv.get("enabled"))
                        if rv.get("rite"):
                            rec["id"] = rv.get("rite")
                        for ts in rv.get_all("tenet_setup"):
                            if isinstance(ts, Block):
                                feats = R.block_list(ts.get("dlc_feature"))
                                rec["tenetSetups"].append({
                                    "dlc": sorted({ck3.FEATURE_TO_DLC.get(f, f) for f in feats}),
                                    "tenets": [{"key": t, "name": R.tenet_name(t)}
                                               for t in R.block_list(ts.get("tenets"))]})
                        rec["doctrines"] = R.block_list(rv.get("doctrines"))
                    rites.append(rec)
            status = {}
            for st in ("known", "permitted", "prohibited"):
                status[st] = [{"key": t, "name": R.tenet_name(t)}
                              for t in R.block_list(e.get(st))]
            head = e.get("religious_head")
            entries.append({
                "date": str(date),
                "created": bool(e.get("created")) if e.get("created") is not None else None,
                "mainRite": e.get("main_rite"),
                "religiousHead": {"title": head, "name": R.title_name(head)} if head else None,
                "rites": rites,
                **status,
            })
        entries.sort(key=lambda x: tuple(int(p) for p in x["date"].split(".")))
        out[fkey] = entries
    return out


# --- main ---------------------------------------------------------------------

HANDLED_FAMILY_FIELDS = {"hostility_doctrine", "name"}
SKIP_FAMILY_FIELDS = {
    "graphical_faith": "3D temple asset selection, not player-facing data",
    "piety_icon_group": "GUI piety icon skin",
    "tenet_background_icon": "GUI tenet banner art",
    "tenet_heretical_background_icon": "GUI tenet banner art",
    "tenet_neutral_background_icon": "GUI tenet banner art",
    "tenet_unknown_background_icon": "GUI tenet banner art",
}

HANDLED_RELIGION_FIELDS = {"religion_details", "doctrine", "traits", "pagan_roots",
                           "main_holy_site", "eminent_holy_sites_max", "holy_sites_max",
                           "eminent_holy_sites_min", "holy_sites_min"}
SKIP_RELIGION_FIELDS = {
    "custom_faith_icons": "icon picker pool for the faith-creation UI",
    "holy_order_names": "random holy-order name pool (flavor)",
    "holy_order_maa": "holy order AI army composition",
    "localization": "flavor term table (god names, priest titles) — not reference data",
    "reserved_male_names": "character name pool plumbing",
    "reserved_female_names": "character name pool plumbing",
}
HANDLED_RELIGION_DETAILS = {"family", "theocracy_government_type",
                            "theocracy_lease_contract_type"}
SKIP_RELIGION_DETAILS = SKIP_FAMILY_FIELDS

HANDLED_FAITH_FIELDS = {"faith_details", "eminent_holy_sites", "holy_sites", "tenets",
                        "doctrines", "tenet_selection_pair", "main_rite", "historical",
                        "origin", "cultures", "clerical_elector_titles"}
SKIP_FAITH_FIELDS = {
    "localization": "flavor term table override — not reference data",
    "holy_order_names": "random holy-order name pool (flavor)",
    "reserved_male_names": "character name pool plumbing",
    "reserved_female_names": "character name pool plumbing",
}
HANDLED_FAITH_DETAILS = {"religion", "color", "icon", "religious_head", "head_of_rite",
                         "theocracy_government_type"}
SKIP_FAITH_DETAILS = {
    "reformed_icon": "art variant swapped in after pagan reformation; base icon shown",
    "graphical_faith": "3D temple asset selection",
}

HANDLED_RITE_FIELDS = {"name", "desc", "icon", "color", "founder", "faith", "cultures",
                       "convert", "create", "history", "tenets", "doctrines",
                       "tenet_selection_pair"}
SKIP_RITE_FIELDS = {
    "localization": "flavor term table override — not reference data",
}

HANDLED_HISTORY_FIELDS = {"created", "main_rite", "religious_head", "known", "permitted",
                          "prohibited", "rites"}
HANDLED_HISTORY_RITE_FIELDS = {"rite", "enabled", "tenet_setup", "doctrines"}


def check(blk, handled, skip, counter, label):
    for k in blk.keys():
        if k not in handled and k not in skip:
            counter[label][k] += 1


def culture_names(keys):
    out = []
    for c in keys:
        raw = ck3.loc(c)
        out.append({"key": c, "name": ck3.render_text(raw) if raw else c})
    return out


def main():
    unhandled = defaultdict(Counter)

    families = []
    for _p, key, blk in ck3.parse_dir(R.RELIGION / "religion_family_types"):
        check(blk, HANDLED_FAMILY_FIELDS, SKIP_FAMILY_FIELDS, unhandled, "family")
        families.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(blk.get("name") or key) or key.removeprefix("rf_").title()),
            "hostilityDoctrine": blk.get("hostility_doctrine"),
        })

    limits_default = {
        "eminentMax": R.define("NReligion", "FAITH_EMINENT_HOLY_SITES_MAX_DEFAULT"),
        "totalMax": R.define("NReligion", "FAITH_HOLY_SITES_MAX_DEFAULT"),
        "eminentMin": R.define("NReligion", "FAITH_EMINENT_HOLY_SITES_MIN_DEFAULT"),
        "totalMin": R.define("NReligion", "FAITH_HOLY_SITES_MIN_DEFAULT"),
    }

    religions, rel_by_id = [], {}
    for _p, rkey, rblk in ck3.parse_dir(R.RELIGION / "religion_types"):
        if not isinstance(rblk, Block):
            continue
        check(rblk, HANDLED_RELIGION_FIELDS, SKIP_RELIGION_FIELDS, unhandled, "religion")
        det = rblk.get("religion_details")
        det = det if isinstance(det, Block) else Block([])
        check(det, HANDLED_RELIGION_DETAILS, SKIP_RELIGION_DETAILS, unhandled, "religion_details")
        traits = rblk.get("traits")
        gov = det.get("theocracy_government_type")
        lease = det.get("theocracy_lease_contract_type")
        main_site = rblk.get("main_holy_site")
        rec = {
            "id": rkey,
            "name": ck3.render_text(ck3.loc(rkey) or rkey),
            "family": det.get("family"),
            "doctrines": rblk.get_all("doctrine"),
            "virtues": trait_list(traits.get("virtues")) if isinstance(traits, Block) else [],
            "sins": trait_list(traits.get("sins")) if isinstance(traits, Block) else [],
            "paganRoots": bool(rblk.get("pagan_roots", False)),
            "theocracyGovernment": {"key": gov, "name": R.title_name(gov)} if gov else None,
            "theocracyLease": {"key": lease, "name": R.title_name(lease)} if lease else None,
            "mainHolySite": main_site,
            "holySiteLimits": {
                "eminentMax": rblk.get("eminent_holy_sites_max", limits_default["eminentMax"]),
                "totalMax": rblk.get("holy_sites_max", limits_default["totalMax"]),
                "eminentMin": rblk.get("eminent_holy_sites_min", limits_default["eminentMin"]),
                "totalMin": rblk.get("holy_sites_min", limits_default["totalMin"]),
            },
        }
        religions.append(rec)
        rel_by_id[rkey] = rec

    history = faith_history(unhandled)

    # --- rites (parsed first so faiths can resolve their main rite) ---
    rite_blocks = {}
    rite_files = {}
    for path, key, blk in ck3.parse_dir(R.RELIGION / "rite_types"):
        if isinstance(blk, Block):
            check(blk, HANDLED_RITE_FIELDS, SKIP_RITE_FIELDS, unhandled, "rite")
            rite_blocks[key] = blk
            rite_files[key] = path.name

    faith_blocks = {}
    faith_files = {}
    for path, fkey, fblk in ck3.parse_dir(R.RELIGION / "faith_types"):
        if isinstance(fblk, Block):
            check(fblk, HANDLED_FAITH_FIELDS, SKIP_FAITH_FIELDS, unhandled, "faith")
            det = fblk.get("faith_details")
            check(det if isinstance(det, Block) else Block([]), HANDLED_FAITH_DETAILS,
                  SKIP_FAITH_DETAILS, unhandled, "faith_details")
            faith_blocks[fkey] = fblk
            faith_files[fkey] = path.name

    # which rites belong to which faith: rite type `faith =`, then history
    # `rites = {}` / `main_rite =` entries move rites between faiths by date.
    rites_of = defaultdict(list)
    for rk, rb in rite_blocks.items():
        if rb.get("faith"):
            rites_of[rb.get("faith")].append({"id": rk, "from": None, "via": "rite type"})
    history_rite_faith = {}
    for fkey, entries in history.items():
        for e in entries:
            ids = [r["id"] for r in e["rites"]] + ([e["mainRite"]] if e["mainRite"] else [])
            for rid in ids:
                if rid not in [x["id"] for x in rites_of[fkey]]:
                    rites_of[fkey].append({"id": rid, "from": e["date"], "via": "history"})
                    history_rite_faith.setdefault(rid, []).append((fkey, e["date"]))

    def main_rite_of(fkey, fblk):
        """(rite key, source) — faith type, else earliest dated history entry,
        else the faith's only scripted rite."""
        if fblk.get("main_rite"):
            return fblk.get("main_rite"), "faith type"
        for e in history.get(fkey, []):
            if e["mainRite"]:
                return e["mainRite"], f"history {e['date']}"
        own = [r["id"] for r in rites_of.get(fkey, []) if r["via"] == "rite type"]
        if len(own) == 1:
            return own[0], "only scripted rite"
        return None, None

    faiths, rites = [], []
    for fkey, fblk in faith_blocks.items():
        det = fblk.get("faith_details")
        rkey = det.get("religion")
        rel = rel_by_id.get(rkey, {})
        main_rite, main_src = main_rite_of(fkey, fblk)
        mr_blk = rite_blocks.get(main_rite)

        faith_doctrines = R.block_list(fblk.get("doctrines"))
        rel_doctrines = rel.get("doctrines", [])
        if mr_blk is not None:
            eff_doctrines = R.merge_doctrines([rel_doctrines, faith_doctrines,
                                               R.block_list(mr_blk.get("doctrines"))])
            tenets = tenet_entries(R.block_list(mr_blk.get("tenets")), selection_pairs(mr_blk))
            tenet_src = "main rite"
        else:
            eff_doctrines = R.merge_doctrines([rel_doctrines, faith_doctrines])
            tenets = tenet_entries(R.block_list(fblk.get("tenets")), selection_pairs(fblk))
            tenet_src = "faith type"

        head = det.get("religious_head")
        hor = det.get("head_of_rite")
        gov = det.get("theocracy_government_type")
        main_by_date = [{"date": e["date"], "rite": e["mainRite"]}
                        for e in history.get(fkey, []) if e["mainRite"]]
        sites = ([{"key": h, "eminent": True} for h in R.block_list(fblk.get("eminent_holy_sites"))]
                 + [{"key": h, "eminent": False} for h in R.block_list(fblk.get("holy_sites"))])
        for s in sites:
            s["name"] = ck3.render_text(ck3.loc(f"holy_site_{s['key']}_name")
                                        or s["key"].replace("_", " ").title())
        name = ck3.loc(fkey)
        desc = ck3.loc(f"{fkey}_desc")
        faiths.append({
            "id": fkey,
            "name": ck3.render_text(name) if name else None,
            "adjective": ck3.render_text(ck3.loc(f"{fkey}_adj") or "") or None,
            "adherent": ck3.render_text(ck3.loc(f"{fkey}_adherent") or "") or None,
            "desc": ck3.render_text(desc) if desc else None,
            "religion": rkey,
            "family": rel.get("family"),
            "color": color_hex(det.get("color")),
            "icon": str(det.get("icon") or fkey).removesuffix(".dds"),
            "religiousHead": {"title": head, "name": R.title_name(head)} if head else None,
            "headOfRite": {"title": hor, "name": R.title_name(hor)} if hor else None,
            "theocracyGovernment": {"key": gov, "name": R.title_name(gov)} if gov else None,
            "holySites": sites,
            "doctrines": eff_doctrines,
            "faithDoctrines": faith_doctrines,
            "tenets": tenets,
            "tenetSource": tenet_src,
            "mainRite": main_rite,
            "mainRiteSource": main_src,
            "mainRiteByDate": main_by_date,
            "rites": [r["id"] for r in rites_of.get(fkey, [])],
            "riteMembership": rites_of.get(fkey, []),
            "historical": bool(fblk.get("historical", False)),
            "origin": fblk.get("origin"),
            "cultures": culture_names(R.block_list(fblk.get("cultures"))),
            "clericalElectorTitles": [{"title": t, "name": R.title_name(t)}
                                      for t in R.block_list(fblk.get("clerical_elector_titles"))],
            "history": history.get(fkey, []),
            "sourceFile": faith_files[fkey],
        })

    faith_by_id = {f["id"]: f for f in faiths}
    main_of = {}
    for f in faiths:
        if f["mainRite"]:
            main_of.setdefault(f["mainRite"], []).append(f["id"])
        for m in f["mainRiteByDate"]:
            main_of.setdefault(m["rite"], [])
            if f["id"] not in main_of[m["rite"]]:
                main_of[m["rite"]].append(f["id"])

    for rk, rb in rite_blocks.items():
        fkey = rb.get("faith")
        f = faith_by_id.get(fkey, {})
        rel = rel_by_id.get(f.get("religion"), {})
        fblk = faith_blocks.get(fkey)
        name_key = rb.get("name") if isinstance(rb.get("name"), str) else rk
        name, name_variants = R.dynamic_text(rb, "name", rk)
        desc, _ = R.dynamic_text(rb, "desc", f"{rk}_desc")
        own_doctrines = R.block_list(rb.get("doctrines"))
        eff = R.merge_doctrines([rel.get("doctrines", []),
                                 R.block_list(fblk.get("doctrines")) if fblk else [],
                                 own_doctrines])
        founder = rb.get("founder")
        dlc, _features = ck3.dlc_tag(rite_files[rk], rb)
        rites.append({
            "id": rk,
            "name": name,
            "nameVariants": name_variants,
            "adjective": ck3.render_text(ck3.loc(f"{name_key}_adj") or "") or None,
            "adherent": ck3.render_text(ck3.loc(f"{name_key}_adherent") or "") or None,
            "desc": desc,
            "faith": fkey,
            "religion": f.get("religion"),
            "historyFaiths": [{"faith": fk, "from": d} for fk, d in history_rite_faith.get(rk, [])],
            "mainOf": main_of.get(rk, []),
            "color": color_hex(rb.get("color")),
            "icon": str(rb.get("icon")).removesuffix(".dds") if rb.get("icon") else None,
            "founder": {"title": founder, "name": R.title_name(founder)} if founder else None,
            "tenets": tenet_entries(R.block_list(rb.get("tenets")), selection_pairs(rb)),
            "doctrines": own_doctrines,
            "effectiveDoctrines": eff,
            "cultures": culture_names(R.block_list(rb.get("cultures"))),
            "convert": rb.get("convert", True) is not False,
            "create": rb.get("create", True) is not False,
            "historyOnly": bool(rb.get("history", False)),
            "dlc": dlc,
            "sourceFile": rite_files[rk],
        })

    faiths.sort(key=lambda f: (f["family"] or "", f["religion"], f["id"]))
    religions.sort(key=lambda r: (r["family"] or "", r["id"]))
    rites.sort(key=lambda r: (r["faith"] or "", r["id"]))

    concepts = {k: {"name": R.concept_name(k), "desc": R.concept(k)} for k in (
        "rite", "mainline_rite", "rite_divergence", "tenet_status", "tenet",
        "eminent_holy_site", "holy_site")}
    ck3.write_json("faiths.json", {
        "families": families, "religions": religions, "faiths": faiths, "rites": rites,
        "concepts": concepts,
        "tenetStatusNames": {s: R.concept_name(f"{s}_tenet_status")
                             for s in ("unknown", "known", "permitted", "prohibited", "core")},
    })
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
    rmissing = [r["id"] for r in rites if not r["name"]]
    if rmissing:
        print(f"⚠ {len(rmissing)} rites without localized names: {rmissing[:10]}")
    no_main = [f["id"] for f in faiths if not f["mainRite"]]
    if no_main:
        print(f"  ({len(no_main)} faiths with no scripted main rite — the game creates a "
              f"dynamic one: {no_main})")
    unknown_rites = sorted({r for f in faiths for r in f["rites"] if r not in rite_blocks})
    if unknown_rites:
        print(f"⚠ history names rites with no rite type: {unknown_rites}")


if __name__ == "__main__":
    main()
