#!/usr/bin/env python3
"""Build src/data/laws.json from common/law_groups/ + common/laws/.

1.20 split the format: law groups are their own definitions in
common/law_groups/ (schema: _law_groups.info), and each law is a top-level
entry in common/laws/ that names its group with `law_group_type` and its
position with `index` (schema: _laws.info; equal indexes fall back to
definition order). We re-nest them into the same group -> laws shape the page
has always read. Fields the data uses beyond the law doc: potential,
requires_approve, widget_name, pass_phrase, title_allegiance_opinion,
can_remove_from_title.

Requirement extraction is shallow (like build_maa.py's collect_requirements):
notable trigger leaves become readable strings with negation tracked;
custom_tooltip/custom_description blocks use their loc'd text and are not
descended into (the game shows exactly that text).
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

GROUP_HANDLED = {"default", "cumulative", "flag", "is_treasury_budget_group",
                 "required_government_flag", "can_have_group"}
GROUP_SKIP = {
    "can_change_law_group": "group-level change gate; per-law can_pass carries the requirements shown",
}

LAW_HANDLED = {
    "law_group_type", "index",  # 1.20: group membership + order within the group
    "modifier", "flag", "succession", "pass_cost", "revoke_cost",
    "can_keep", "can_pass", "can_have", "potential", "should_start_with",
    "shown_in_encyclopedia", "title_allegiance_opinion",
}
LAW_SKIP = {
    "on_pass": "effect script (cooldown variables, modifier cleanup)",
    "on_after_pass": "effect script",
    "on_revoke": "effect script",
    "ai_will_do": "AI enactment weighting, not player-facing",
    "can_title_have": "title-scope visibility trigger; realm-scope gates are rendered",
    "can_realm_have": "realm-scope visibility override, GUI plumbing",
    "should_show_for_title": "GUI visibility plumbing",
    "can_remove_from_title": "GUI removal gate",
    "requires_approve": "diarchy/regency approval plumbing",
    "widget_name": "GUI widget selection",
    "pass_phrase": "GUI confirmation text key",
    "confirmation_title": "GUI confirmation text key",
    "confirmation_button_text": "GUI confirmation text key",
}

SUCCESSION_FIELDS = {
    "order_of_succession": "orderOfSuccession", "title_division": "titleDivision",
    "traversal_order": "traversalOrder", "rank": "rank", "gender_law": "genderLaw",
    "faith": "faith", "election_type": "electionType",
    "appointment_type": "appointmentType", "pool_character_config": "poolCharacterConfig",
    "create_primary_tier_titles": "createPrimaryTierTitles",
    "primary_heir_minimum_share": "primaryHeirMinimumShare",
    "exclude_rulers": "excludeRulers", "limit_to_courtiers": "limitToCourtiers",
    # 1.20 (_laws.info): heirs from outside the realm pass their former titles on
    "resign_outside_realm": "resignOutsideRealm",
}
# repeatable succession keys -> emitted as a list
SUCCESSION_LIST_FIELDS = {
    "required_heir_government_types": "requiredHeirGovernmentTypes",
}

# page section per law-GROUP file (common/law_groups/); the game's own file
# grouping, mirrored 1:1 by the law files in common/laws/
CATEGORY_BY_GROUP_FILE = {
    "00_realm_law_groups.txt": "realm",
    "00_succession_law_groups.txt": "succession",
    "01_title_succession_law_groups.txt": "title_succession",
    "02_admininistrative_law_groups.txt": "administrative",
    "03_imperial_policie_groups.txt": "imperial_policy",
    "04_pam_ecclesiastical_law_groups.txt": "ecclesiastical",
}

NEGATORS = {"NOT", "NOR", "NAND"}
# scope/plumbing keys whose leaves say nothing readable on their own
_PLUMBING = {"exists", "always", "this", "subject", "text", "count", "limit"}

_scripted_triggers: dict | None = None


def scripted_triggers():
    """Law gates hide in scripted-trigger macros (the MAA lesson) — load them
    so describe_trigger can expand `x_trigger = yes` references in place."""
    global _scripted_triggers
    if _scripted_triggers is None:
        _scripted_triggers = {}
        st_dir = ck3.COMMON / "scripted_triggers"
        if st_dir.exists():
            for _p, key, blk in ck3.parse_dir(st_dir):
                if isinstance(blk, Block):
                    _scripted_triggers[key] = blk
    return _scripted_triggers

TIER_NAMES = {"tier_barony": "Barony", "tier_county": "County", "tier_duchy": "Duchy",
              "tier_kingdom": "Kingdom", "tier_empire": "Empire", "tier_hegemony": "Hegemony"}

_DLC_TRIGGER = re.compile(r"^has_([a-z0-9]+)_dlc_trigger$")


def prettify(key):
    return str(key).replace("_", " ").strip().capitalize()


def loc_text(key, *fallbacks):
    for k in (key, *fallbacks):
        raw = ck3.loc(k)
        if raw:
            text = ck3.render_text(raw)
            # $EFFECT_LIST_BULLET$ has no english loc entry; it and raw
            # newlines separate effect lines — normalize to "; "
            text = re.sub(r"\s*EFFECT_LIST_BULLET\s*", "; ", text)
            text = re.sub(r"\s*\n\s*", "; ", text).strip("; ")
            return re.sub(r"(; )+", "; ", text)
    return None


def law_name(key):
    return loc_text(key, f"{key}_name") or prettify(key)


def _cmp_text(key, op, value):
    label = {"piety_level": "Devotion level", "influence_level": "Influence level",
             "legitimacy_level": "Legitimacy level", "prestige_level": "Fame level",
             "highest_held_title_tier": "Highest title tier",
             "title_held_years": "Years holding the title"}.get(key, prettify(key))
    v = TIER_NAMES.get(value, value)
    op = {"=": "is", ">=": "≥", "<=": "≤", ">": ">", "<": "<", "!=": "≠"}.get(op, op)
    return f"{label} {op} {v}"


def gov_flag_text(flag):
    """government_is_X flags -> the government's display name where possible."""
    m = re.match(r"^government_is_(\w+)$", flag)
    if m:
        stem = {"nomadic": "nomad", "theocracy": "theocracy"}.get(m.group(1), m.group(1))
        name = loc_text(f"{stem}_government")
        if name:
            return f"{name} government"
    return loc_text(flag) or prettify(flag.removeprefix("government_")) + " government"


def describe_trigger(trigger, reqs, negated=False, scope=None, depth=0, seen=None):
    """Collect readable requirement strings from a trigger block (shallow)."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block) or depth > 8 or len(reqs) >= 10:
        return
    if seen is None:
        seen = set()

    def add(text):
        if not text:
            return
        text = re.sub(r"\s*\n\s*[•·]?\s*", "; ", str(text)).strip("; ")
        text = re.sub(r"\s+", " ", text)
        # drop lines that are mostly unresolved data-function placeholders
        if text.count("…") >= 2 or not re.search(r"\w", text.replace("…", "")):
            return
        if len(text) > 150:
            text = text[:147].rstrip() + "…"
        entry = {"text": (f"{scope}: {text}" if scope else text), "negated": negated}
        if entry not in reqs and len(reqs) < 10:
            reqs.append(entry)

    for k, op, v in trigger:
        if k is None:
            continue
        if k in ("custom_tooltip", "custom_description") and isinstance(v, Block):
            text_key = v.get("text")
            cd = re.match(r"^has_(\w+)_cooldown$", str(text_key or ""))
            if cd and not ck3.loc(text_key):
                add(f"not on {prettify(cd.group(1))} cooldown")
            else:
                add(loc_text(text_key) or prettify(text_key))
        elif k in ("trigger_if", "trigger_else", "trigger_else_if") and isinstance(v, Block):
            body = Block([t for t in v.triples if t[0] != "limit"])
            describe_trigger(body, reqs, negated, scope, depth + 1, seen)
        elif k in NEGATORS and isinstance(v, (Block, Tagged)):
            describe_trigger(v, reqs, not negated, scope, depth + 1, seen)
        elif k in ("OR", "AND") and isinstance(v, (Block, Tagged)):
            if k == "OR":
                sub = []
                describe_trigger(v, sub, False, None, depth + 1, seen)
                if sub:
                    joined = ", or ".join(r["text"] for r in sub[:4])
                    entry = {"text": (f"{scope}: {joined}" if scope else joined), "negated": negated}
                    if entry not in reqs and len(reqs) < 10:
                        reqs.append(entry)
            else:
                describe_trigger(v, reqs, negated, scope, depth + 1, seen)
        elif k == "has_realm_law" and isinstance(v, str):
            add(f"{law_name(v)} enacted")
        elif k == "has_realm_law_flag" and isinstance(v, str):
            add(f"realm law grants “{prettify(v)}”")
        elif k == "government_has_flag" and isinstance(v, str):
            add(gov_flag_text(v))
        elif k == "government_allows" and isinstance(v, str):
            add(f"{prettify(v)} government mechanics")
        elif k == "has_innovation" and isinstance(v, str):
            add(f"innovation: {loc_text(v) or prettify(v)}")
        elif k == "has_cultural_parameter" and isinstance(v, str):
            add(loc_text(f"culture_parameter_{v}") or f"cultural tradition ({prettify(v)})")
        elif k == "has_cultural_pillar" and isinstance(v, str):
            add(f"heritage: {loc_text(v, f'{v}_name') or prettify(v)}")
        elif k == "has_cultural_tradition" and isinstance(v, str):
            add(f"tradition: {loc_text(v, f'{v}_name') or prettify(v.removeprefix('tradition_'))}")
        elif k == "has_doctrine" and isinstance(v, str):
            add(f"doctrine: {loc_text(v, f'{v}_name') or prettify(v)}")
        elif k == "has_trait" and isinstance(v, str):
            add(f"trait: {loc_text(f'trait_{v}') or prettify(v)}")
        elif k == "has_title" and isinstance(v, str):
            add(f"holds {loc_text(v.removeprefix('title:')) or prettify(v.removeprefix('title:'))}")
        elif k == "has_game_rule" and isinstance(v, str):
            add(f"game rule: {prettify(v)}")
        elif k == "vassal_contract_has_flag" and isinstance(v, str):
            add(f"contract grants “{prettify(v)}”")
        elif k == "is_independent_ruler" and isinstance(v, bool):
            add("independent ruler" if v else "is a vassal")
        elif k == "is_confederation_member" and isinstance(v, bool):
            add("confederation member" if v else "not in a confederation")
        elif k == "has_active_diarchy" and isinstance(v, bool):
            add("active diarchy" if v else "no active diarchy")
        elif k == "is_at_war" and isinstance(v, bool):
            add("at war" if v else "at peace")
        elif k in ("piety_level", "influence_level", "legitimacy_level", "prestige_level",
                   "highest_held_title_tier", "title_held_years"):
            add(_cmp_text(k, op, v))
        elif k.endswith(".herd") or k == "herd":
            n, r = ck3.resolve_value(v) if isinstance(v, str) else (v, None)
            add(f"herd {op} {round(n) if isinstance(n, (int, float)) else prettify(v)}")
        elif isinstance(v, bool) and (m := _DLC_TRIGGER.match(k)):
            dlc = ck3.PREFIX_TO_DLC.get(m.group(1))
            add(f"{dlc} DLC" if dlc else prettify(k))
        elif isinstance(v, bool) and k in scripted_triggers() and k not in seen:
            # expand the macro in place; a `= no` reference flips negation
            seen = seen | {k}
            describe_trigger(scripted_triggers()[k], reqs,
                             negated if v else not negated, scope, depth + 1, seen)
        elif k.endswith("_trigger") and isinstance(v, bool):
            base = re.sub(r"_trigger$", "", k)
            base = re.sub(r"^(can_have_|can_keep_|can_change_|should_have_|historical_succession_access_)", "", base)
            add(prettify(base))
        elif k in ("liege", "top_liege") and isinstance(v, (Block, Tagged)):
            describe_trigger(v, reqs, negated, "Liege", depth + 1, seen)
        elif k in ("culture", "faith", "house", "primary_title", "domicile") and isinstance(v, (Block, Tagged)):
            describe_trigger(v, reqs, negated, scope, depth + 1, seen)
        elif k in _PLUMBING or k.startswith("has_variable") or k.startswith("var:") \
                or k in ("top_liege", "liege", "this", "situation_current_phase") \
                or k.startswith("any_") or k.startswith("situation"):
            continue  # scope plumbing / internal variables
        elif isinstance(v, (Block, Tagged)):
            describe_trigger(v, reqs, negated, scope, depth + 1, seen)


def cost_block(v):
    """pass_cost/revoke_cost -> {currency: {value, varies}} with honest rules."""
    if v is None or not isinstance(v, Block):
        return None
    out = {}
    for cur, _op, val in v:
        if cur is None:
            continue
        n, rules = ck3.resolve_value(val)
        if n is not None:
            out[cur] = {"value": round(n, 1), "varies": False}
        else:
            base = _base_of(rules)
            # a chain of unconditional add/base wrappers is effectively static
            conditional = bool(re.search(r"'(?:if|else|else_if|min|max|multiply)'", repr(rules)))
            out[cur] = {"value": base, "varies": conditional or base is None, "rules": rules}
    return out or None


def _base_of(rules, depth=0):
    """First numeric base/add in a resolve_value rule structure, if any.
    Follows named script values referenced in conditional `then` clauses so
    `pass_cost = { prestige = { if = { add = X } } }` still yields X's base."""
    if not isinstance(rules, list) or depth > 4:
        return None
    for r in rules:
        if not isinstance(r, dict):
            continue
        for key in ("base", "value", "add", "then"):
            v = r.get(key)
            if isinstance(v, (int, float)):
                return v
            if isinstance(v, list):
                if key == "then":
                    for step in v:
                        m = re.match(r"^(?:add|value) (\S+)$", str(step))
                        if m:
                            n, sub = ck3.resolve_value(m.group(1))
                            if n is not None:
                                return n
                            b = _base_of(sub, depth + 1)
                            if b is not None:
                                return b
                else:
                    b = _base_of(v, depth + 1)
                    if b is not None:
                        return b
    return None


def scan_dlc(block, found, depth=0, seen=None):
    """has_<x>_dlc_trigger reached through *conjunctive* branches only — a DLC
    check inside an OR alternative does not gate the law on that DLC."""
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block) or depth > 6:
        return
    seen = seen or set()
    for k, _op, v in block:
        if not isinstance(k, str):
            continue
        m = _DLC_TRIGGER.match(k)
        if m and m.group(1) in ck3.PREFIX_TO_DLC:
            found.add(ck3.PREFIX_TO_DLC[m.group(1)])
        elif k in ("OR", "NOT", "NOR", "NAND", "custom_tooltip", "custom_description",
                   "trigger_if", "trigger_else", "trigger_else_if"):
            continue  # alternative/negated/conditional branch, not a hard gate
        elif isinstance(v, bool) and k in scripted_triggers() and v and k not in seen:
            scan_dlc(scripted_triggers()[k], found, depth + 1, seen | {k})
        elif isinstance(v, (Block, Tagged)):
            scan_dlc(v, found, depth + 1, seen)


LAW_ICONS = {  # keys that ship a gfx/interface/icons/laws/<key>.dds
    # populated at runtime by checking the repo-local reference gfx list is not
    # possible (gfx lives only in the mirror); build_art.py handles absence
    # with quiet fallback, and the page renders icons only when present.
}


def government_index():
    """government flag -> [{id, name}] of the governments carrying it, so a
    group's `required_government_flag` can name who actually gets the group."""
    out = {}
    for _p, gkey, gblk in ck3.parse_dir(ck3.COMMON / "governments"):
        if not isinstance(gblk, Block):
            continue
        fb = gblk.get("flags")
        if not isinstance(fb, Block):
            continue
        raw = ck3.loc(gkey)
        name = ck3.render_text(raw) if raw else prettify(gkey)
        for f in fb.values():
            if isinstance(f, str):
                out.setdefault(f, []).append({"id": gkey, "name": name})
    return out


def build_law(path, lkey, lblk, gblk, group_dlc, unhandled_law):
    mods = []
    mb = lblk.get("modifier")
    if isinstance(mb, Block):
        for mk, _o3, mv in mb:
            if mk is not None:
                mods.append({"key": mk, "text": ck3.render_modifier(mk, mv),
                             "polarity": ck3.modifier_polarity(mk, mv)})

    lflags = []
    for fk, _o3, fv in lblk:
        if fk == "flag" and isinstance(fv, str):
            lflags.append({"key": fv, "name": loc_text(fv)})

    succ = None
    sb = lblk.get("succession")
    if isinstance(sb, Block):
        succ = {}
        for sk, _o3, sv in sb:
            if sk in SUCCESSION_FIELDS:
                succ[SUCCESSION_FIELDS[sk]] = sv
            elif sk in SUCCESSION_LIST_FIELDS:
                succ.setdefault(SUCCESSION_LIST_FIELDS[sk], []).append(sv)
            elif sk is not None:
                unhandled_law[f"succession.{sk}"] += 1

    reqs = {}
    for trig, label in (("can_pass", "pass"), ("can_keep", "keep"),
                        ("can_have", "have"), ("potential", "potential"),
                        ("should_start_with", "startsWith")):
        if lblk.has(trig):
            r = []
            describe_trigger(lblk.get(trig), r)
            reqs[label] = r

    for k in lblk.keys():
        if k not in LAW_HANDLED and k not in LAW_SKIP:
            unhandled_law[k] += 1

    # DLC: a conjunctive has_<x>_dlc_trigger gate first, then the file's own
    # prefix / has_dlc_feature (04_pam_* -> By God Alone), then the group's
    dlcs = set()
    for gate in ("can_have", "can_keep", "potential", "should_start_with"):
        scan_dlc(lblk.get(gate), dlcs)
    dlc = sorted(dlcs)[0] if dlcs else (ck3.dlc_tag(path, lblk)[0] or group_dlc)

    m = re.search(r"_(\d+)$", lkey)
    idx = lblk.get("index", 0)
    return {
        "id": lkey,
        "name": law_name(lkey),
        "effects": loc_text(f"{lkey}_effects"),
        "level": int(m.group(1)) if m else None,
        "index": idx if isinstance(idx, int) else 0,
        "isDefault": gblk.get("default") == lkey,
        "modifiers": mods,
        "flags": lflags,
        "succession": succ,
        "passCost": cost_block(lblk.get("pass_cost")),
        "revokeCost": cost_block(lblk.get("revoke_cost")),
        "requirements": reqs,
        "titleAllegianceOpinion": lblk.get("title_allegiance_opinion"),
        "shownInEncyclopedia": lblk.get("shown_in_encyclopedia", True) is not False,
        "dlc": dlc,
    }


def main():
    unhandled_group = Counter()
    unhandled_law = Counter()
    govs = government_index()

    # 1. groups, in group-file definition order
    group_defs = {}
    for gpath, gkey, gblk in ck3.parse_dir(ck3.COMMON / "law_groups"):
        if gpath.name.startswith("_") or gkey is None:
            continue
        if not isinstance(gblk, Block):
            gblk = Block([])  # `succession_faith = { }` still declares a group
        if gkey in group_defs:
            print(f"⚠ law group {gkey} defined twice; keeping the later one")
        group_defs[gkey] = (gpath, gblk)
        for k in gblk.keys():
            if k not in GROUP_HANDLED and k not in GROUP_SKIP:
                unhandled_group[k] += 1

    # 2. laws, bucketed by law_group_type
    members = {}
    orphans = []
    order = 0
    for lpath, lkey, lblk in ck3.parse_dir(ck3.COMMON / "laws"):
        if lpath.name.startswith("_") or lkey is None or not isinstance(lblk, Block):
            continue
        gtype = lblk.get("law_group_type")
        if gtype not in group_defs:
            orphans.append((lkey, gtype))
            continue
        order += 1
        idx = lblk.get("index", 0)
        members.setdefault(gtype, []).append(
            ((idx if isinstance(idx, int) else 0), order, lpath, lkey, lblk))

    groups = []
    law_count = 0
    for gkey, (gpath, gblk) in group_defs.items():
        rows = sorted(members.get(gkey, []), key=lambda t: (t[0], t[1]))
        if not rows:
            print(f"⚠ law group {gkey} has no laws; not emitted")
            continue
        category = CATEGORY_BY_GROUP_FILE.get(gpath.name)
        if category is None:
            print(f"⚠ {gpath.name} has no CATEGORY_BY_GROUP_FILE entry; {gkey} filed under realm")
            category = "realm"
        group_dlc = ck3.dlc_tag(gpath, gblk)[0]
        laws = [build_law(lp, lk, lb, gblk, group_dlc, unhandled_law)
                for _i, _o, lp, lk, lb in rows]
        law_count += len(laws)

        req_gov = []
        rgf = gblk.get("required_government_flag")
        if isinstance(rgf, Block):
            for f in rgf.values():
                if isinstance(f, str):
                    req_gov.append({"flag": f, "governments": govs.get(f, [])})
        group_reqs = []
        if gblk.has("can_have_group"):
            describe_trigger(gblk.get("can_have_group"), group_reqs)

        gflags = [v for k, _o, v in gblk if k == "flag" and isinstance(v, str)]
        has_levels = all(l["level"] is not None for l in laws) and len(laws) > 1
        groups.append({
            "id": gkey,
            "name": loc_text(gkey) or prettify(gkey),
            "category": category,
            "cumulative": bool(gblk.get("cumulative", False)),
            "default": gblk.get("default"),
            "flags": gflags,
            "treasuryBudget": bool(gblk.get("is_treasury_budget_group", False)),
            "progression": has_levels,
            "requiredGovernments": req_gov,
            "groupRequirements": group_reqs,
            "dlc": group_dlc,
            "laws": laws,
            "sourceFile": rows[0][2].name,
            "groupSourceFile": gpath.name,
        })

    ck3.write_json("laws.json", groups)
    print(f"  ({law_count} laws in {len(groups)} groups)")

    if orphans:
        print("⚠ laws whose law_group_type names no common/law_groups entry (not emitted):")
        for lkey, gtype in orphans:
            print(f"    {lkey} -> {gtype}")
    if unhandled_group:
        print("⚠ unhandled law-GROUP fields (add to GROUP_HANDLED or GROUP_SKIP):")
        for k, n in unhandled_group.most_common():
            print(f"    {k} ×{n}")
    if unhandled_law:
        print("⚠ unhandled law fields (add to LAW_HANDLED or LAW_SKIP):")
        for k, n in unhandled_law.most_common():
            print(f"    {k} ×{n}")


if __name__ == "__main__":
    main()
