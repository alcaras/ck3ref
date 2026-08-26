#!/usr/bin/env python3
"""Build public/data/search-index.json for the header search.

Compact rows: {n: name, t: type label, u: url path (no base), c: icon path?}.
Sources: built tabs (regex over tabs.ts — keep its literal format stable) and
the entity registry.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

TYPE_LABELS = {
    "maa": "Men-at-Arms", "maa_archetype": "MAA archetype", "trait": "Trait",
    "perk": "Perk", "focus": "Focus", "legacy_track": "Dynasty Legacy",
    "dynasty_perk": "Legacy Perk", "building": "Building", "faith": "Faith",
    "religion": "Religion", "doctrine": "Doctrine", "tenet": "Tenet",
    "holy_site": "Holy Site", "concept": "Concept", "tradition": "Tradition",
    "innovation": "Innovation", "pillar": "Culture Pillar", "terrain": "Terrain",
    "government": "Government", "law": "Law", "contract": "Vassal Contract",
    "cb": "Casus Belli", "court_position": "Court Position",
    "council_position": "Council", "culture": "Culture", "title": "Title",
    "decision": "Decision", "activity": "Activity", "scheme": "Scheme",
    "nickname": "Nickname", "artifact": "Artifact",
}


def main():
    rows = []
    tabs_src = (ck3.ROOT / "src/data/tabs.ts").read_text(encoding="utf-8")
    for m in re.finditer(r"\{ slug: '([^']+)', label: '((?:[^'\\]|\\.)+)',.*?status: '(\w+)'", tabs_src):
        if m.group(3) == "built":
            rows.append({"n": m.group(2).replace("\\'", "'").replace("\\&", "&"),
                         "t": "Page", "u": f"/{m.group(1)}"})

    ent = json.loads((ck3.ROOT / "src/data/entities.json").read_text(encoding="utf-8"))
    for e in ent["entities"]:
        if not e.get("page"):
            continue
        row = {"n": e["name"], "t": TYPE_LABELS.get(e["type"], e["type"]),
               "u": f"/{e['page']}#{e['slug']}"}
        if e.get("icon"):
            row["c"] = "/" + e["icon"]
        rows.append(row)

    out = ck3.ROOT / "public/data/search-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"✓ wrote public/data/search-index.json — {len(rows)} rows")


if __name__ == "__main__":
    main()
