#!/usr/bin/env python3
"""Build src/data/council.json from common/council_positions/ + council_tasks/.

Positions and tasks joined by the task's `position` field. Kurultai seats
1–4 are four identical position/task copies (seat 2–4 loc just aliases seat
1); we emit seat 1 with seats=4 and consciously skip the duplicates.

Council modifiers carry a `scale` script value (liege tier, councillor
skill, monthly income…) — every line is rendered with its scale named,
never collapsed to the unscaled base number alone.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP_FIELDS = {
    "auto_fill": "auto-assignment plumbing (spouse/kurultai fill themselves)",
    "fill_from_pool": "auto-fill sourcing detail",
    "can_fire": "reassignment rules surface in the tooltip desc where relevant",
    "can_reassign": "reassignment rules surface in the tooltip desc where relevant",
    "can_change_once": "reassignment rules surface in the tooltip desc where relevant",
    "inherit": "succession plumbing (chaplain inheritance)",
    "valid_character": "candidate eligibility macros, not position facts",
    "on_get_position": "script effect",
    "on_lose_position": "script effect",
    "on_fired_from_position": "script effect",
    "use_for_scheme_phase_duration": "scheme-engine wiring flag",
    "use_for_scheme_resistance": "scheme-engine wiring flag",
    "portrait_animation": "GUI",
    "barbershop_data": "GUI",
    "pool_character_config": "auto-fill character generation detail",
}

HANDLED_FIELDS = {
    "skill", "name", "tooltip", "valid_position", "modifier",
    "council_owner_modifier", "is_clergy_position",
}

TASK_SKIP_FIELDS = {
    "default_task": "which task is pre-selected; not an effect",
    "asset": "icon consumed; other GUI art skipped",
    "ai_will_do": "AI task-picking weight",
    "ai_county_target": "AI targeting restriction",
    "ai_target_score": "AI targeting weight",
    "monthly_on_action": "event scheduling",
    "on_start_task": "script effect", "on_finish_task": "script effect",
    "on_cancel_task": "script effect", "on_monthly": "script effect",
    "on_start_task_county": "script effect", "on_finish_task_county": "script effect",
    "on_cancel_task_county": "script effect", "on_monthly_county": "script effect",
    "on_start_task_court": "script effect", "on_finish_task_court": "script effect",
    "on_cancel_task_court": "script effect", "on_monthly_court": "script effect",
    "is_shown": "visibility gates (DLC checks consumed for provenance)",
    "is_valid_showing_failures_only": "grey-out validity plumbing",
    "potential_county": "county targeting internals; county_target names the reach",
    "valid_county": "county targeting internals",
    "potential_target_court": "court targeting internals",
    "valid_target_court": "court targeting internals",
    "progress": "progress-rate formula internals (skill-driven); type noted instead",
    "full_progress": "tooltip ETA plumbing",
    "custom_other_loc": "tooltip loc override",
    "highlight_own_realm": "map GUI flag",
    "restart_on_finish": "noted via progress type; auto-repeat detail",
    "task_current_value": "progress formula internals; progress type noted",
    "task_max_value": "progress formula internals; progress type noted",
    "effect_desc": "triggered-loc tree; static <key>_effect_desc rendered instead",
}

TASK_HANDLED_FIELDS = {
    "position", "task_type", "county_target", "task_progress", "skill",
    "councillor_modifier", "council_owner_modifier", "county_modifier", "clone",
}

_DLC_TRIGGER = re.compile(r"^has_([a-z]+\d?)(?:_[a-z_]+)?_dlc_trigger$")
NEGATORS = {"NOT", "NOR", "NAND"}

_BULLET = re.compile(r"EFFECT_LIST_BULLET\s*")


def clean_text(s):
    return _BULLET.sub("", s).strip() if isinstance(s, str) else s


# --------------------------------------------------------------------------
# triggered-loc name/tooltip: string -> loc it; block -> the untriggered
# fallback desc inside first_valid

def loc_field(v, fallback_key=None):
    key = None
    if isinstance(v, str):
        key = v
    elif isinstance(v, Block):
        fv = v.get("first_valid")
        blk = fv if isinstance(fv, Block) else v
        for k, _op, val in blk:
            if k == "desc" and isinstance(val, str):
                key = val  # last plain desc wins: it's the fallback
    raw = ck3.loc(key) if key else None
    if raw is None and fallback_key:
        raw = ck3.loc(fallback_key)
    return clean_text(ck3.render_text(raw)) if raw else None


# --------------------------------------------------------------------------
# modifiers with scale

def scale_note(scale):
    if scale is None:
        return None
    divisor = None
    if isinstance(scale, Block):
        v = scale.get("value")
        d = scale.get("divide")
        divisor = d if isinstance(d, (int, float)) else None
        scale = v if isinstance(v, str) else None
        if scale is None:
            return "situational"
    if not isinstance(scale, str):
        return "situational"
    s = scale.split(".")[-1]
    s = re.sub(r"^(council_scaled_by_|council_scaled_|scaled_by_|scale_)", "", s)
    s = re.sub(r"_(scale|total|value)$", "", s)
    s = s.replace("_", " ")
    return f"{s} ÷{divisor:g}" if divisor else s


def rendered_mods(blocks):
    """List of modifier blocks -> flat rendered lines with scale notes."""
    out = []
    for blk in blocks:
        if isinstance(blk, Tagged):
            blk = blk.block
        if not isinstance(blk, Block):
            continue
        note = scale_note(blk.get("scale"))
        for k, _op, v in blk:
            if k in (None, "name", "scale") or isinstance(v, (Block, Tagged)):
                continue
            out.append({"text": ck3.render_modifier(k, v),
                        "polarity": ck3.modifier_polarity(k, v),
                        **({"scale": note} if note else {})})
    return out


# --------------------------------------------------------------------------
# gates -> requirement chips + DLC provenance (council flavor: government
# flags with NOR negation, DLC triggers)

def collect_gates(trigger, reqs, dlcs, negated=False, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 6:
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        m = _DLC_TRIGGER.match(k)
        if m:
            dlc = ck3.PREFIX_TO_DLC.get(m.group(1))
            if dlc:
                dlcs.add(dlc)
            continue
        if k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_").replace("_", " ").title()
            reqs.append({"name": f"{label} government", "negated": negated})
            continue
        if k == "has_dlc_feature":
            continue  # dlc_tag scan covers provenance
        if k == "tgp_has_access_to_ministry_trigger":
            # scripted trigger: has_title = title:h_china + celestial government
            reqs.append({"name": "Hegemon of China (Celestial government)", "negated": negated})
            dlcs.add("The Great People")
            continue
        if k == "custom_tooltip" and isinstance(v, Block):
            raw = ck3.loc(v.get("text")) if isinstance(v.get("text"), str) else None
            if raw:
                line = clean_text(ck3.render_text(raw)).split("\n")[0].rstrip(":… ")
                if line:
                    reqs.append({"name": line, "negated": negated})
            continue
        if isinstance(v, (Block, Tagged)) and k not in ("limit", "trigger_if", "trigger_else", "trigger_else_if"):
            collect_gates(v, reqs, dlcs, negated or (k in NEGATORS), depth + 1)


def dedupe(reqs):
    seen, out = set(), []
    for r in reqs:
        key = (r["name"], r["negated"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


_KURULTAI_DUP = re.compile(r"(_kurultai.*)_([234])$")


def is_duplicate_seat(key):
    return bool(_KURULTAI_DUP.search(key))


# --------------------------------------------------------------------------

def build_positions(unhandled):
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "council_positions"):
        if isinstance(blk, Tagged) or is_duplicate_seat(key):
            continue
        reqs, gate_dlcs = [], set()
        collect_gates(blk.get("valid_position"), reqs, gate_dlcs)
        dlc, features = ck3.dlc_tag(path, blk)
        if not dlc and gate_dlcs:
            dlc = sorted(gate_dlcs)[0]
        if not dlc and "kurultai" in key:
            dlc = "Khans of the Steppe"  # nomad council; gated only by government flag

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        rec = {
            "id": key,
            "name": loc_field(blk.get("name"), fallback_key=key),
            "desc": loc_field(blk.get("tooltip")),
            "skill": blk.get("skill"),
            "isClergy": bool(blk.get("is_clergy_position", False)),
            "seats": 4 if "kurultai" in key else 1,
            "modifiers": rendered_mods(blk.get_all("modifier")),
            "ownerModifiers": rendered_mods(blk.get_all("council_owner_modifier")),
            "requirements": dedupe(reqs),
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        }
        out.append(rec)
    return out


def resolve_clones(entries):
    """clone = other_task shares everything but `position`."""
    by_key = {k: blk for _p, k, blk in entries}
    resolved = []
    for path, key, blk in entries:
        src = blk.get("clone")
        if isinstance(src, str) and src in by_key:
            base = by_key[src]
            merged = Block(list(base.triples))
            for k, op, v in blk:
                if k != "clone":
                    merged.triples = [(kk, oo, vv) for kk, oo, vv in merged.triples if kk != k]
                    merged.triples.append((k, op, v))
            resolved.append((path, key, merged, src))
        else:
            resolved.append((path, key, blk, None))
    return resolved


def build_tasks(unhandled):
    entries = ck3.parse_dir(ck3.COMMON / "council_tasks")
    out = []
    for path, key, blk, clone_of in resolve_clones(entries):
        if isinstance(blk, Tagged) or is_duplicate_seat(key):
            continue
        name_key = clone_of or key
        name = ck3.loc(key) or ck3.loc(name_key)
        effect_desc = ck3.loc(f"{name_key}_effect_desc")
        if effect_desc:
            effect_desc = clean_text(ck3.render_text(effect_desc))
            if not re.search(r"[A-Za-z]", effect_desc.replace("At", "").replace("TAB", "")):
                effect_desc = None  # rendered to pure placeholders

        reqs, gate_dlcs = [], set()
        collect_gates(blk.get("is_shown"), reqs, gate_dlcs)
        dlc, _features = ck3.dlc_tag(path, blk)
        if not dlc and gate_dlcs:
            dlc = sorted(gate_dlcs)[0]
        if not dlc and "kurultai" in key:
            dlc = "Khans of the Steppe"

        icon = key
        asset = blk.get("asset")
        if isinstance(asset, Block) and isinstance(asset.get("icon"), str):
            icon = Path(asset.get("icon")).stem

        for k in blk.keys():
            if k not in TASK_HANDLED_FIELDS and k not in TASK_SKIP_FIELDS:
                unhandled[k] += 1

        rec = {
            "id": key,
            "name": clean_text(ck3.render_text(name)) if name else None,
            "effectDesc": effect_desc or None,
            "position": re.sub(r"_[234]$", "_1", str(blk.get("position") or "")),
            "taskType": (blk.get("task_type") or "task_type_general").removeprefix("task_type_"),
            "countyTarget": blk.get("county_target"),
            "progress": (blk.get("task_progress") or "task_progress_infinite").removeprefix("task_progress_"),
            "skill": blk.get("skill"),
            "councillorMods": rendered_mods(blk.get_all("councillor_modifier")),
            "ownerMods": rendered_mods(blk.get_all("council_owner_modifier")),
            "countyMods": rendered_mods(blk.get_all("county_modifier")),
            "cloneOf": clone_of,
            "icon": icon,
            "dlc": dlc,
            "sourceFile": path.name,
        }
        out.append(rec)
    return out


def main():
    unhandled_p, unhandled_t = Counter(), Counter()
    positions = build_positions(unhandled_p)
    tasks = build_tasks(unhandled_t)
    order = {p["id"]: i for i, p in enumerate(positions)}
    tasks.sort(key=lambda t: (order.get(t["position"], 99), t["id"]))
    ck3.write_json("council.json", {"positions": positions, "tasks": tasks})

    for label, c in (("position", unhandled_p), ("task", unhandled_t)):
        if c:
            print(f"⚠ unhandled council {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    missing = [r["id"] for r in positions + tasks if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} entries without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
