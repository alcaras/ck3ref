#!/usr/bin/env python3
"""Build src/data/accolades.json from common/accolade_types/.

Schema documented in _accolade_type.info. Each entry is an accolade
*attribute* — an acclaimed knight's accolade combines up to
ACCOLADE_MAX_TYPES (3) of them, and each attribute contributes its rank
1–3 effects as the accolade gains glory. Glory rank thresholds live in
defines (NAccolade.ACCOLADE_GLORY_LEVELS) and are emitted as meta.

Attribute requirements are the game's own `<key>.unlock_tt` tooltip (the
squire_perfect_fit trigger's custom_tooltip), rendered to text.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

# Fields we deliberately do not render, with reasons.
SKIP_FIELDS = {
    "portrait_pose": "accolade-window animation selection, not gameplay",
    "weight": "AI/generation scoring for which attribute gets picked",
    "squire_acceptable_fit": "AI-personality approximation of the perfect-fit "
                             "requirement; unlock_tt covers the player-facing rule",
}

HANDLED_FIELDS = {
    "adjective", "noun", "icon", "accolade_categories", "squire_perfect_fit",
    "ranks",
}

RANK_HANDLED = {"liege_modifier", "knight_modifier", "knight_army_modifier",
                "men_at_arms", "accolade_parameters"}

SKILLS = ("diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess")

GROUP_BY_FILE = {
    "04_ep2_common_attributes.txt": "common",
    "04_ep2_skilled_attributes.txt": "skilled",
    "04_ep2_eminent_attributes.txt": "eminent",
    "04_ep2_maa_attributes.txt": "men_at_arms",
}

# [EmptyScope.ScriptValue('x')|fmt] has a static answer when the script value
# does — resolve before render_text turns it into "…".
_SCRIPT_VALUE = re.compile(r"\[EmptyScope\.ScriptValue\(\s*'(\w+)'\s*\)(\|[\w+=\-]+)?\]")


def resolve_scriptvalue_calls(s):
    def sub(m):
        n, _rules = ck3.resolve_value(m.group(1))
        if n is None:
            return m.group(0)
        fmt = m.group(2) or ""
        num = f"{n:g}"
        if "+" in fmt and n > 0:
            num = "+" + num
        return num
    return _SCRIPT_VALUE.sub(sub, s)


def render_loc_lines(raw):
    """Loc string -> list of plain-text lines (bullet markers stripped)."""
    # $EFFECT_LIST_BULLET$ is an engine loc (bullet glyph) absent from the
    # yml files — treat it as a line break so each bullet becomes a line.
    raw = raw.replace("$EFFECT_LIST_BULLET$", "\\n")
    raw = re.sub(r"\[\w+_i\]", "", raw)  # [prestige_i]-style inline icons
    text = ck3.render_text(resolve_scriptvalue_calls(raw))
    lines = []
    for line in text.split("\n"):
        line = line.strip().lstrip("•").strip()
        if line:
            lines.append(line)
    return lines


_fit_triggers: dict | None = None


def fit_triggers():
    global _fit_triggers
    if _fit_triggers is None:
        _fit_triggers = {}
        p = ck3.COMMON / "scripted_triggers" / "04_ep2_accolade_triggers.txt"
        for k, _op, v in ck3.parse_file(p):
            if k is not None and isinstance(v, Block):
                _fit_triggers[k] = v
    return _fit_triggers


def fallback_unlock(key):
    """No unlock_tt loc (blademaster): read the shallow trigger directly."""
    trig = fit_triggers().get(f"{key}_trigger")
    if not isinstance(trig, Block):
        return []
    lines = []
    for k, _op, v in trig:
        if k == "has_trait" and isinstance(v, str):
            t = ck3.loc(f"trait_{v}")
            if t:
                lines.append(f"The Acclaimed Knight is a {ck3.render_text(t)}")
        elif k == "has_trait_xp" and isinstance(v, Block):
            t = ck3.loc(f"trait_{v.get('trait', '')}")
            # value comes through as a loose ">= N" comparison triple
            n = next((vv for kk, op, vv in v if kk == "value"), None)
            if t and n is not None:
                lines.append(f"{ck3.render_text(t)} experience is {n} or higher")
    return lines


def render_mod_block(blk):
    if not isinstance(blk, Block):
        return []
    return [ck3.render_modifier(k, v) for k, v in blk.items()]


def main():
    entries = ck3.parse_dir(ck3.COMMON / "accolade_types")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        group = GROUP_BY_FILE.get(path.name)
        if group is None:
            continue  # 00_accolade_categories.txt is comment-only documentation
        dlc, features = ck3.dlc_tag(path, blk)

        cats = [c for c in (blk.get("accolade_categories") or Block()).values()
                if isinstance(c, str)]
        icon = str(blk.get("icon") or "").rsplit("/", 1)[-1].removesuffix(".dds")

        unlock_raw = ck3.loc(f"{key}.unlock_tt")
        unlock = render_loc_lines(unlock_raw) if unlock_raw else fallback_unlock(key)
        if unlock and unlock[0].rstrip(":").lower() == "any of these":
            unlock = unlock[1:]

        ranks = []
        rb = blk.get("ranks")
        if isinstance(rb, Block):
            for rk, _op, rv in rb:
                if rk is None or not isinstance(rv, Block):
                    continue
                for k in rv.keys():
                    if k not in RANK_HANDLED:
                        unhandled[f"ranks.{k}"] += 1
                maa = []
                mb = rv.get("men_at_arms")
                if isinstance(mb, Block):
                    for m in mb.values():
                        if isinstance(m, str):
                            maa.append({"id": m,
                                        "name": ck3.render_text(ck3.loc(m) or m.replace("_", " ").title())})
                params = []
                pb = rv.get("accolade_parameters")
                if isinstance(pb, Block):
                    for p in pb.keys() + [v for v in pb.values() if isinstance(v, str)]:
                        raw = ck3.loc(p)
                        if raw:
                            params.extend(render_loc_lines(raw))
                        else:
                            params.append(p.removeprefix("accolade_").replace("_", " ").capitalize())
                ranks.append({
                    "rank": int(rk),
                    "liege": render_mod_block(rv.get("liege_modifier")),
                    "knight": render_mod_block(rv.get("knight_modifier")),
                    "knightArmy": render_mod_block(rv.get("knight_army_modifier")),
                    "maa": maa,
                    "params": params,
                })

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name = ck3.loc(key)
        adjective = ck3.loc(blk.get("adjective", ""))
        noun = ck3.loc(blk.get("noun", ""))
        out.append({
            "id": key,
            "name": ck3.render_text(name) if name else None,
            "adjective": ck3.render_text(adjective) if adjective else None,
            "noun": ck3.render_text(noun) if noun else None,
            "group": group,
            "skills": [s for s in SKILLS if s in cats],
            "categories": cats,
            "icon": icon,
            "unlock": unlock,
            "ranks": ranks,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    # Glory thresholds & max attributes from defines — accolade-wide meta.
    defines = ck3.parse_file(ck3.REF / "game" / "common" / "defines" / "00_defines.txt")
    nacc = defines.get("NAccolade") or Block()
    glory = [v for v in (nacc.get("ACCOLADE_GLORY_LEVELS") or Block()).values()
             if isinstance(v, (int, float))]
    rank_flavors = []
    for i in range(len(glory) + 1):
        f = ck3.loc(f"accolade_rank_flavor_{['unsung','established','recognized','feted','lionized','august','glorious'][i]}" if i < 7 else "")
        rank_flavors.append(ck3.render_text(f) if f else None)

    group_order = {"common": 0, "skilled": 1, "eminent": 2, "men_at_arms": 3}
    out.sort(key=lambda r: (group_order.get(r["group"], 9), r["id"]))
    ck3.write_json("accolades.json", {
        "attributes": out,
        "gloryLevels": glory,
        "rankFlavors": rank_flavors,
        "maxAttributes": nacc.get("ACCOLADE_MAX_TYPES"),
    })

    if unhandled:
        print("⚠ unhandled accolade fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")
    no_unlock = [r["id"] for r in out if not r["unlock"]]
    if no_unlock:
        print(f"⚠ {len(no_unlock)} entries without unlock_tt loc: {no_unlock[:10]}")


if __name__ == "__main__":
    main()
