#!/usr/bin/env python3
"""Build src/data/holdings.json from common/holdings/.

Schema documented by the game in _holdings.info. Since 1.21 a holding type
names its primary DISTRICT (whose primary building — castle_01, city_01… —
is the holding's main building) and the roster of standard districts it can
build; inheritance and domain-limit rules and heir-government gates are as
before. District and building details live in districts.json /
buildings.json (run build_districts.py first); this dataset
cross-references them by key instead of duplicating.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block

HANDLED_FIELDS = {
    "primary_district", "districts", "can_be_inherited",
    "counts_toward_domain_limit_if_disabled", "required_heir_government_types",
    "parameters",
}

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {}


def main():
    buildings = json.loads(
        (ck3.ROOT / "src" / "data" / "buildings.json").read_text(encoding="utf-8"))
    by_id = {b["id"]: b for b in buildings}
    chain_len = Counter(b["chain"] for b in buildings)
    districts = json.loads(
        (ck3.ROOT / "src" / "data" / "districts.json").read_text(encoding="utf-8"))["districts"]
    d_by_id = {d["id"]: d for d in districts}

    def building_ref(key):
        """Cross-reference into buildings.json (key is a tier-1 chain root)."""
        b = by_id.get(key)
        if b is None:
            return {"id": key, "name": key.replace("_", " ").title(),
                    "category": None, "tiers": None, "dlc": None, "missing": True}
        return {"id": key, "name": b["name"], "category": b["category"],
                "tiers": chain_len[b["chain"]], "dlc": b["dlc"], "icon": b["icon"]}

    def district_ref(key):
        d = d_by_id.get(key)
        if d is None:
            return {"id": key, "name": key.replace("_", " "), "missing": True}
        return {"id": key, "name": d["name"], "type": d["type"],
                "icon": d["icon"], "buildings": len(d["buildings"]),
                "unlockedBy": d["unlockedBy"], "dlc": d["dlc"]}

    entries = ck3.parse_dir(ck3.COMMON / "holdings")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if not isinstance(blk, Block):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name = ck3.loc(key)
        governments = []
        rg = blk.get("required_heir_government_types")
        if isinstance(rg, Block):
            for g in rg.values():
                gname = ck3.loc(f"{g}_name") or ck3.loc(g)
                governments.append({"id": g,
                                    "name": ck3.render_text(gname) if gname else g.replace("_", " ").title()})

        roster = []
        dl = blk.get("districts")
        if isinstance(dl, Block):
            roster = [district_ref(d) for d in dl.values() if isinstance(d, str)]
        pd = blk.get("primary_district")
        primary = district_ref(pd) if isinstance(pd, str) else None
        pdd = d_by_id.get(pd) if isinstance(pd, str) else None
        main_building = (building_ref(pdd["primaryBuilding"]["id"])
                         if pdd and pdd.get("primaryBuilding") else None)
        # buildings of the holding district itself (castle-only lines etc.)
        own = [building_ref(b["id"]) for b in (pdd or {}).get("buildings", [])]

        params = []
        pb = blk.get("parameters")
        if isinstance(pb, Block):
            params = [p for p in pb.values() if isinstance(p, str)]

        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "primaryDistrict": primary,
            "primaryBuilding": main_building,
            "buildings": own,
            "districts": roster,
            "canBeInherited": bool(blk.get("can_be_inherited", True)),
            "countsTowardDomainLimitIfDisabled":
                bool(blk.get("counts_toward_domain_limit_if_disabled", True)),
            "requiredHeirGovernments": governments,
            "parameters": params,
            "icon": key,
            "sourceFile": path.name,
        })

    ck3.write_json("holdings.json", out)

    if unhandled:
        print("⚠ unhandled holding fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing}")
    dangling = [b["id"] for r in out
                for b in [r["primaryBuilding"] or {}, r["primaryDistrict"] or {},
                          *r["buildings"], *r["districts"]] if b.get("missing")]
    if dangling:
        print(f"⚠ building/district keys not found: {sorted(set(dangling))}")


if __name__ == "__main__":
    main()
