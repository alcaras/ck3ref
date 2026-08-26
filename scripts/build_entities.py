#!/usr/bin/env python3
"""Entity registry + alias index (v0: men-at-arms, archetypes, terrains).

Grows a type per phase. aliasIndex only contains names safe to auto-link in
free text (scan) — common-word names register with scan=False so <Term id>
resolves but text scanning ignores them (the owreference trait lesson).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3


def main():
    entities = []
    seen_types = set()

    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "men_at_arms_types"):
        name = ck3.render_text(ck3.loc(key) or key)
        entities.append({
            "id": key, "slug": key, "type": "maa", "name": name,
            "page": "men-at-arms", "icon": f"img/maa/{key}.webp", "scan": True,
        })
        t = blk.get("type")
        if isinstance(t, str):
            seen_types.add(t)

    for t in sorted(seen_types):
        entities.append({
            "id": f"maa_type_{t}", "slug": t, "type": "maa_archetype",
            "name": ck3.render_text(ck3.loc(t) or t.replace("_", " ").title()),
            "page": "men-at-arms", "scan": False,
        })

    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "terrain_types"):
        entities.append({
            "id": f"terrain_{key}", "slug": key, "type": "terrain",
            "name": ck3.render_text(ck3.loc(key) or key.title()),
            "page": None, "scan": False,  # terrain page lands phase 1
        })

    alias_index = sorted(
        ({"alias": e["name"], "id": e["id"]} for e in entities
         if e.get("scan") and e.get("name")),
        key=lambda a: -len(a["alias"]),
    )
    ck3.write_json("entities.json", {"entities": sorted(entities, key=lambda e: e["id"]),
                                     "aliasIndex": alias_index})


if __name__ == "__main__":
    main()
