#!/usr/bin/env python3
"""Build src/data/startworld.json — where each culture and faith starts.

Joins game/history/provinces (culture/religion per province id) to
common/landed_titles (barony → province id → county → duchy → kingdom), so
every culture and faith gets a province count and its county/region spread at
the 867 baseline that province history encodes.

Province history has no dated blocks for culture/religion in practice (the
1066 differences are applied by history/titles + effects), so this is the
"world as scripted" view, not a per-bookmark diff. That caveat is rendered on
the pages that consume it.
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

HIST = ck3.REF / "game" / "history" / "provinces"


def province_index():
    """province id -> (county_id, duchy_id, kingdom_id)."""
    idx = {}

    def walk(node_key, node, county=None, duchy=None, kingdom=None):
        tier = node_key[:2] if isinstance(node_key, str) else ""
        if tier == "k_":
            kingdom = node_key
        elif tier == "d_":
            duchy = node_key
        elif tier == "c_":
            county = node_key
        if tier == "b_":
            pid = node.get("province")
            if isinstance(pid, int):
                idx[pid] = (county, duchy, kingdom)
            return
        for k, _op, v in node:
            if isinstance(k, str) and k[:2] in ("e_", "k_", "d_", "c_", "b_") \
                    and isinstance(v, (Block, Tagged)):
                walk(k, v if isinstance(v, Block) else v.block, county, duchy, kingdom)

    for f in sorted((ck3.COMMON / "landed_titles").glob("*.txt")):
        if f.name.startswith("_"):
            continue
        for key, _op, v in ck3.parse_file(f):
            if isinstance(key, str) and isinstance(v, Block):
                walk(key, v)
    return idx


_PROV = re.compile(r"^(\d+)\s*=\s*\{", re.M)
_FIELD = re.compile(r'^\s*(culture|religion)\s*=\s*"?([\w.-]+)"?', re.M)


def province_setup():
    """province id -> {culture, religion} (top-level fields only)."""
    out = {}
    for f in sorted(HIST.glob("*.txt")):
        text = f.read_text(encoding="utf-8-sig", errors="replace")
        ms = list(_PROV.finditer(text))
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            body = text[m.end():end]
            fields = {}
            for k, v in _FIELD.findall(body):
                fields.setdefault(k, v)
            if fields:
                out[int(m.group(1))] = fields
    return out


def main():
    idx = province_index()
    setup = province_setup()
    titles = {}
    import json
    tj = json.loads((ck3.ROOT / "src/data/titles.json").read_text(encoding="utf-8"))

    def walk(n):
        titles[n["id"]] = n["name"]
        for c in n.get("children", []):
            walk(c)
    for r in tj["roots"]:
        walk(r)

    cultures = defaultdict(lambda: {"provinces": 0, "counties": set(), "kingdoms": Counter()})
    faiths = defaultdict(lambda: {"provinces": 0, "counties": set(), "kingdoms": Counter()})

    for pid, fields in setup.items():
        county, _duchy, kingdom = idx.get(pid, (None, None, None))
        for key, bucket in (("culture", cultures), ("religion", faiths)):
            val = fields.get(key)
            if not val:
                continue
            b = bucket[val]
            b["provinces"] += 1
            if county:
                b["counties"].add(county)
            if kingdom:
                b["kingdoms"][kingdom] += 1

    def pack(bucket):
        out = {}
        for k, v in bucket.items():
            top = [{"id": t, "name": titles.get(t, t), "n": n}
                   for t, n in v["kingdoms"].most_common(6)]
            out[k] = {"provinces": v["provinces"], "counties": len(v["counties"]),
                      "regions": top}
        return out

    ck3.write_json("startworld.json", {
        "cultures": pack(cultures),
        "faiths": pack(faiths),
        "totalProvinces": len(setup),
        "mappedProvinces": sum(1 for p in setup if p in idx),
    })
    print(f"  {len(cultures)} cultures, {len(faiths)} faiths placed across "
          f"{len(setup)} provinces")


if __name__ == "__main__":
    main()
