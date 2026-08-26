#!/usr/bin/env python3
"""Build src/data/nicknames.json from common/nicknames/.

Schema documented by the game in _nicknames.info: a nickname is just a key
with optional is_bad / is_prefix flags. Localization is the bare key (keys
already carry the nick_ prefix). Assignment is entirely event-driven — the
data files contain no triggers, so "how to earn it" is not derivable here;
the _desc loc strings are character-context flavor, not acquisition rules.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP_FIELDS = {
    # nothing skipped — the schema is only is_bad / is_prefix
}

HANDLED_FIELDS = {"is_bad", "is_prefix"}

# The one key without its own loc entry: the game reuses the base nickname's
# display text for the rumoured variant (verified: no nick_the_bastard_rumoured
# loc key exists anywhere in english/).
NAME_FALLBACKS = {"nick_the_bastard_rumoured": "nick_the_bastard"}

# File prefixes not in ck3.PREFIX_TO_DLC: "roco" files self-identify as
# "Royal Court Character Nicknames" in their header comment.
LOCAL_PREFIX_DLC = {"roco": "The Royal Court"}


def main():
    entries = ck3.parse_dir(ck3.COMMON / "nicknames")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1
        dlc, features = ck3.dlc_tag(path, blk)
        if dlc is None:
            m = path.name.split("_")
            if len(m) > 1 and m[1] in LOCAL_PREFIX_DLC:
                dlc = LOCAL_PREFIX_DLC[m[1]]
        raw = ck3.loc(key) or ck3.loc(NAME_FALLBACKS.get(key, ""))
        out.append({
            "id": key,
            "name": ck3.render_text(raw) if raw else None,
            "isBad": bool(blk.get("is_bad", False)),
            "isPrefix": bool(blk.get("is_prefix", False)),
            "dlc": dlc,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: ((r["name"] or "").lower().removeprefix("the "), r["id"]))
    ck3.write_json("nicknames.json", out)

    if unhandled:
        print("⚠ unhandled nickname fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} nicknames without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
