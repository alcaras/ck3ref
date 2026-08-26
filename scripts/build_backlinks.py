#!/usr/bin/env python3
"""Backlinks: scan all generated datasets for entity references.

v0: counters + requirements in maa.json produce links between MAA entries and
archetypes/innovations. Grows automatically as datasets join src/data/.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

DATA = ck3.ROOT / "src" / "data"


def main():
    backlinks = defaultdict(list)
    maa_path = DATA / "maa.json"
    if maa_path.exists():
        maa = json.loads(maa_path.read_text(encoding="utf-8"))
        for rec in maa:
            for arch in rec.get("counters", {}):
                backlinks[f"maa_type_{arch}"].append({
                    "page": "men-at-arms", "anchor": rec["id"],
                    "text": f"countered by {rec['name']}",
                })
            for req in rec.get("requirements", []):
                backlinks[f"{req['kind']}:{req['key']}"].append({
                    "page": "men-at-arms", "anchor": rec["id"],
                    "text": f"unlocks {rec['name']}",
                })
    ck3.write_json("backlinks.json", {k: sorted(v, key=lambda x: x["anchor"])
                                      for k, v in sorted(backlinks.items())})


if __name__ == "__main__":
    main()
