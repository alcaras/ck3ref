#!/usr/bin/env python3
"""Build the events browser index.

9,792 events is too much for one page's HTML, so this emits:
  src/data/event-categories.json  — folder/namespace rollup (rendered inline)
  public/data/event-index.json    — the searchable index, fetched on demand

Per event we keep what a reader can act on: id, namespace, type, title/desc
(rendered), option count, whether it's hidden, DLC, and its source file.
Full option trees are deliberately out of scope — they are effect scripts, and
rendering them honestly needs the whole effect layer (a later phase).
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

EVENTS = ck3.REF / "game" / "events"

TYPES = {"character_event": "character", "letter_event": "letter",
         "court_event": "court", "activity_event": "activity",
         "duel_event": "duel", "empty": "hidden"}


def first_loc_ref(v):
    """A title/desc field is either a loc key or a dynamic block; take the last
    plain desc in a block (the untriggered fallback) per the shared quirk."""
    if isinstance(v, str):
        return v
    refs = []

    def walk(b):
        if isinstance(b, Tagged):
            b = b.block
        if not isinstance(b, Block):
            return
        for k, _op, val in b:
            if k in ("desc", "text", "title") and isinstance(val, str):
                refs.append(val)
            elif isinstance(val, (Block, Tagged)):
                walk(val)
    walk(v)
    return refs[-1] if refs else None


def main():
    files = sorted(EVENTS.rglob("*.txt"))
    events = []
    cats = Counter()
    for f in files:
        try:
            blk = ck3.parse_file(f)
        except Exception as e:
            print(f"⚠ parse failed: {f.name}: {e}")
            continue
        ns = blk.get("namespace")
        rel = f.relative_to(EVENTS)
        folder = rel.parts[0] if len(rel.parts) > 1 else "root"
        for key, _op, v in blk:
            if not (isinstance(key, str) and "." in key and isinstance(v, Block)):
                continue
            dlc, _feats = ck3.dlc_tag(f, v)
            title_ref = first_loc_ref(v.get("title"))
            desc_ref = first_loc_ref(v.get("desc"))
            title = ck3.render_text(ck3.loc(title_ref) or "") if title_ref else None
            desc = ck3.render_text(ck3.loc(desc_ref) or "") if desc_ref else None
            etype = None
            for t in TYPES:
                if v.has(t) or v.get("type") == t:
                    etype = TYPES[t]
                    break
            hidden = bool(v.get("hidden", False))
            events.append({
                "id": key,
                "ns": (ns if isinstance(ns, str) else key.split(".")[0]),
                "folder": folder,
                "file": f.name,
                "type": etype or ("hidden" if hidden else "character"),
                "title": (title or "").strip() or None,
                "desc": ((desc or "").strip()[:220] or None),
                "options": len(v.get_all("option")),
                "hidden": hidden,
                "dlc": dlc,
            })
            cats[folder] += 1

    events.sort(key=lambda e: (e["folder"], e["id"]))
    out = ck3.ROOT / "public/data/event-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(events, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"✓ wrote public/data/event-index.json — {len(events)} events")

    by_folder = []
    for folder, n in sorted(cats.items()):
        sample = [e for e in events if e["folder"] == folder]
        by_folder.append({
            "folder": folder,
            "count": n,
            "named": sum(1 for e in sample if e["title"]),
            "dlcs": sorted({e["dlc"] for e in sample if e["dlc"]}),
            "namespaces": sorted({e["ns"] for e in sample})[:12],
        })
    ck3.write_json("event-categories.json", by_folder)


if __name__ == "__main__":
    main()
