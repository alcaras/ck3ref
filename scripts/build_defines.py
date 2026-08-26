#!/usr/bin/env python3
"""Build src/data/defines.json — every engine constant, grouped by namespace,
with the comment on its line (the game's own documentation) attached."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

FILES = sorted((ck3.COMMON / "defines").rglob("*.txt"))

_NS = re.compile(r"^(\w+)\s*=\s*\{")
_KV = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*([^#\n]+?)\s*(?:#\s*(.*))?$")


def main():
    out = []
    for f in FILES:
        rel = f.relative_to(ck3.COMMON / "defines").as_posix()
        ns = None
        for line in f.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            m = _NS.match(line.strip())
            if m and m.group(1)[0] == "N":
                ns = m.group(1)
                continue
            kv = _KV.match(line)
            if kv and ns:
                val = kv.group(2).strip().strip('"')
                if val == "{":  # multi-line list values: keep marker
                    val = "{…}"
                out.append({"ns": ns, "key": kv.group(1), "value": val,
                            "comment": (kv.group(3) or "").strip() or None,
                            "file": rel})
    ck3.write_json("defines.json", out)
    ns_count = len({d["ns"] for d in out})
    print(f"  {ns_count} namespaces")


if __name__ == "__main__":
    main()
