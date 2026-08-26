#!/usr/bin/env python3
"""Per-patch changelog: diff every src/data/*.json against the last snapshot.

Ported in spirit from owreference's changelog.py: automatic tracking (new
datasets join on first run), id-keyed entry diffs, per-file line caps,
prepend + idempotent re-runs.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

SNAPDIR = ck3.ROOT / "data" / "snapshots"
CHANGELOG = ck3.ROOT / "CHANGELOG.md"
PATCH = ck3.ROOT / "data" / "patch.json"
MAX_LINES = 120
SUMMARY_ONLY = {"entities.json", "backlinks.json"}


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def entry_map(data):
    if isinstance(data, list) and data and isinstance(data[0], dict):
        for idk in ("id", "key", "slug", "name"):
            ids = [e.get(idk) for e in data]
            if all(ids) and len(set(ids)) == len(ids):
                return {e[idk]: e for e in data}
    return None


def diff_file(name, old, new, lines):
    om, nm = entry_map(old), entry_map(new)
    if name in SUMMARY_ONLY or om is None or nm is None:
        if old != new:
            def size(d):
                return len(d) if isinstance(d, (list, dict)) else 1
            lines.append(f"- ✏️ `{name}` changed ({size(old)} → {size(new)} entries)")
        return
    for k in nm:
        if k not in om:
            lines.append(f"- ➕ `{name}` added **{k}**")
    for k in om:
        if k not in nm:
            lines.append(f"- ➖ `{name}` removed **{k}**")
    for k in nm:
        if k in om and om[k] != nm[k]:
            changed = [f for f in set(om[k]) | set(nm[k]) if om[k].get(f) != nm[k].get(f)]
            lines.append(f"- ✏️ `{name}` **{k}**: {', '.join(sorted(changed))}")


def main():
    version = "unversioned"
    if PATCH.exists():
        version = load(PATCH).get("version", version)
    snap = SNAPDIR / version
    tracked = sorted((ck3.ROOT / "src" / "data").glob("*.json"))
    lines = []
    for f in tracked:
        new = load(f)
        oldf = snap / f.name
        if not oldf.exists():
            n = len(new) if isinstance(new, (list, dict)) else 1
            lines.append(f"- 🌱 `{f.name}` now tracked ({n} entries)")
        else:
            per_file = []
            diff_file(f.name, load(oldf), new, per_file)
            if len(per_file) > MAX_LINES:
                per_file = per_file[:MAX_LINES] + [f"- … and {len(per_file) - MAX_LINES} more changes in `{f.name}`"]
            lines.extend(per_file)

    snap.mkdir(parents=True, exist_ok=True)
    for f in tracked:
        (snap / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    if not lines:
        print("✓ changelog: no changes")
        return
    header = f"## {version}\n\n"
    body = header + "\n".join(lines) + "\n\n"
    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n\n"
    if header in existing:  # idempotent re-run: replace section
        pre, _, rest = existing.partition(header)
        _, _, tail = rest.partition("\n## ")
        existing = pre + ("\n## " + tail if tail else "")
    top, _, rest = existing.partition("\n")
    CHANGELOG.write_text(top + "\n\n" + body + rest.lstrip("\n"), encoding="utf-8")
    print(f"✓ changelog: {len(lines)} lines under {version}")


if __name__ == "__main__":
    main()
