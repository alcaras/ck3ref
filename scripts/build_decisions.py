#!/usr/bin/env python3
"""Build src/data/decisions.json from common/decisions/ (recursive — the DLC
sets live in dlc_decisions/<pack>/) + common/decision_group_types/.

Loc pattern (verified): title "<key>" (or `title` override), desc "<key>_desc",
confirm "<key>_confirm", selection tooltip "<key>_tooltip" — each overridable
by a field that is either a loc key or a first_valid/triggered_desc block, in
which case we take the LAST desc entry (the untriggered fallback, per the
dynamic-desc quirk in CLAUDE.md).

Effects are never rendered as script — we extract the effect block's
custom_tooltip lines (the game's own player-facing phrasing) and omit the
rest. The debug group (debug_only decisions) and the tutorial_objectives
group (tutorial-session-only) are excluded, as the game excludes them from
a normal campaign.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

EXCLUDED_GROUPS = {"debug", "tutorial_objectives"}

SKIP_FIELDS = {
    "extra_picture": "struggle-button illustration",
    "soundeffect": "audio",
    "confirm_click_sound": "audio",
    "progress": "ruler-objective progress bar script",
    "advice": "ruler-objective advice scripts",
    "ai_goal": "AI budgeting flag", "ai_check_interval": "AI plumbing",
    "ai_check_interval_by_tier": "AI plumbing", "ai_potential": "AI plumbing",
    "ai_will_do": "AI plumbing",
    "should_create_alert": "alert plumbing on top of the base requirements",
    "widget": "embedded GUI widget (option lists render their own tooltips)",
    "effect": "effect script; its custom_tooltip lines are extracted as effectText",
    "confirm_text": "confirm-button label override; confirm loc covered by <key>_confirm",
    "selection_tooltip": "list-hover override; the desc column covers the summary",
    "cooldown_against_recipient": "interaction-style per-target cooldown plumbing",
}

HANDLED_FIELDS = {
    "picture",
    "title", "desc", "decision_group_type", "sort_order", "is_shown",
    "is_valid", "is_valid_showing_failures_only", "cost", "minimum_cost",
    "cooldown", "major", "is_invisible",
}

NEGATORS = {"NOT", "NOR", "NAND"}

# --------------------------------------------------------------------------
# DLC provenance (shared approach with build_activities.py)

_dlc_triggers: dict | None = None


def dlc_trigger_map():
    global _dlc_triggers
    if _dlc_triggers is None:
        _dlc_triggers = {}
        p = ck3.COMMON / "scripted_triggers" / "00_has_dlc_scripted_triggers.txt"
        for key, _op, blk in ck3.parse_file(p):
            if not isinstance(blk, Block):
                continue
            feats = set()
            ck3._scan_features(blk, feats)
            dlcs = sorted({ck3.FEATURE_TO_DLC[f] for f in feats if f in ck3.FEATURE_TO_DLC})
            if dlcs:
                _dlc_triggers[key] = dlcs[0]
    return _dlc_triggers


# dlc_decisions/<folder>/ names -> ck3.PREFIX_TO_DLC keys
FOLDER_PREFIX = {"bp_2": "bp2", "bp3": "bp3", "ce_1": "ce1", "ep_1": "ep1",
                 "ep_2": "ep2", "ep_3": "ep3", "fp_1": "fp1", "fp_3": "fp3",
                 "mpo": "mpo", "tgp": "tgp"}


def path_dlc(path):
    if path.parent.name in FOLDER_PREFIX:
        return ck3.PREFIX_TO_DLC.get(FOLDER_PREFIX[path.parent.name])
    m = re.match(r"^\d*_?([a-z]+\d?)_", path.name)
    return ck3.PREFIX_TO_DLC.get(m.group(1)) if m else None


def scan_dlc(blk, dlcs, depth=0):
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block) or depth > 8:
        return
    for k, _op, v in blk:
        if k == "has_dlc_feature" and isinstance(v, str) and v in ck3.FEATURE_TO_DLC:
            dlcs.add(ck3.FEATURE_TO_DLC[v])
        elif isinstance(k, str) and k in dlc_trigger_map():
            dlcs.add(dlc_trigger_map()[k])
        elif isinstance(v, (Block, Tagged)):
            scan_dlc(v, dlcs, depth + 1)


# --------------------------------------------------------------------------
# money / durations (decision costs are mostly static; script-value costs get
# the base-line treatment from build_activities.py)

MIN_BASE = 5


def _find_base(v, depth=0, desc_only=True):
    if depth > 8:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if not desc_only and v >= MIN_BASE:
            return v
        return None
    if isinstance(v, str):
        v = ck3.script_values().get(re.sub(r"^(root|scope:\w+|this)\.", "", v))
    if not isinstance(v, Block):
        return None
    for k, _op, val in v:
        if k in ("value", "add"):
            if isinstance(val, Block):
                if desc_only and not val.has("desc"):
                    n = _find_base(val, depth + 1, desc_only)
                else:
                    n = _find_base(val.get("value"), depth + 1, desc_only=False) \
                        if val.has("desc") else _find_base(val, depth + 1, desc_only)
            else:
                n = _find_base(val, depth + 1, desc_only)
            if n is not None:
                return n
        elif k in ("if", "else_if", "else") and isinstance(val, Block):
            body = Block([t for t in val if t[0] != "limit"])
            n = _find_base(body, depth + 1, desc_only)
            if n is not None:
                return n
    return None


def money(v):
    n, _rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": round(n, 2)} if n else None
    base = _find_base(v, desc_only=True)
    if base is None:
        base = _find_base(v, desc_only=False)
    if base is not None:
        return {"base": round(base, 2), "scales": True}
    return {"scales": True}


def money_block(blk):
    if not isinstance(blk, Block):
        return {}
    out = {}
    for k, _op, v in blk:
        if k is None or k == "round":
            continue
        m = money(v)
        if m:
            out[k] = m
    if "treasury" in out:
        out.setdefault("gold", out["treasury"])
        del out["treasury"]
    return out


def duration(blk):
    if not isinstance(blk, Block):
        return None
    for unit in ("years", "months", "weeks", "days"):
        v = blk.get(unit)
        if v is not None:
            m = money(v) or {"value": 0}
            return {"unit": unit, **m}
    return None


# --------------------------------------------------------------------------
# gates -> requirement chips (court-positions pattern, decision trigger set)

TIER_NAMES = {"tier_barony": "Barony", "tier_county": "County", "tier_duchy": "Duchy",
              "tier_kingdom": "Kingdom", "tier_empire": "Empire", "tier_hegemony": "Hegemony"}

GATE_IGNORE = {
    "is_ai", "always", "exists", "is_adult", "is_available_adult",
    "is_available", "is_available_healthy", "is_capable_adult", "is_alive",
    "is_imprisoned", "is_landed", "is_landed_or_landless_administrative",
    "is_playable_character", "is_at_war", "is_ruler", "is_independent_ruler",
    "save_temporary_scope_as", "save_scope_as", "save_temporary_scope_value_as",
    "years_from_game_start", "has_character_flag", "has_variable",
    "has_global_variable", "has_game_rule", "is_adult_or_is_commanding",
    "is_available_adult_or_is_commanding", "trigger_if", "trigger_else_if",
    "trigger_else", "limit", "debug_only", "count", "age", "gold",
    "short_term_gold", "current_date", "exists_pretrigger", "is_alive_pretrigger",
}

TRAIT_SKILLS = {"diplomacy", "martial", "stewardship", "intrigue", "learning", "prowess"}


def _loc_name(key, *patterns):
    for pat in patterns:
        raw = ck3.loc(pat.format(k=key))
        if raw:
            return ck3.render_text(raw)
    return None


def collect_gates(trigger, reqs, dlcs, negated=False, depth=0):
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 6:
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        if k == "has_dlc_feature" or (isinstance(k, str) and k in dlc_trigger_map()):
            scan_dlc(Block([(k, _op, v)]), dlcs)
            continue
        if k in ("custom_tooltip", "custom_description") and isinstance(v, (Block, str)):
            text = v.get("text") if isinstance(v, Block) else v
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                line = ck3.render_text(raw).split("\n")[0].rstrip(":… ")
                if line:
                    reqs.append({"name": line, "negated": negated})
            continue
        if k == "highest_held_title_tier" and isinstance(v, str):
            tier = TIER_NAMES.get(v, v)
            reqs.append({"name": f"{tier} tier{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k == "government_has_flag" and isinstance(v, str):
            label = v.removeprefix("government_is_").removeprefix("government_")
            reqs.append({"name": f"{label.replace('_', ' ').title()} government",
                         "negated": negated})
            continue
        if k == "government_allows" and isinstance(v, str):
            reqs.append({"name": f"Government allows {v.replace('_', ' ')}",
                         "negated": negated})
            continue
        if k == "has_government" and isinstance(v, str):
            name = _loc_name(v, "{k}", "{k}_name")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k == "has_realm_law" and isinstance(v, str):
            name = _loc_name(v, "{k}", "{k}_name")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k == "has_trait" and isinstance(v, str):
            name = _loc_name(v, "trait_{k}")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("has_perk", "has_focus", "has_dynasty_perk") and isinstance(v, str):
            name = _loc_name(v, "{k}_name", "{k}")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("has_innovation", "has_doctrine") and isinstance(v, str):
            name = _loc_name(v, "{k}", "{k}_name")
            if name:
                reqs.append({"name": name, "negated": negated})
            continue
        if k in ("religion", "has_religion", "religion_tag") and isinstance(v, str):
            name = _loc_name(v.split(":")[-1].removesuffix("_religion"), "{k}", "{k}_religion")
            if name:
                reqs.append({"name": f"{name} religion", "negated": negated})
            continue
        if k in ("faith", "has_faith") and isinstance(v, str):
            name = _loc_name(v.split(":")[-1], "{k}")
            if name:
                reqs.append({"name": f"{name} faith", "negated": negated})
            continue
        if k in ("culture", "has_culture") and isinstance(v, str):
            name = _loc_name(v.split(":")[-1], "{k}", "{k}_name")
            if name:
                reqs.append({"name": f"{name} culture", "negated": negated})
            continue
        if k == "culture_group" and isinstance(v, str):
            name = _loc_name(v.split(":")[-1], "{k}", "{k}_name")
            if name:
                reqs.append({"name": f"{name} culture group", "negated": negated})
            continue
        if k == "has_cultural_parameter" and isinstance(v, str):
            name = _loc_name(v, "culture_parameter_{k}")
            reqs.append({"name": name or "Cultural tradition", "negated": negated})
            continue
        if k in ("has_cultural_tradition", "has_cultural_pillar", "has_heritage") and isinstance(v, str):
            name = _loc_name(v, "{k}_name", "{k}")
            reqs.append({"name": name or v.replace("_", " ").title(), "negated": negated})
            continue
        if k in ("has_title", "completely_controls", "has_primary_title",
                 "completely_controls_region") and isinstance(v, str):
            ref = v.split(":")[-1]
            name = _loc_name(ref, "{k}") or ref.replace("_", " ").title()
            verb = "Controls " if k.startswith("completely_controls") else ""
            reqs.append({"name": f"{verb}{name}", "negated": negated})
            continue
        if k in ("prestige_level", "piety_level") and isinstance(v, (int, float)):
            what = "Prestige" if k == "prestige_level" else "Devotion"
            reqs.append({"name": f"{what} level {v:g}{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k in TRAIT_SKILLS and isinstance(v, (int, float)):
            reqs.append({"name": f"{k.title()} {v:g}{'+' if _op in ('>=', '>') else ''}",
                         "negated": negated})
            continue
        if k in GATE_IGNORE:
            continue
        if isinstance(v, (Block, Tagged)):
            collect_gates(v, reqs, dlcs, negated or (k in NEGATORS), depth + 1)
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            body = _scripted_trigger(k)
            if body is not None:
                scan_dlc(body, dlcs, depth + 1)


_scripted_triggers: dict | None = None


def _scripted_trigger(name):
    global _scripted_triggers
    if _scripted_triggers is None:
        _scripted_triggers = {}
        for _p, key, blk in ck3.parse_dir(ck3.COMMON / "scripted_triggers"):
            if isinstance(blk, Block):
                _scripted_triggers.setdefault(key, blk)
    return _scripted_triggers.get(name)


def dedupe(reqs):
    seen, out = set(), []
    for r in reqs:
        key = (r["name"], r["negated"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# --------------------------------------------------------------------------

def dyn_loc(field, default_key):
    """title/desc field -> rendered text. String field = loc key; Block field
    = dynamic desc, take the LAST desc loc ref (untriggered fallback)."""
    if field is None:
        raw = ck3.loc(default_key)
        return ck3.render_text(raw) if raw else None
    if isinstance(field, str):
        raw = ck3.loc(field)
        return ck3.render_text(raw) if raw else None
    refs = []

    def walk(blk, depth=0):
        if isinstance(blk, Tagged):
            blk = blk.block
        if not isinstance(blk, Block) or depth > 6:
            return
        for k, _op, v in blk:
            if k == "desc" and isinstance(v, str):
                refs.append(v)
            elif isinstance(v, (Block, Tagged)):
                walk(v, depth + 1)

    walk(field)
    for ref in reversed(refs):
        raw = ck3.loc(ref)
        if raw:
            return ck3.render_text(raw)
    raw = ck3.loc(default_key)
    return ck3.render_text(raw) if raw else None


def effect_tooltips(blk, depth=0, found=None):
    if found is None:
        found = []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block) or depth > 6:
        return found
    for k, _op, v in blk:
        if k == "custom_tooltip":
            text = v.get("text") if isinstance(v, Block) else v
            raw = ck3.loc(text) if isinstance(text, str) else None
            if raw:
                line = ck3.render_text(raw)
                if line and line not in found:
                    found.append(line)
        elif isinstance(v, (Block, Tagged)):
            effect_tooltips(v, depth + 1, found)
    return found


def build_groups():
    out = {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "decision_group_types"):
        if isinstance(blk, Block):
            out[key] = {
                "id": key,
                "name": ck3.render_text(ck3.loc(f"decision_group_type_{key}")
                                        or key.replace("_", " ").title()),
                "sortOrder": blk.get("sort_order", 0),
                "important": bool(blk.get("important_decision_group", False)),
            }
    return out


def decision_files():
    root = ck3.COMMON / "decisions"
    for p in sorted(root.rglob("*.txt")):
        if p.name.startswith("_"):
            continue
        yield p


def main():
    groups = build_groups()
    unhandled = Counter()
    out, excluded = [], Counter()

    for path in decision_files():
        for key, _op, blk in ck3.parse_file(path):
            if key is None or not isinstance(blk, Block):
                continue
            group = blk.get("decision_group_type") or "decisions"
            if group in EXCLUDED_GROUPS:
                excluded[group] += 1
                continue

            reqs, dlcs = [], set()
            collect_gates(blk.get("is_shown"), reqs, dlcs)
            collect_gates(blk.get("is_valid"), reqs, dlcs)
            collect_gates(blk.get("is_valid_showing_failures_only"), reqs, dlcs)
            dlc = sorted(dlcs)[0] if dlcs else path_dlc(path)

            for k in blk.keys():
                if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                    unhandled[k] += 1

            # `picture = { trigger? reference = "gfx/..." }`, first-valid style.
            # The unconditional entry is the fallback the game shows when no
            # trigger matches — that's the one safe to render statically.
            picture = None
            for pb in blk.get_all("picture"):
                if not isinstance(pb, Block):
                    continue
                ref = pb.get("reference")
                if isinstance(ref, str):
                    if not pb.has("trigger"):
                        picture = ref          # unconditional: prefer it
                    elif picture is None:
                        picture = ref          # else keep the first seen
            if isinstance(blk.get("picture"), str):
                picture = blk.get("picture")

            ginfo = groups.get(group, {"important": False})
            rec = {
                "id": key,
                "name": dyn_loc(blk.get("title"), key),
                "desc": dyn_loc(blk.get("desc"), f"{key}_desc"),
                "confirm": dyn_loc(None, f"{key}_confirm"),
                "tooltip": dyn_loc(blk.get("selection_tooltip"), f"{key}_tooltip"),
                "group": group,
                "major": ginfo["important"],
                # taken from another screen (activity planner, unity view) —
                # never listed in the decisions tab itself
                "invisible": bool(blk.get("is_invisible", False)),
                "cost": money_block(blk.get("cost")),
                "minimumCost": money_block(blk.get("minimum_cost")),
                "cooldown": duration(blk.get("cooldown")),
                "requirements": dedupe(reqs),
                "effectText": effect_tooltips(blk.get("effect")),
                "sortOrder": blk.get("sort_order", 0),
                "picture": picture,
                "dlc": dlc,
                "sourceFile": path.name,
            }
            out.append(rec)

    order = {g: i for i, g in enumerate(
        sorted(groups, key=lambda g: -groups[g]["sortOrder"]))}
    out.sort(key=lambda r: (order.get(r["group"], 99), -r["sortOrder"], r["id"]))

    group_list = sorted(groups.values(), key=lambda g: -g["sortOrder"])
    group_list = [g for g in group_list if g["id"] not in EXCLUDED_GROUPS]
    ck3.write_json("decisions.json", {"groups": group_list, "decisions": out})
    print(f"  ({len(out)} decisions; excluded: "
          f"{dict(excluded)} — debug/tutorial-only, as in a normal campaign)")

    if unhandled:
        print("⚠ unhandled decision fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing = [r["id"] for r in out if not r["name"]]
    if missing:
        print(f"⚠ {len(missing)} decisions without localized names: {missing[:10]}")


if __name__ == "__main__":
    main()
