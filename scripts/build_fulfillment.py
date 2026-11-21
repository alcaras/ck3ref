#!/usr/bin/env python3
"""Build src/data/fulfillment.json from common/spiritual_fulfillment/.

1.20 (By God Alone). Each fulfillment type maps characters of its `religions`
to a ladder of levels; the type with no religions is the fallback. A level is
active when fulfillment is >= its (positive) threshold or <= its (negative)
threshold; threshold 0 is the neutral level. Per _spiritual_fulfillment_type.info:

  level name   <type>_level_<index>, falling back to
               default_fulfillment_level_<index> (index after sorting by
               threshold, from 0)
  flags        checked by has_fulfillment_parameter; described by
               fulfillment_level_parameter_<flag>

The range and the tenet weightings come from NReligion defines, read at
build time.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

HANDLED_TYPE = {"religions", "level"}
HANDLED_LEVEL = {"threshold", "modifier", "flags", "icon"}
SKIP_FIELDS: dict = {}

# NReligion defines shown on the page (all read from defines, never typed in)
DEFINES = [
    "MIN_SPIRITUAL_FULFILLMENT", "MAX_SPIRITUAL_FULFILLMENT",
    "SPIRITUAL_FULFILLMENT_MULT_PERSONAL_TENET", "SPIRITUAL_FULFILLMENT_MULT_CORE_TENET",
    "SPIRITUAL_FULFILLMENT_MULT_PERMITTED_TENET", "SPIRITUAL_FULFILLMENT_MULT_RELIGION_TRAIT",
    "SPIRITUAL_FULFILLMENT_FOR_STRESS_DIVIDE_FACTOR", "MIN_FULFILLMENT_CHANGE_FOR_EFFECT",
    "BASE_PERSONAL_TENETS_CAP", "PERSONAL_TENET_CHANGE_COOLDOWN_DAYS",
]

_DECISION = re.compile(r"\[GetDecisionWithKey\('(\w+)'\)\.GetName\]")
_INTERACTION = re.compile(r"\[GetPlayer\.GetPlayerInteractionName\('(\w+)'\)\]")
_SVALUE = re.compile(r"\[EmptyScope\.ScriptValue\('(\w+)'\)(?:\|(\w*%?))?\]")


def _svalue(m):
    n, _r = ck3.resolve_value(m.group(1))
    if not isinstance(n, (int, float)):
        return m.group(0)
    fmt = m.group(2) or ""
    if fmt.endswith("%"):
        return f"{n * 100:g}%"
    return f"{n:g}"


def defines():
    out = {}
    for ns, _op, blk in ck3.parse_file(ck3.COMMON / "defines" / "00_defines.txt"):
        if ns == "NReligion" and isinstance(blk, Block):
            for k in DEFINES:
                if blk.get(k) is not None:
                    out[k] = blk.get(k)
    return out


def text(raw):
    """render_text, after resolving the decision/interaction name lookups the
    generic renderer leaves as an ellipsis."""
    if not raw:
        return None
    raw = _DECISION.sub(lambda m: ck3.loc(m.group(1)) or m.group(1), raw)
    raw = _INTERACTION.sub(lambda m: ck3.loc(m.group(1)) or m.group(1), raw)
    raw = _SVALUE.sub(_svalue, raw)
    return ck3.render_text(raw)


def level_name(type_key, idx):
    for k in (f"{type_key}_level_{idx}", f"default_fulfillment_level_{idx}"):
        raw = ck3.loc(k)
        if raw:
            return ck3.render_text(raw)
    return None


def main():
    unhandled = Counter()
    religions = {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "religion" / "religion_types"):
        if isinstance(blk, Block):
            religions[key] = ck3.render_text(ck3.loc(key) or key)

    types, levels_flat = [], []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "spiritual_fulfillment"):
        if not isinstance(blk, Block):
            continue
        for k, _op, _v in blk:
            if k not in HANDLED_TYPE and k not in SKIP_FIELDS:
                unhandled[f"type.{k}"] += 1
        rel = blk.get("religions")
        rel_keys = [v for k, _o, v in rel if k is None] if isinstance(rel, Block) else []
        raw_levels = []
        for lv in blk.get_all("level"):
            if not isinstance(lv, Block):
                continue
            for k, _op, _v in lv:
                if k not in HANDLED_LEVEL and k not in SKIP_FIELDS:
                    unhandled[f"level.{k}"] += 1
            thr = lv.get("threshold")
            mods = []
            mb = lv.get("modifier")
            if isinstance(mb, Block):
                for mk, _o, mv in mb:
                    if mk is None:
                        continue
                    if isinstance(mv, (Block, Tagged)):
                        mods.append(f"{ck3.modifier_name(mk)}: (conditional)")
                    else:
                        mods.append(ck3.render_modifier(mk, mv))
            fb = lv.get("flags")
            flags = []
            if isinstance(fb, Block):
                for fk, _o, fv in fb:
                    f = fv if fk is None else fk
                    flags.append({"key": f, "text": text(ck3.loc(f"fulfillment_level_parameter_{f}"))})
            icon = lv.get("icon")
            raw_levels.append({
                "threshold": thr, "modifiers": mods, "flags": flags,
                "icon": Path(icon).stem if isinstance(icon, str) else None,
            })
        raw_levels.sort(key=lambda l: l["threshold"] if isinstance(l["threshold"], (int, float)) else -999)
        for i, l in enumerate(raw_levels):
            l["index"] = i
            l["name"] = level_name(key, i)
            l["id"] = f"{key}_level_{i}"
            levels_flat.append({"id": l["id"], "icon": l["icon"]})
        types.append({
            "id": key,
            "religions": [{"id": r, "name": religions.get(r, r)} for r in rel_keys],
            "fallback": not rel_keys,
            "levels": raw_levels,
            "dlc": ck3.dlc_tag(path, blk)[0],
        })

    concept = ck3.loc("game_concept_spiritual_fulfillment_desc")
    out = {
        "types": types,
        "levels": levels_flat,  # flat list for build_art.py
        "defines": defines(),
        "about": ck3.render_text(concept) if concept else None,
    }
    ck3.write_json("fulfillment.json", out)
    print(f"  {len(types)} fulfillment types, {len(levels_flat)} levels")
    if unhandled:
        print("⚠ unhandled fulfillment fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k}: {n}")


if __name__ == "__main__":
    main()
