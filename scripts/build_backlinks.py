#!/usr/bin/env python3
"""Backlinks: what references each entity, across every generated dataset.

Two passes over src/data/*.json:
  1. structural — any string field whose value is an entity id (or a nested
     {key|id} ref) links source → target;
  2. textual — entity NAMES that are safe to scan (entities.json aliasIndex)
     found in rendered effect/description text.

Output: {entity_id: [{page, anchor, label, context}]}, capped per target so a
few very popular entities (gold, prestige) can't dominate the file.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

DATA = ck3.ROOT / "src" / "data"
MAX_PER_TARGET = 60

# datasets that describe themselves (skip self-referential noise)
SKIP_FILES = {"entities.json", "backlinks.json", "search-index.json",
              "event-categories.json", "defines.json", "startworld.json",
              "startdates.json", "titles.json", "genetics.json", "dlc.json"}

# fields that are ids of the record itself, not references
SELF_FIELDS = {"id", "slug", "key", "icon", "sourceFile", "file", "chain"}


def load_entities():
    e = json.loads((DATA / "entities.json").read_text(encoding="utf-8"))
    by_id = {x["id"]: x for x in e["entities"]}
    scan = [(a["alias"], a["id"]) for a in e["aliasIndex"] if len(a["alias"]) >= 5]
    scan.sort(key=lambda p: -len(p[0]))
    return by_id, scan


def records_of(data):
    """Yield (record, section) for the shapes our datasets use."""
    if isinstance(data, list):
        for r in data:
            if isinstance(r, dict):
                yield r, None
    elif isinstance(data, dict):
        for section, val in data.items():
            if isinstance(val, list):
                for r in val:
                    if isinstance(r, dict):
                        yield r, section


def walk_strings(obj, out, depth=0):
    """Collect (value, path-ish label) for every string in a record."""
    if depth > 6:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in SELF_FIELDS:
                continue
            walk_strings(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            walk_strings(v, out, depth + 1)


def main():
    by_id, scan = load_entities()
    links = defaultdict(list)
    counts = defaultdict(int)

    def add(target, page, anchor, label, context):
        if counts[target] >= MAX_PER_TARGET:
            return
        counts[target] += 1
        links[target].append({"page": page, "anchor": anchor,
                              "label": label, "context": context})

    for f in sorted(DATA.glob("*.json")):
        if f.name in SKIP_FILES:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec, section in records_of(data):
            src_id = rec.get("id")
            src_name = rec.get("name")
            if not src_id or not src_name:
                continue
            src_ent = by_id.get(src_id)
            page = src_ent["page"] if src_ent and src_ent.get("page") else None
            if not page:
                continue
            strings = []
            walk_strings(rec, strings)
            seen_targets = set()
            # structural: strings that are entity ids
            for s in strings:
                if s in by_id and s != src_id and s not in seen_targets:
                    seen_targets.add(s)
                    add(s, page, src_id, src_name, section or f.stem)
            # textual: scannable names inside longer prose
            prose = " ".join(s for s in strings if len(s) > 12)
            if prose:
                low = prose.lower()
                for alias, tid in scan:
                    if tid == src_id or tid in seen_targets:
                        continue
                    if alias in low:
                        seen_targets.add(tid)
                        add(tid, page, src_id, src_name, section or f.stem)
                    if len(seen_targets) > 40:
                        break

    out = {k: sorted(v, key=lambda x: (x["page"], x["anchor"]))
           for k, v in sorted(links.items())}
    ck3.write_json("backlinks.json", out)
    print(f"  {sum(len(v) for v in out.values())} links across {len(out)} entities")


if __name__ == "__main__":
    main()
