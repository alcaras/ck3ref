#!/usr/bin/env python3
"""Entity registry + alias index.

Reads the already-generated src/data/*.json (run after the build_* scripts).
aliasIndex only contains names safe to auto-link in free text (scan=True) —
common-word names register with scan=False so <Term id> resolves but text
scanning ignores them (the owreference trait lesson).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

DATA = ck3.ROOT / "src" / "data"


def load(name):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    entities = []

    def add(id_, type_, name, page, icon=None, scan=False, slug=None):
        if name:
            entities.append({"id": id_, "slug": slug or id_.split(":")[-1],
                             "type": type_, "name": name, "page": page,
                             **({"icon": icon} if icon else {}), "scan": scan})

    maa = load("maa.json") or []
    for r in maa:
        add(r["id"], "maa", r["name"], "men-at-arms", f"img/maa/{r['id']}.webp", scan=True)
    for t in sorted({r["type"] for r in maa if r.get("type")}):
        add(f"maa_type_{t}", "maa_archetype",
            ck3.render_text(ck3.loc(t) or t.replace("_", " ").title()),
            "men-at-arms", scan=False, slug=t)

    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "terrain_types"):
        add(f"terrain_{key}", "terrain",
            ck3.render_text(ck3.loc(key) or key.title()), "terrain", scan=False, slug=key)

    for r in load("holdings.json") or []:
        add(r["id"], "holding", r["name"], "holdings",
            f"img/holdings/{r['id']}.webp", scan=False)
    for r in load("great_projects.json") or []:
        add(r["id"], "great_project", r["name"], "great-projects", scan=False)
    act = load("activities.json") or {"activities": []}
    for r in act["activities"]:
        add(r["id"], "activity", r["name"], "activities",
            f"img/activities/{r['id']}.webp", scan=" " in r["name"])
    dec = load("decisions.json") or {"decisions": []}
    for r in dec["decisions"]:
        add(r["id"], "decision", r["name"], "decisions", scan=False)

    for r in load("traits.json") or []:
        add(r["id"], "trait", r["name"], "traits",
            f"img/traits/{r['id']}.webp", scan=False)

    ls = load("lifestyles.json") or {"trees": [], "focuses": []}
    for t in ls["trees"]:
        for p in t["perks"]:
            add(p["id"], "perk", p["name"], "lifestyles", scan=False)
    for f in ls["focuses"]:
        add(f["id"], "focus", f["name"], "lifestyles", scan=False)

    for r in load("legacies.json") or []:
        add(r["id"], "legacy_track", r["name"], "legacies",
            f"img/legacies/{r['id']}.webp", scan=False)
        for p in r["perks"]:
            add(p["id"], "dynasty_perk", p["name"], "legacies", scan=False)

    for r in load("buildings.json") or []:
        if r.get("tier") == 1 or r["id"] == r.get("chain"):
            add(r["id"], "building", r["name"], "buildings",
                f"img/buildings/{r['icon']}.webp", scan=False)

    fa = load("faiths.json") or {"faiths": [], "religions": []}
    for r in fa["faiths"]:
        add(r["id"], "faith", r["name"], "faiths", f"img/faith/{r['id']}.webp", scan=True)
    for r in fa["religions"]:
        add(r["id"], "religion", r["name"], "faiths", scan=True)

    doc = load("doctrines.json") or {"doctrines": []}
    for r in doc["doctrines"]:
        add(r["id"], "tenet" if r.get("isTenet") else "doctrine", r["name"],
            "doctrines", scan=False)

    for r in load("holy_sites.json") or []:
        add(f"holy_site_{r['id']}", "holy_site", r["name"], "holy-sites",
            scan=False, slug=r["id"])

    sch = load("schemes.json") or {"schemes": []}
    for r in sch["schemes"]:
        add(r["id"], "scheme", r["name"], "schemes",
            f"img/schemes/{r['id']}.webp", scan=False)

    for r in load("struggles.json") or []:
        add(r["id"], "struggle", r["name"], "struggles", scan=True)
    for r in load("situations.json") or []:
        add(r["id"], "situation", r["name"], "situations", scan=False)
    lg = load("legends.json") or {"types": [], "seeds": []}
    for r in lg.get("types", []):
        add(r["id"], "legend_type", r["name"], "legends", scan=False)
    for r in lg.get("seeds", []):
        add(r["id"], "legend_seed", r["name"], "legends", scan=True)
    for r in load("epidemics.json") or []:
        add(r["id"], "epidemic", r["name"], "epidemics",
            f"img/epidemics/{r['id']}.webp", scan=True)

    for r in load("task_contracts.json") or []:
        add(r["id"], "task_contract", r["name"], "task-contracts", scan=False)
    dom = load("domiciles.json") or {"types": []}
    for r in dom.get("types", []):
        add(r["id"], "domicile", r["name"], "domiciles", scan=False)
    acc = load("accolades.json") or {}
    for r in (acc.get("attributes", []) if isinstance(acc, dict) else []):
        add(r["id"], "accolade", r.get("name"), "accolades", scan=False)

    art = load("artifacts.json") or {"named": []}
    for r in art.get("named", []):
        add(r["id"], "artifact", r["name"], "artifacts", scan=False)

    for r in load("cultures.json") or []:
        add(r["id"], "culture", r["name"], "cultures", scan=True)

    for r in load("governments.json") or []:
        add(r["id"], "government", r["name"], "governments",
            f"img/governments/{r['id']}.webp", scan=False)
    lw = load("laws.json") or []
    for g in (lw if isinstance(lw, list) else lw.get("groups", [])):
        for r in g.get("laws", []):
            add(r["id"], "law", r["name"], "laws", scan=False)
    ct = load("contracts.json") or {}
    for r in (ct.get("contracts", []) if isinstance(ct, dict) else []):
        add(r["id"], "contract", r["name"], "contracts", scan=False)

    cp = load("court_positions.json") or {"positions": []}
    for r in cp["positions"]:
        add(r["id"], "court_position", r["name"], "court-positions",
            f"img/court/{r['id']}.webp", scan=True)
    cl = load("council.json") or {"positions": []}
    for r in cl["positions"]:
        add(r["id"], "council_position", r["name"], "council", scan=False)

    for r in (load("cbs.json") or {"cbs": []})["cbs"]:
        add(r["id"], "cb", r["name"], "casus-belli",
            f"img/cb/{r['id']}.webp", scan=False)

    ti = load("titles.json") or {"roots": []}

    def walk_titles(node, empire_page=None):
        page = empire_page
        if node["tier"] in ("hegemony", "empire"):
            page = f"titles/{node['id']}"
        if node["tier"] in ("hegemony", "empire", "kingdom", "duchy"):
            add(node["id"], f"title_{node['tier']}", node["name"],
                page or "titles", scan=False)
        for ch in node.get("children", []):
            walk_titles(ch, page)

    for r in ti["roots"]:
        walk_titles(r)

    for r in load("concepts.json") or []:
        add(f"concept_{r['id']}", "concept", r["name"], "concepts",
            scan=" " in r["name"], slug=r["id"])

    tr = load("traditions.json") or {"traditions": []}
    for r in tr["traditions"]:
        add(r["id"], "tradition", r["name"], "traditions",
            scan=" " in r["name"])
    for r in load("innovations.json") or []:
        add(r["id"], "innovation", r["name"], "innovations",
            f"img/innovations/{r['id']}.webp", scan=True)
    for r in load("pillars.json") or []:
        add(r["id"], "pillar", r["name"], "pillars", scan=False)

    # de-dup by id (later registrations win nothing; first wins)
    seen = {}
    for e in entities:
        seen.setdefault(e["id"], e)
    entities = list(seen.values())

    names = {}
    for e in entities:
        if e["scan"]:
            names.setdefault(e["name"].lower(), e["id"])
    alias_index = sorted(({"alias": n, "id": i} for n, i in names.items()),
                         key=lambda a: -len(a["alias"]))
    ck3.write_json("entities.json", {
        "entities": sorted(entities, key=lambda e: e["id"]),
        "aliasIndex": alias_index,
    })


if __name__ == "__main__":
    main()
