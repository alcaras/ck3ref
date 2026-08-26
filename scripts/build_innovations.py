#!/usr/bin/env python3
"""Build src/data/innovations.json from common/culture/innovations/.

Schema documented by the game in _culture_innovations.info. Name loc is the
bare key; description is <key>_desc. Unlock fields are tooltip-only pointers
(except unlock_maa, which actually unlocks), rendered as chips; `custom` lines
are the game's own effect strings.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import culture_text
from ck3 import Block, Tagged


def _render(s):
    """render_text with culture-file data functions statically pre-resolved."""
    return ck3.render_text(culture_text.expand(s)) if isinstance(s, str) else s


SKIP_FIELDS = {
    "ai_weight_for_fascination": "AI fascination pick weighting, not player-facing",
    "ai_weight_for_spread": "AI spread pick weighting, not player-facing",
    "asset": "per-culture name/icon restyling (e.g. Chinese mangonel art); site shows the generic form",
    "flag": "innovation-set bookkeeping for has_all_innovations triggers, not player-facing",
    "can_progress": "runtime progress gating (decision/situation state); the potential/region gates cover static visibility",
}

HANDLED_FIELDS = {
    "group", "culture_era", "region", "icon", "skill", "potential",
    "unlock_building", "unlock_decision", "unlock_casus_belli", "unlock_maa",
    "unlock_law", "custom", "maa_upgrade", "parameters",
    "character_modifier", "culture_modifier", "county_modifier", "province_modifier",
    "name", "desc",
}

ERA_ORDER = ["culture_era_tribal", "culture_era_early_medieval",
             "culture_era_high_medieval", "culture_era_late_medieval"]
GROUP_ORDER = ["culture_group_military", "culture_group_civic", "culture_group_regional"]

NEGATORS = {"NOT", "NOR", "NAND"}
_DLC_TRIGGER = re.compile(r"^has_([a-z0-9]+)_dlc_trigger$")

TRIGGER_LABELS = {
    "silk_road_innovation_trigger": "Spreads along the Silk Road",
    "is_roman_emperor_primary_title_excluding_byzantium_trigger":
        "Rules a restored Roman Empire (not Byzantium)",
}

MAA_UPGRADE_STATS = {"damage": "damage", "toughness": "toughness", "pursue": "pursuit",
                     "screen": "screen", "siege_value": "siege value", "max_size": "max size"}

def render_custom(key):
    """A `custom` effect loc line, with data functions statically resolved."""
    raw = ck3.loc(key)
    if raw is None:
        return key.replace("_", " ").capitalize()
    return _render(raw)


def unlock_name(kind, key):
    """Localized display name for an unlock reference."""
    if kind == "building":
        raw = ck3.loc(f"building_{key}") or ck3.loc(key) or ck3.loc(f"{key}_name")
    else:
        raw = ck3.loc(key) or ck3.loc(f"{key}_name")
    return _render(raw) if raw else key.replace("_", " ").title()


def collect_reqs(trigger, reqs, negated=False, depth=0):
    """Shallow potential-gate extraction (the build_maa pattern)."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 6:
        return
    for k, _op, v in trigger:
        if k in ("custom_tooltip", "custom_description"):
            text_key = v if isinstance(v, str) else v.get("text") if isinstance(v, Block) else None
            if text_key:
                txt = _render(ck3.loc(text_key) or text_key)
                reqs.append({"kind": "text", "text": txt, "negated": negated})
            continue
        if k == "has_cultural_pillar" and isinstance(v, str):
            name = _render(ck3.loc(f"{v}_name") or ck3.loc(v) or v)
            reqs.append({"kind": "pillar", "key": v, "text": name, "negated": negated})
        elif k == "has_innovation" and isinstance(v, str):
            name = _render(ck3.loc(v) or v)
            reqs.append({"kind": "innovation", "key": v, "text": name, "negated": negated})
        elif k == "has_cultural_parameter" and isinstance(v, str):
            name = _render(ck3.loc(f"culture_parameter_{v}") or v)
            reqs.append({"kind": "parameter", "key": v, "text": name, "negated": negated})
        elif k == "has_dlc_feature" and isinstance(v, str):
            reqs.append({"kind": "dlc", "key": v, "text": ck3.FEATURE_TO_DLC.get(v, v),
                         "negated": negated})
        elif isinstance(k, str) and _DLC_TRIGGER.match(k):
            prefix = _DLC_TRIGGER.match(k).group(1)
            reqs.append({"kind": "dlc", "key": k,
                         "text": ck3.PREFIX_TO_DLC.get(prefix, prefix), "negated": negated})
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            label = TRIGGER_LABELS.get(k, k.removesuffix("_trigger").replace("_", " ").capitalize())
            reqs.append({"kind": "trigger", "key": k, "text": label, "negated": negated})
        elif isinstance(k, str) and k.endswith("_trigger") and isinstance(v, (Block, Tagged)):
            # scripted-trigger macro invoked with arguments; the args are macro
            # plumbing, the trigger name is the requirement
            reqs.append({"kind": "trigger", "key": k, "text": TRIGGER_LABELS.get(k, k.removesuffix("_trigger").replace("_", " ").capitalize()),
                         "negated": negated})
        elif isinstance(v, (Block, Tagged)):
            collect_reqs(v, reqs, negated or (k in NEGATORS), depth + 1)


def dedupe(reqs):
    seen = set()
    out = []
    for r in reqs:
        sig = (r.get("kind"), r.get("key"), r.get("text"), r.get("negated"))
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


def modifier_lines(blk):
    if not isinstance(blk, Block):
        return []
    lines = []
    for k, _op, v in blk:
        if k is None or k.startswith("ai_"):
            continue  # ai_* modifier keys steer AI behavior; hidden in game tooltips
        if isinstance(v, str):
            n, _rules = ck3.resolve_value(v)
            if n is not None:
                v = n
        lines.append(culture_text.render_modifier(k, v))
    return lines


def maa_upgrade_text(up):
    t = up.get("type")
    tname = _render(ck3.loc(t) or str(t).replace("_", " ").title())
    parts = []
    for k, _o, v in up:
        if k in (None, "type"):
            continue
        label = MAA_UPGRADE_STATS.get(k, k.replace("_", " "))
        parts.append(f"+{v} {label}" if isinstance(v, (int, float)) and v >= 0 else f"{v} {label}")
    return f"{tname}: {', '.join(parts)}"


def main():
    entries = ck3.parse_dir(ck3.COMMON / "culture" / "innovations")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        name = ck3.loc(key)
        desc = ck3.loc(f"{key}_desc")

        unlocks = []
        for field, kind in (("unlock_maa", "maa"), ("unlock_building", "building"),
                            ("unlock_law", "law"), ("unlock_casus_belli", "casus_belli"),
                            ("unlock_decision", "decision")):
            for v in blk.get_all(field):
                unlocks.append({"kind": kind, "key": v, "text": unlock_name(kind, v)})
        for up in blk.get_all("maa_upgrade"):
            if isinstance(up, Block):
                unlocks.append({"kind": "maa_upgrade", "key": up.get("type"),
                                "text": maa_upgrade_text(up)})

        effects = [render_custom(c) for c in blk.get_all("custom")]

        params = []
        pb = blk.get("parameters")
        if isinstance(pb, Block):
            for pk, _o, pv in pb:
                if pk is None:
                    continue
                lk = pk if ck3.loc(f"culture_parameter_{pk}") is None else f"culture_parameter_{pk}"
                txt = culture_text.render(lk, pv)
                params.append({"key": pk, "value": pv,
                               "text": txt if txt else pk.replace("_", " ").capitalize(),
                               "hasLoc": bool(txt)})

        mods = {}
        for field, label in (("character_modifier", "Characters"),
                             ("province_modifier", "Provinces"),
                             ("county_modifier", "Counties"),
                             ("culture_modifier", "Culture")):
            lines = modifier_lines(blk.get(field))
            if lines:
                mods[label] = lines

        reqs = []
        collect_reqs(blk.get("potential"), reqs)
        # a potential often ORs `has_innovation = <itself>` so hybrids keep it;
        # as a chip that self-reference reads as circular — drop it
        reqs = [r for r in reqs if not (r.get("kind") == "innovation" and r.get("key") == key)]

        region = blk.get("region")
        region_name = None
        if region:
            raw = ck3.loc(region) or ck3.loc(f"{region}_name")
            region_name = _render(raw) if raw else \
                region.removeprefix("world_innovation_").removeprefix("world_") \
                      .removeprefix("custom_").removeprefix("ghw_region_").replace("_", " ").title()

        icon = blk.get("icon") or key
        icon = Path(str(icon)).name.removesuffix(".dds")

        era = blk.get("culture_era")
        group = blk.get("group")

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        out.append({
            "id": key,
            "name": _render(name) if name else None,
            "desc": _render(desc) if desc else None,
            "era": era,
            "eraName": _render(ck3.loc(era) or str(era)),
            "group": group,
            "groupName": _render(ck3.loc(group) or str(group)),
            "skill": blk.get("skill", "learning"),
            "region": region,
            "regionName": region_name,
            "unlocks": unlocks,
            "effects": effects,
            "parameters": params,
            "modifiers": mods,
            "requirements": dedupe(reqs),
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (ERA_ORDER.index(r["era"]) if r["era"] in ERA_ORDER else 99,
                            GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else 99,
                            r["id"]))
    ck3.write_json("innovations.json", out)

    if unhandled:
        print("⚠ unhandled innovation fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")
    noloc_params = sorted({p["key"] for r in out for p in r["parameters"] if not p["hasLoc"]})
    if noloc_params:
        print(f"⚠ {len(noloc_params)} parameters without loc (prettified): {noloc_params}")


if __name__ == "__main__":
    main()
