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
            ck3.render_text(ck3.loc(key) or key.title()), None, scan=False, slug=key)

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

    for r in load("concepts.json") or []:
        add(r["id"], "concept", r["name"], "concepts", scan=False)

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
