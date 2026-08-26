#!/usr/bin/env python3
"""Slot constants for the province planner, read from defines NProvince.

Only the numbers the game states are emitted; how slots unlock as a holding
levels up is not a single constant in the files, so it is not modelled.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

KEYS = ["BARONY_BUILDING_SLOTS", "COUNTY_BUILDING_SLOTS", "MAX_BUILDINGS"]


def main():
    text = (ck3.COMMON / "defines" / "00_defines.txt").read_text(
        encoding="utf-8-sig", errors="replace")
    out = {}
    for k in KEYS:
        m = re.search(rf"^\s*{k}\s*=\s*(\d+)\s*(?:#\s*(.*))?$", text, re.M)
        if m:
            out[k] = {"value": int(m.group(1)),
                      "comment": (m.group(2) or "").strip() or None}
    ck3.write_json("province-rules.json", out)
    print("  " + ", ".join(f"{k}={v['value']}" for k, v in out.items()))


if __name__ == "__main__":
    main()
