#!/usr/bin/env python3
"""Build src/data/concepts.json from common/game_concepts/.

No _*.info schema doc ships for this category; fields observed in the data are
alias / parent / texture / framesize / frame / requires_dlc_flag /
shown_in_encyclopedia. Every field is emitted, consciously skipped
(SKIP_FIELDS), or reported unhandled — audit.py fails on unhandled fields
after a patch.

Loc contract: name = game_concept_<key>, description = game_concept_<key>_desc,
and every alias has its own game_concept_<alias> name (verified: 1376/1376).
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "texture": "in-game tooltip icon; paths scatter across gfx/, no art need for a text glossary",
    "framesize": "sprite-sheet geometry for texture",
    "frame": "sprite-sheet frame index for texture",
}

HANDLED_FIELDS = {"alias", "parent", "requires_dlc_flag", "shown_in_encyclopedia"}

# $EFFECT_LIST_BULLET$ is defined GUI-side, not in loc, so render_text can't
# resolve it; the game draws it as a list bullet.
BULLET = "$EFFECT_LIST_BULLET$"


def main():
    entries = ck3.parse_dir(ck3.COMMON / "game_concepts")
    unhandled = Counter()
    unknown_flags = set()
    hidden = []
    out = []

    for path, key, blk in entries:
        if not isinstance(blk, Block):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        # the game's own encyclopedia hides these (tutorial helpers, zoom
        # levels, the dynasty-renown ladder, story-cycle blurbs) — mirror it
        if blk.get("shown_in_encyclopedia") is False:
            hidden.append(key)
            continue

        name = ck3.render_text(ck3.loc(f"game_concept_{key}") or key.replace("_", " ").title())
        raw_desc = ck3.loc(f"game_concept_{key}_desc")
        desc = ck3.render_text(raw_desc.replace(BULLET, "•")) if raw_desc else None
        if desc:
            # a run of bullets whose items were all dynamic ([Get…] lists the
            # renderer can't resolve) collapses to one honest placeholder line
            desc = re.sub(r"(?:\n\s*•\s*…\s*(?=\n|$))+", "\n• …", desc)

        aliases = []
        seen = {name.lower()}
        ab = blk.get("alias")
        if isinstance(ab, Block):
            for a in ab.values():
                if not isinstance(a, str):
                    continue
                an = ck3.loc(f"game_concept_{a}")
                an = ck3.render_text(an) if an else a.replace("_", " ").title()
                if an.lower() not in seen:
                    seen.add(an.lower())
                    aliases.append(an)

        dlc, features = ck3.dlc_tag(path, blk)
        flag = blk.get("requires_dlc_flag")
        if isinstance(flag, str):
            features = sorted(set(features) | {flag})
            if flag in ck3.FEATURE_TO_DLC:
                dlc = ck3.FEATURE_TO_DLC[flag]
            else:
                unknown_flags.add(flag)

        out.append({
            "id": key,
            "name": name,
            "desc": desc,
            "aliases": aliases,
            "parent": blk.get("parent"),
            "dlc": dlc,
            "features": features,
        })

    # parents may name an alias rather than the canonical key — remap; a
    # parent still absent after that (hidden concept) would be a dead link
    ids = {r["id"] for r in out}
    alias_to_id = {}
    for _p, key, blk in entries:
        ab = blk.get("alias")
        if key in ids and isinstance(ab, Block):
            for a in ab.values():
                if isinstance(a, str):
                    alias_to_id.setdefault(a, key)
    dead_parents = set()
    for r in out:
        p = r["parent"]
        if p and p not in ids:
            r["parent"] = alias_to_id.get(p)
            if r["parent"] is None:
                dead_parents.add(p)

    out.sort(key=lambda r: (r["name"].lower(), r["id"]))
    ck3.write_json("concepts.json", out)

    print(f"  ({len(hidden)} concepts hidden by shown_in_encyclopedia=no, e.g. {hidden[:3]})")
    if dead_parents:
        print(f"  (parents outside the glossary, link dropped: {sorted(dead_parents)})")
    if unknown_flags:
        print(f"⚠ requires_dlc_flag not in ck3.FEATURE_TO_DLC: {sorted(unknown_flags)}")
    if unhandled:
        print("⚠ unhandled game_concepts fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    unresolved = ck3.unresolved_report()
    print(f"  (unresolved loc tokens across all descriptions: {len(unresolved)})")


if __name__ == "__main__":
    main()
