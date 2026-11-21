#!/usr/bin/env python3
"""Build src/data/doctrines.json from common/religion/ (CK3 1.20+ layout).

Since 1.20 (By God Alone) the religion data is split into separate databases:

  doctrine_category_types/  categories (sort order, visibility)
  doctrine_group_types/     groups (category, divergence model, lock level)
  doctrine_types/           doctrines; each names its own `doctrine_group_type`
                            and `index` (order within the group)
  tenet_types/              tenets — no longer a doctrine group at all

Emits {categories, groups, doctrines}. Tenets are emitted as doctrines with
isTenet=True inside one synthetic group, `doctrine_core_tenets`, whose pick
count is the define NReligion FAITH_CORE_TENETS_CAP (read at build time). The
id is kept from the 1.19 layout so existing page anchors stay valid.

Piety costs stay honest: the value/if/else chains in the data become
{values: [{when, value}], mults: [{when, factor}]} rule structures; only the
unconditional single-value case collapses to a number.

Schema docs: _doctrine_types.info, _doctrine_group_types.info,
_doctrine_category_types.info, _tenet_types.info.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

RELIGION = ck3.COMMON / "religion"
TENET_GROUP = "doctrine_core_tenets"

SKIP_FIELDS = {
    "historical_glossary": "rendered separately as `glossary` (hyperlinked glossary term)",
}

HANDLED_FIELDS = {
    "icon", "name", "desc", "visible", "parameters", "piety_cost", "is_shown",
    "can_pick", "character_modifier", "clergy_modifier", "county_modifier",
    "traits", "special_parameters", "doctrine_group_type", "index",
    "divergence", "divergence_multiplier", "requires_dlc_flag",
    "personal_tenet_modifier", "personal_tenet_parameters",
    "can_pick_as_personal_tenet", "historical_glossary", "descriptive_name",
}

SKIP_GROUP_FIELDS = {}
HANDLED_GROUP_FIELDS = {"category", "divergence", "doctrine_lock", "main_rite",
                        "is_available_on_create"}

SKIP_CATEGORY_FIELDS = {"gui_tags": "GUI layout tags (sizing of the in-game panel)"}
HANDLED_CATEGORY_FIELDS = {"visible", "sort_order"}


def read_define(namespace, key):
    for ns, _op, blk in ck3.parse_file(ck3.COMMON / "defines" / "00_defines.txt"):
        if ns == namespace and isinstance(blk, Block):
            return blk.get(key)
    return None


# --- DLC triggers -----------------------------------------------------------

_dlc_triggers: dict | None = None


def dlc_trigger_map():
    """has_*_dlc_trigger scripted-trigger name -> DLC display name."""
    global _dlc_triggers
    if _dlc_triggers is None:
        _dlc_triggers = {}
        p = ck3.COMMON / "scripted_triggers" / "00_has_dlc_scripted_triggers.txt"
        if p.exists():
            for key, _op, blk in ck3.parse_file(p):
                if isinstance(blk, Block):
                    feat = blk.get("has_dlc_feature")
                    if isinstance(feat, str):
                        _dlc_triggers[key] = ck3.FEATURE_TO_DLC.get(feat, feat)
    return _dlc_triggers


# --- names ------------------------------------------------------------------

def _desc_keys(v, out):
    """Collect the desc loc keys inside a dynamic name/desc block, in order."""
    if isinstance(v, Tagged):
        v = v.block
    if isinstance(v, str):
        out.append(v)
        return
    if not isinstance(v, Block):
        return
    for k, _op, val in v:
        if k == "desc" and isinstance(val, str):
            out.append(val)
        elif isinstance(val, (Block, Tagged)):
            _desc_keys(val, out)


def dynamic_names(blk, field, default_key):
    """(primary, variants) for a name/desc, honoring dynamic blocks.

    The default key (e.g. <key>_name) comes first when it exists; otherwise
    the LAST entry of a first_valid chain is the untriggered fallback, so it
    is preferred over the triggered variants.
    """
    keys = []
    _desc_keys(blk.get(field), keys)
    if keys and default_key not in keys and not ck3.loc(default_key):
        keys = [keys[-1]] + keys[:-1]
    if default_key and default_key not in keys:
        keys.insert(0, default_key)
    rendered = []
    for k in keys:
        raw = ck3.loc(k)
        if raw:
            t = ck3.render_text(raw)
            if t and t not in rendered:
                rendered.append(t)
    primary = rendered[0] if rendered else None
    return primary, rendered[1:]


def doctrine_display_name(key):
    raw = ck3.loc(f"{key}_name") or ck3.loc(key)
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


# --- piety cost -------------------------------------------------------------

def cond_name(key):
    """Doctrine/tenet name for use inside a condition: the game's descriptive
    name when it has one ("Pagan-aligned Hostility" rather than "Pagan")."""
    raw = ck3.loc(f"{key}_descriptive_name")
    return ck3.render_text(raw) if raw else doctrine_display_name(key)


_HAS = ("has_doctrine", "rite_has_doctrine", "has_tenet", "rite_has_tenet")
_REL = ("religion_tag", "rite_religion_tag")


def limit_match(limit):
    """A limit that is a single term or an OR of religion / family / doctrine
    terms -> {religions, families, doctrines} the client can evaluate against
    a faith. Anything else (AND, NOT, other triggers) -> None."""
    if not isinstance(limit, Block):
        return None
    m = {"religions": [], "families": [], "doctrines": [], "faiths": [], "rites": []}
    def walk(b, top):
        terms = list(b)
        if top and len(terms) != 1 and not all(k == "OR" for k, _o, _v in terms):
            # several top-level terms are an implicit AND
            return False
        for k, _op, v in terms:
            if k in _REL and isinstance(v, str):
                m["religions"].append(v)
            elif k in _HAS and isinstance(v, str):
                m["doctrines"].append(v)
            elif k == "religion" and isinstance(v, Block) and v.get("is_in_family")                     and len(v) == 1:
                m["families"].append(v.get("is_in_family"))
            elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
                m["religions"].append(v.removeprefix("religion:"))
            elif k == "faith" and isinstance(v, str) and v.startswith("faith:"):
                m["faiths"].append(v.removeprefix("faith:"))
            elif k == "this" and isinstance(v, str) and v.startswith("rite:"):
                m["rites"].append(v.removeprefix("rite:"))
            elif k == "OR" and isinstance(v, Block):
                if not walk(v, False):
                    return False
            else:
                return False
        return True
    return m if walk(limit, True) and any(m.values()) else None


def _religion_names(limit):
    names = []
    def walk(b):
        for k, _op, v in b:
            if k in _REL and isinstance(v, str):
                names.append(ck3.render_text(ck3.loc(v) or v))
            elif k in _HAS and isinstance(v, str):
                names.append(f"faiths with {cond_name(v)}")
            elif k == "religion" and isinstance(v, Block):
                fam = v.get("is_in_family")
                if fam:
                    names.append(ck3.render_text(ck3.loc(fam) or str(fam)) + " family")
            elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
                r = v.removeprefix("religion:")
                names.append(ck3.render_text(ck3.loc(r) or r))
            elif k in ("OR", "AND") and isinstance(v, Block):
                walk(v)
    walk(limit)
    return names


def describe_limit(limit, self_key, as_change=False):
    """A piety_cost limit -> short human condition ('' if unrecognized).

    `as_change`: in a multiplier, a lone "current rite has X" test is the
    game's step-distance surcharge for switching away from X ("had X")."""
    if not isinstance(limit, Block):
        return None
    keys = limit.keys()
    if len(keys) == 1 and keys[0] in _HAS:
        d = limit.get(keys[0])
        if d == self_key:
            return "keeping this doctrine"
        return f"had {cond_name(d)}" if as_change else f"faiths with {cond_name(d)}"
    rels = _religion_names(limit)
    if rels and all(k in _REL + ("religion", "OR", "AND") + _HAS for k in keys):
        return " or ".join(rels)
    return ck3._describe_trigger(limit)


def piety_cost(pc, self_key):
    if pc is None:
        return None
    if isinstance(pc, (int, float, str)):
        n, rules = ck3.resolve_value(pc)
        return {"base": round(n, 1) if n is not None else None,
                "values": [], "mults": [], "notes": [] if n is not None else [str(rules)]}
    values, mults, notes = [], [], []
    base = None
    for k, _op, v in pc:
        if k == "value":
            n, r = ck3.resolve_value(v)
            base = n if n is not None else base
            if n is None:
                notes.append(f"value {r}")
        elif k in ("if", "else_if", "else") and isinstance(v, Block):
            lim = v.get("limit")
            iv, im = v.get("value"), v.get("multiply")
            match = None if k == "else" else limit_match(lim)
            if iv is not None:
                n, r = ck3.resolve_value(iv)
                when = "otherwise" if k == "else" else describe_limit(lim, self_key)
                values.append({"when": when, "value": n if n is not None else str(r),
                               "match": match, "else": k == "else"})
            if im is not None:
                n, r = ck3.resolve_value(im)
                when = "otherwise" if k == "else" else describe_limit(lim, self_key, True)
                mults.append({"when": when, "factor": n if n is not None else str(r),
                              "match": match, "else": k == "else",
                              "keep": bool(match) and match["doctrines"] == [self_key]})
            extra = [kk for kk, _o, _vv in v if kk not in (None, "limit", "value", "multiply")]
            if extra:
                notes.append(f"{k} also: {', '.join(extra)}")
        elif k in ("multiply", "divide", "add", "subtract", "min", "max", "ceiling", "round"):
            n, r = ck3.resolve_value(v)
            notes.append(f"{k} {n if n is not None else r}")
        elif k is not None:
            notes.append(k)
    return {"base": base, "values": values, "mults": mults, "notes": notes}


# --- parameters -------------------------------------------------------------

_VALUE_SUB = re.compile(r"\$VALUE(\|[^$]*)?\$")


def _fmt_value(value, fmt):
    """Apply the loc format flags we can honour: % (x100), + / = (sign)."""
    fmt = (fmt or "").lstrip("|")
    num = value
    if isinstance(num, bool):
        return ""
    if "%" in fmt and isinstance(num, (int, float)):
        num = num * 100
    if isinstance(num, float) and float(num).is_integer():
        num = int(num)
    txt = str(round(num, 2) if isinstance(num, float) else num)
    if "+" in fmt and isinstance(num, (int, float)) and num > 0:
        txt = "+" + txt
    if "%" in fmt:
        txt += "%"
    return txt


def _sub_value(raw, value):
    return ck3.render_text(_VALUE_SUB.sub(lambda m: _fmt_value(value, m.group(1)), raw))


def hostility_level_name(level):
    """'astray' / 1 -> the game's concept name for that hostility level."""
    names = ("righteous", "astray", "hostile", "evil")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        level = names[max(0, min(3, int(level)))]
    raw = ck3.loc(f"game_concept_faith_{level}")
    return ck3.render_text(raw) if raw else str(level).title()


def param_text(key, value):
    cands = []
    if value is False:
        cands = [f"doctrine_parameter_{key}_disabled", f"doctrine_parameter_{key}"]
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            cands = [f"doctrine_parameter_{key}_{int(value)}"]
        cands.append(f"doctrine_parameter_{key}")
    else:
        cands = [f"doctrine_parameter_{key}"]
    for c in cands:
        raw = ck3.loc(c)
        if raw is not None:
            return _sub_value(raw, value)
    return None


def param_list(blk):
    params = []
    if isinstance(blk, Block):
        for pk, _op, pv in blk:
            if pk is None:
                pk, pv = str(pv), True  # bare parameter name means "set"
            params.append({"key": pk, "value": pv, "text": param_text(pk, pv)})
    return params


# Labels for loc-less special parameters are the field descriptions from
# _doctrine_types.info, not our wording.
SPECIAL_LABELS = {
    "number_of_spouses": "Number of spouses",
    "number_of_consorts": "Number of consorts",
    "bonus_fervor_gain": "Flat additional yearly fervor gain",
    "bonus_heresy_protection": "Additional negated heresies",
    "divergence_protection": "Negates fervor loss due to divergent rites",
    "minimum_fervor": "Fervor cannot go below",
    "heresy_threshold": "Heretical rite divergence threshold",
}
HOSTILITY_SCOPES = {
    "same_religion": "Faiths of the same religion",
    "same_family": "Faiths of the same family",
    "unrelated": "Faiths of other families",
}


def special_lines(sp):
    """special_parameters -> list of {key, text} in definition order."""
    out = []
    if not isinstance(sp, Block):
        return out
    for k, _op, v in sp:
        if k == "hostility_levels" and isinstance(v, Block):
            for sk, _o, lvl in v:
                out.append({"key": f"{k}.{sk}",
                            "text": f"{HOSTILITY_SCOPES.get(sk, sk)} are considered "
                                    f"{hostility_level_name(lvl)}"})
        elif k == "hostility_level_override" and isinstance(v, Block):
            for dk, _o, lvl in v:
                out.append({"key": f"{k}.{dk}",
                            "text": f"Faiths with {doctrine_display_name(dk)} are considered "
                                    f"{hostility_level_name(lvl)}"})
        elif k == "same_hof_hostility_override":
            out.append({"key": k, "text": "Faiths sharing their Head of Faith are considered "
                                          f"{hostility_level_name(v)}"})
        elif k == "parameter_opinion_override" and isinstance(v, Block):
            for pk, _o, n in v:
                raw = ck3.loc(f"doctrine_parameter_{pk}_opinion_active")
                label = ck3.render_text(raw) if raw else pk.replace("_", " ")
                out.append({"key": f"{k}.{pk}", "text": f"+{n} opinion: {label}"})
        elif k == "allowed_holding_types" and isinstance(v, Block):
            names = [ck3.render_text(ck3.loc(h) or h) for h in v.values() if isinstance(h, str)]
            out.append({"key": k, "text": "Can hold " + ", ".join(names)
                        + " regardless of government"})
        else:
            txt = param_text(k, v)
            if txt is None:
                label = SPECIAL_LABELS.get(k, k.replace("_", " "))
                txt = f"{label}: {v}"
            out.append({"key": k, "text": txt})
    return out


# --- triggers ---------------------------------------------------------------

NEGATORS = {"NOT", "NOR", "NAND"}
_DOCTRINE_REF = re.compile(r"^(?:doctrine|tenet):(\w+)$")


def collect_shown(trigger, out, negated=False):
    """is_shown -> ([condition strings], dlc name or None)."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        neg = negated or (k in NEGATORS)
        pre = "not " if neg else ""
        if k in ("religion_tag", "rite_religion_tag") and isinstance(v, str):
            out["religions"].append(pre + ck3.render_text(ck3.loc(v) or v))
        elif k in _HAS and isinstance(v, str):
            out["conds"].append(f"{pre}has {doctrine_display_name(v)}")
        elif k == "has_doctrine_parameter" and isinstance(v, str):
            out["conds"].append(f"{pre}{v.replace('_', ' ')}")
        elif k in dlc_trigger_map():
            if not neg:
                out["dlc"] = dlc_trigger_map()[k]
            else:
                out["conds"].append(f"without {dlc_trigger_map()[k]} DLC")
        elif k == "has_game_rule" and isinstance(v, str):
            out["conds"].append(f"{pre}game rule {v.replace('_', ' ')}")
        elif k == "always" and v is False:
            out["conds"].append("script-assigned only")
        elif k == "religion" and isinstance(v, Block) and v.get("is_in_family"):
            fam = v.get("is_in_family")
            out["religions"].append(pre + ck3.render_text(ck3.loc(fam) or str(fam)) + " family")
        elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
            r = v.removeprefix("religion:")
            out["religions"].append(pre + ck3.render_text(ck3.loc(r) or r))
        elif isinstance(v, (Block, Tagged)):
            collect_shown(v, out, neg)
        else:
            out["conds"].append(f"{pre}{k}".strip())


def collect_pick(trigger, incompat, requires, notes, negated=False):
    """can_pick -> incompatible/required doctrine keys + leftover notes."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        m = _DOCTRINE_REF.match(k)
        if m:
            (incompat if (negated) else requires).append(m.group(1))
        elif k in NEGATORS or k in ("custom_description", "AND", "OR", "trigger_if"):
            collect_pick(v, incompat, requires, notes,
                         negated or (k in NEGATORS))
        elif k in ("text", "always", "limit"):
            continue
        elif isinstance(v, (Block, Tagged)):
            notes.append(f"{'not ' if negated else ''}{k.replace('_', ' ')}")
        else:
            notes.append(f"{'not ' if negated else ''}{k.replace('_', ' ')} {v}")


# --- modifiers --------------------------------------------------------------

def modifier_lines(blk):
    lines = []
    if not isinstance(blk, Block):
        return lines
    for k, _op, v in blk:
        if k is None or k == "name":
            continue
        if isinstance(v, str):
            n, _r = ck3.resolve_value(v)
            v = n if n is not None else v
        if isinstance(v, (Block, Tagged)):
            lines.append(f"{ck3.modifier_name(k)}: (conditional)")
        else:
            lines.append(ck3.render_modifier(k, v))
    return lines


def trait_list(traits, field):
    v = traits.get(field) if isinstance(traits, Block) else None
    out = []
    if isinstance(v, Block):
        keys = [x for x in v.values() if isinstance(x, str)] + \
               [k for k, _op, _v in v if k is not None]
        for t in keys:
            raw = ck3.loc(f"trait_{t}") or ck3.loc(t)
            out.append(ck3.render_text(raw) if raw else t.replace("_", " ").title())
    return out


def number(v):
    n, _r = ck3.resolve_value(v) if v is not None else (None, None)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return n


# --- records ----------------------------------------------------------------

def build_record(path, key, blk, group, is_tenet, unhandled):
    for k in blk.keys():
        if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
            unhandled[k] += 1

    name, name_variants = dynamic_names(blk, "name", f"{key}_name")
    desc, desc_variants = dynamic_names(blk, "desc", f"{key}_desc")
    descriptive, _ = dynamic_names(blk, "descriptive_name", f"{key}_descriptive_name")
    glossary, glossary_variants = dynamic_names(blk, "historical_glossary", None) \
        if blk.get("historical_glossary") is not None else (None, [])

    shown = {"religions": [], "conds": [], "dlc": None}
    collect_shown(blk.get("is_shown"), shown)
    incompat, requires, pick_notes = [], [], []
    collect_pick(blk.get("can_pick"), incompat, requires, pick_notes)
    pick_notes = list(dict.fromkeys(pick_notes))

    personal = None
    if is_tenet and (blk.get("personal_tenet_modifier") is not None
                     or blk.get("personal_tenet_parameters") is not None):
        pshown = {"religions": [], "conds": [], "dlc": None}
        collect_shown(blk.get("can_pick_as_personal_tenet"), pshown)
        personal = {
            "modifier": modifier_lines(blk.get("personal_tenet_modifier")),
            "parameters": param_list(blk.get("personal_tenet_parameters")),
            "conditions": (pshown["religions"] + pshown["conds"]) or None,
        }

    dlc, _features = ck3.dlc_tag(path, blk)
    req_flag = blk.get("requires_dlc_flag")
    if isinstance(req_flag, str):
        dlc = ck3.FEATURE_TO_DLC.get(req_flag, dlc)

    return {
        "id": key,
        "name": name or key.replace("_", " ").title(),
        "descriptiveName": descriptive if descriptive and descriptive != name else None,
        "nameVariants": name_variants,
        "desc": desc,
        "descVariants": desc_variants,
        "glossary": glossary,
        "glossaryVariants": glossary_variants,
        "group": group,
        "isTenet": is_tenet,
        "index": number(blk.get("index")),
        "divergence": number(blk.get("divergence")),
        "divergenceMultiplier": number(blk.get("divergence_multiplier")),
        "visible": blk.get("visible", True) is not False,
        "pietyCost": piety_cost(blk.get("piety_cost"), key),
        "parameters": param_list(blk.get("parameters")),
        "specialParameters": special_lines(blk.get("special_parameters")),
        "characterModifier": modifier_lines(blk.get("character_modifier")),
        "clergyModifier": modifier_lines(blk.get("clergy_modifier")),
        "countyModifier": modifier_lines(blk.get("county_modifier")),
        "personal": personal,
        "virtues": trait_list(blk.get("traits"), "virtues"),
        "sins": trait_list(blk.get("traits"), "sins"),
        "shownForReligions": shown["religions"],
        "shownConditions": shown["conds"],
        "incompatibleWith": sorted(set(incompat)),
        "requiresDoctrines": sorted(set(requires)),
        "pickNotes": pick_notes,
        "icon": str(blk.get("icon") or key).removesuffix(".dds")
                if not isinstance(blk.get("icon"), Block) else key,
        "dlc": shown["dlc"] or dlc,
        "sourceFile": path.name,
    }


def main():
    unhandled, unhandled_grp, unhandled_cat = Counter(), Counter(), Counter()

    # categories ------------------------------------------------------------
    categories = {}
    for _p, ckey, blk in ck3.parse_dir(RELIGION / "doctrine_category_types"):
        for k in blk.keys():
            if k not in HANDLED_CATEGORY_FIELDS and k not in SKIP_CATEGORY_FIELDS:
                unhandled_cat[k] += 1
        raw = ck3.loc(f"doctrine_category_{ckey}")
        categories[ckey] = {
            "id": ckey,
            "name": ck3.render_text(raw) if raw else ckey.replace("_", " ").title(),
            "sortOrder": number(blk.get("sort_order")) or 0,
            "visible": blk.get("visible", True) is not False,
        }
    tenets_name = ck3.render_text(ck3.loc("game_concept_tenets") or "Tenets")
    categories["core_tenets"] = {"id": "core_tenets", "name": tenets_name,
                                 "sortOrder": None, "visible": True}

    # doctrines (grouped by their own doctrine_group_type) ------------------
    out = []
    order = 0
    for path, key, blk in ck3.parse_dir(RELIGION / "doctrine_types"):
        if not isinstance(blk, Block):
            continue
        rec = build_record(path, key, blk, blk.get("doctrine_group_type"), False, unhandled)
        rec["_order"] = order
        order += 1
        out.append(rec)

    # tenets ------------------------------------------------------------------
    for path, key, blk in ck3.parse_dir(RELIGION / "tenet_types"):
        if not isinstance(blk, Block):
            continue
        rec = build_record(path, key, blk, TENET_GROUP, True, unhandled)
        rec["_order"] = order
        order += 1
        out.append(rec)

    # groups --------------------------------------------------------------------
    members = {}
    for r in sorted(out, key=lambda r: (r["index"] if r["index"] is not None else 0,
                                        r["_order"])):
        members.setdefault(r["group"], []).append(r["id"])

    groups = []
    for _p, gkey, blk in ck3.parse_dir(RELIGION / "doctrine_group_types"):
        for k in blk.keys():
            if k not in HANDLED_GROUP_FIELDS and k not in SKIP_GROUP_FIELDS:
                unhandled_grp[k] += 1
        avail = {"religions": [], "conds": [], "dlc": None}
        collect_shown(blk.get("is_available_on_create"), avail)
        cat = blk.get("category")
        lock = blk.get("doctrine_lock")
        groups.append({
            "id": gkey,
            "name": ck3.render_text(ck3.loc(f"{gkey}_name") or gkey.replace("_", " ").title()),
            "category": cat,
            "categoryName": categories.get(cat, {}).get("name") or str(cat),
            "picks": 1,
            "divergence": blk.get("divergence") or "category",
            "lock": lock if lock and lock != "none" else None,
            "mainRiteOnly": blk.get("main_rite") is True,
            "doctrines": members.get(gkey, []),
            "availability": (avail["religions"] + avail["conds"]) or None,
            "dlc": avail["dlc"],
        })
    cap = number(read_define("NReligion", "FAITH_CORE_TENETS_CAP"))
    if cap is None:
        raise SystemExit("✗ NReligion.FAITH_CORE_TENETS_CAP not found in defines")
    groups.append({
        "id": TENET_GROUP, "name": tenets_name, "category": "core_tenets",
        "categoryName": tenets_name, "picks": cap, "divergence": None, "lock": None,
        "mainRiteOnly": False, "doctrines": members.get(TENET_GROUP, []),
        "availability": None, "dlc": None,
    })

    known_groups = {g["id"] for g in groups}
    orphans = sorted(r["id"] for r in out if r["group"] not in known_groups)
    if orphans:
        print(f"⚠ doctrines naming an undeclared doctrine_group_type: {orphans}")

    for r in out:
        r.pop("_order")
    out.sort(key=lambda r: (r["group"] or "zz", r["index"] or 0, r["id"]))
    cats = sorted(categories.values(),
                  key=lambda c: (-(c["sortOrder"] if c["sortOrder"] is not None else 99)))
    ck3.write_json("doctrines.json", {"categories": cats, "groups": groups, "doctrines": out})
    print(f"  ({len(cats)} categories, {len(groups)} groups, "
          f"{sum(1 for r in out if not r['isTenet'])} doctrines, "
          f"{sum(1 for r in out if r['isTenet'])} tenets, core tenet cap {cap})")

    for label, c in (("doctrine/tenet", unhandled), ("group", unhandled_grp),
                     ("category", unhandled_cat)):
        if c:
            print(f"⚠ unhandled {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    unloc_params = sum(1 for r in out for p in r["parameters"] if p["text"] is None)
    print(f"  ({unloc_params} parameter values without loc text — shown as raw key: value)")


if __name__ == "__main__":
    main()
