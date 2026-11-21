#!/usr/bin/env python3
"""Build src/data/doctrines.json from common/religion/ doctrine_category_types,
doctrine_group_types, doctrine_types and tenet_types (1.21 model).

Emits {categories, groups, doctrines, defines}. Tenets are no longer a
doctrine group: they come from tenet_types/ and are emitted in the same
`doctrines` list with `isTenet: true` (other scripts key on that flag) and
`group: null`. A doctrine now names its own group (`doctrine_group_type`)
and its order in it (`index`).

Piety costs stay honest. Each `piety_cost` script value is compiled into an
ordered list of steps ({op, value} / {op: 'if', cond, then}) whose conditions
are machine-checkable where the game's trigger is (religion, family, faith,
rite already has doctrine/tenet) and `{unknown: text}` otherwise. The
doctrines page renders the steps as text; the faith-creator evaluates them.

Schema docs: _doctrine_category_types.info, _doctrine_group_types.info,
_doctrine_types.info, _tenet_types.info.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import ck3_religion as R
from ck3 import Block, Tagged

HANDLED_DOCTRINE_FIELDS = {
    "icon", "name", "desc", "historical_glossary", "visible", "parameters", "piety_cost",
    "is_shown", "can_pick", "character_modifier", "clergy_modifier", "traits",
    "doctrine_group_type", "index", "divergence", "special_parameters",
}
SKIP_DOCTRINE_FIELDS = {
    "descriptive_name": "alternate UI label for the same doctrine; the name is shown",
}

HANDLED_TENET_FIELDS = {
    "icon", "name", "desc", "historical_glossary", "visible", "requires_dlc_flag",
    "parameters", "piety_cost", "is_shown", "can_pick", "can_pick_as_personal_tenet",
    "divergence_multiplier", "character_modifier", "clergy_modifier", "county_modifier",
    "traits", "special_parameters", "personal_tenet_modifier", "personal_tenet_parameters",
}
SKIP_TENET_FIELDS = {}

HANDLED_GROUP_FIELDS = {"category", "main_rite", "divergence", "doctrine_lock",
                        "is_available_on_create"}
SKIP_GROUP_FIELDS = {}

HANDLED_CATEGORY_FIELDS = {"visible", "sort_order"}
SKIP_CATEGORY_FIELDS = {"gui_tags": "GUI sizing tags"}


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


def loc_name(key, *cands):
    for c in cands:
        raw = ck3.loc(c)
        if raw:
            return ck3.render_text(raw)
    return key.replace("_", " ")


def religion_name(r):
    return loc_name(r, r)


# --- piety cost: compile the script value -----------------------------------

NEGATORS = {"NOT", "NOR", "NAND"}


def compile_cond(blk):
    """Trigger block -> condition tree (implicit AND)."""
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return {"unknown": str(blk)}
    parts = []
    for k, _op, v in blk:
        if k is None:
            continue
        if k in ("rite_religion_tag", "religion_tag") and isinstance(v, str):
            parts.append({"religion": v})
        elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
            parts.append({"religion": v.removeprefix("religion:")})
        elif k == "religion" and isinstance(v, Block) and v.get("is_in_family") \
                and len(v.items()) == 1:
            parts.append({"family": v.get("is_in_family")})
        elif k == "faith" and isinstance(v, str) and v.startswith("faith:"):
            parts.append({"faith": v.removeprefix("faith:")})
        elif k in ("rite_has_doctrine", "has_doctrine") and isinstance(v, str):
            parts.append({"doctrine": v})
        elif k in ("rite_has_tenet", "has_tenet") and isinstance(v, str):
            parts.append({"tenet": v})
        elif k == "always" and isinstance(v, bool):
            parts.append({"const": v})
        elif k == "OR" and isinstance(v, Block):
            parts.append({"or": compile_cond(v).get("and", [compile_cond(v)])})
        elif k == "AND" and isinstance(v, Block):
            parts.append(compile_cond(v))
        elif k in ("NOT", "NOR") and isinstance(v, Block):
            inner = compile_cond(v)
            parts.append({"not": {"or": inner.get("and", [inner])}})
        elif k == "NAND" and isinstance(v, Block):
            parts.append({"not": compile_cond(v)})
        else:
            if isinstance(v, (Block, Tagged)):
                parts.append({"unknown": f"{k} {{…}}"})
            else:
                parts.append({"unknown": f"{k} = {v}"})
    if len(parts) == 1:
        return parts[0]
    return {"and": parts}


def cond_text(c):
    if "religion" in c:
        return religion_name(c["religion"])
    if "family" in c:
        return f"{loc_name(c['family'], c['family'])} family"
    if "faith" in c:
        return loc_name(c["faith"], c["faith"])
    if "doctrine" in c:
        return f"rite has {R.doctrine_name(c['doctrine'])}"
    if "tenet" in c:
        return f"rite has {R.tenet_name(c['tenet'])}"
    if "const" in c:
        return "always" if c["const"] else "never"
    if "or" in c:
        return " or ".join(cond_text(x) for x in c["or"])
    if "and" in c:
        return " and ".join(cond_text(x) for x in c["and"])
    if "not" in c:
        return f"not ({cond_text(c['not'])})"
    return f"[script: {c.get('unknown')}]"


def cond_unknowns(c, out):
    if "unknown" in c:
        out.append(c["unknown"])
    for k in ("or", "and"):
        for x in c.get(k, []):
            cond_unknowns(x, out)
    if "not" in c:
        cond_unknowns(c["not"], out)


ARITH = ("value", "add", "subtract", "multiply", "divide", "min", "max")


def compile_steps(blk, unknown):
    steps = []
    for k, _op, v in blk:
        if k is None:
            continue
        if k in ARITH:
            n, r = ck3.resolve_value(v)
            if n is None:
                unknown.append(f"{k} {r}")
            steps.append({"op": k, "value": n, "ref": v if isinstance(v, str) else None})
        elif k in ("round", "ceiling", "floor"):
            steps.append({"op": k})
        elif k in ("if", "else_if") and isinstance(v, Block):
            cond = compile_cond(v.get("limit"))
            cond_unknowns(cond, unknown)
            body = Block([(kk, o, vv) for kk, o, vv in v if kk != "limit"])
            steps.append({"op": k, "cond": cond, "then": compile_steps(body, unknown)})
        elif k == "else" and isinstance(v, Block):
            steps.append({"op": "else", "then": compile_steps(v, unknown)})
        else:
            unknown.append(k)
            steps.append({"op": "unknown", "text": k})
    return steps


def steps_text(steps, indent=""):
    lines = []
    for s in steps:
        op = s["op"]
        if op in ARITH:
            val = s["value"] if s["value"] is not None else s.get("ref")
            word = {"value": "", "add": "+", "subtract": "−", "multiply": "×",
                    "divide": "÷", "min": "at least ", "max": "at most "}[op]
            lines.append(f"{indent}{word}{fmt(val)}")
        elif op in ("round", "ceiling", "floor"):
            lines.append(f"{indent}{op}")
        elif op in ("if", "else_if"):
            sub = steps_text(s["then"])
            lines.append(f"{indent}{' '.join(sub)} if {cond_text(s['cond'])}")
        elif op == "else":
            sub = steps_text(s["then"])
            lines.append(f"{indent}{' '.join(sub)} otherwise")
        else:
            lines.append(f"{indent}[script: {s.get('text')}]")
    return lines


def fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def static_value(steps):
    """The number when the chain has no conditional VALUE step (multiplier
    branches like 'keep it ×0.5' are allowed and ignored); else None."""
    base = None
    for s in steps:
        if s["op"] == "value" and s["value"] is not None:
            base = s["value"]
        elif s["op"] in ("if", "else_if", "else"):
            if any(t["op"] == "value" for t in s["then"]):
                return None
        elif s["op"] in ("add", "subtract", "divide", "min", "max", "unknown"):
            return None
        elif s["op"] == "multiply" and base is not None and s["value"] is not None:
            base *= s["value"]
    return base


def piety_cost(pc):
    if pc is None:
        return None
    unknown = []
    if isinstance(pc, (int, float, str)):
        blk = Block([("value", "=", pc)])
    elif isinstance(pc, Block):
        blk = pc
    else:
        return None
    steps = compile_steps(blk, unknown)
    return {"steps": steps, "text": steps_text(steps), "static": static_value(steps),
            "unmodelled": sorted(set(unknown))}


# --- parameters -------------------------------------------------------------

_VALUE_SUB = re.compile(r"\$VALUE(\|[^$]*)?\$")


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def loc_with_value(cands, value):
    for c in cands:
        raw = ck3.loc(c)
        if raw:
            raw = raw.replace("$EFFECT_LIST_BULLET$", "• ")
            num = "" if isinstance(value, bool) else _num(value)
            return ck3.render_text(_VALUE_SUB.sub(str(num), raw))
    return None


def plain_params(pblk):
    """parameters = { a b } (legacy `a = yes` accepted) -> [{key, text}]."""
    out = []
    if not isinstance(pblk, Block):
        return out
    for pk, _op, pv in pblk:
        if pk is None:
            pk, pv = str(pv), True
        txt = loc_with_value([f"doctrine_parameter_{pk}"], pv)
        out.append({"key": pk, "value": pv, "text": txt})
    return out


HOSTILITY_KEYS = ("righteous", "astray", "hostile", "evil")


def hostility_name(level):
    return R.concept_name(f"faith_{level}") if level in HOSTILITY_KEYS else str(level)


def _hostility_line(template_key, level, **subs):
    raw = ck3.loc(template_key)
    if not raw:
        return None
    raw = raw.replace("$HOSTILITY_NAME|V$", hostility_name(level))
    for k, v in subs.items():
        raw = raw.replace(k, v)
    return ck3.render_text(raw)


def special_params(sblk):
    """special_parameters -> [{key, value, text}] (see _doctrine_types.info)."""
    out = []
    if not isinstance(sblk, Block):
        return out
    for k, _op, v in sblk:
        if k is None:
            continue
        if k == "hostility_levels" and isinstance(v, Block):
            for rel, _o, lvl in v:
                out.append({"key": f"hostility_levels.{rel}", "value": lvl,
                            "text": _hostility_line(f"hostility_override_{rel}", lvl)})
        elif k == "hostility_level_override" and isinstance(v, Block):
            for target, _o, lvl in v:
                is_tenet = target in R.tenet_blocks()
                tmpl = "hostility_override_with_tenet" if is_tenet else "hostility_override_with_doctrine"
                token = "[TenetType.GetBaseName|V]" if is_tenet else "[DoctrineType.GetBaseName|V]"
                out.append({"key": f"hostility_level_override.{target}", "value": lvl,
                            "text": _hostility_line(tmpl, lvl, **{token: R.doctrine_name(target)})})
        elif k == "same_hof_hostility_override":
            out.append({"key": k, "value": v,
                        "text": _hostility_line("hostility_override_same_hof", v)})
        elif k == "parameter_opinion_override" and isinstance(v, Block):
            for param, _o, val in v:
                out.append({"key": f"parameter_opinion_override.{param}", "value": val,
                            "text": loc_with_value(
                                [f"doctrine_parameter_{param}_opinion_active"], val)})
        elif k == "allowed_holding_types":
            for h in R.block_list(v):
                hn = loc_name(h, h)
                out.append({"key": f"allowed_holding_types.{h}", "value": True,
                            "text": loc_with_value([f"doctrine_parameter_allowed_holding_type_{h}"], True)
                            or None, "holding": hn})
        else:
            cands = [f"doctrine_parameter_{k}", f"doctrine_parameter_{k.removeprefix('bonus_')}"]
            if isinstance(v, bool):
                txt = loc_with_value(cands, v) if v else None
            else:
                txt = loc_with_value(cands, v)
            out.append({"key": k, "value": v, "text": txt})
    return out


# --- triggers ---------------------------------------------------------------

_REF = re.compile(r"^(doctrine|tenet):(\w+)$")


def collect_shown(trigger, out, negated=False):
    """is_shown / is_available_on_create -> religions, conditions, DLC."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        neg = negated or (k in NEGATORS)
        pre = "not " if neg else ""
        if k in ("religion_tag", "rite_religion_tag") and isinstance(v, str):
            out["religions"].append(pre + religion_name(v))
        elif k in ("has_doctrine", "rite_has_doctrine") and isinstance(v, str):
            out["conds"].append(f"{pre}has {R.doctrine_name(v)}")
        elif k in dlc_trigger_map() and v is True:
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
            out["religions"].append(pre + loc_name(fam, fam) + " family")
        elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
            out["religions"].append(pre + religion_name(v.removeprefix("religion:")))
        elif isinstance(v, (Block, Tagged)):
            collect_shown(v, out, neg)
        else:
            out["conds"].append(f"{pre}{k}".strip())


def collect_pick(trigger, res, negated=False):
    """can_pick -> incompatible/required doctrine & tenet keys, religion gates,
    leftover notes. custom_description `text` keys are trigger loc keys whose
    text is the UNMET-state phrasing, so they are not used as labels."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        if k is None:
            continue
        m = _REF.match(k)
        if m:
            (res["incompat"] if negated else res["requires"]).append(m.group(2))
        elif k in ("has_doctrine", "has_tenet", "rite_has_doctrine", "rite_has_tenet") \
                and isinstance(v, str):
            (res["incompat"] if negated else res["requiresCurrent"]).append(v)
        elif k == "religion" and isinstance(v, str) and v.startswith("religion:"):
            res["religions"].append(("not " if negated else "") +
                                    religion_name(v.removeprefix("religion:")))
        elif k == "religion" and isinstance(v, Block) and v.get("is_in_family"):
            fam = v.get("is_in_family")
            res["religions"].append(("not " if negated else "") + loc_name(fam, fam) + " family")
        elif k == "trigger_if" and isinstance(v, Block) and "is_ai" in str(v.get("limit")):
            res["notes"].append("extra restrictions when an AI picks")
        elif k == "this" and isinstance(v, str) and v.startswith("faith:"):
            f = v.removeprefix("faith:")
            res["notes"].append(f"{'not ' if negated else ''}faith is {loc_name(f, f)}")
        elif k.startswith("scope:actor"):
            res["notes"].append("conditions on the picking character")
        elif k in NEGATORS or k in ("custom_description", "custom_tooltip", "AND", "OR",
                                    "trigger_if", "trigger_else"):
            collect_pick(v, res, negated or (k in NEGATORS))
        elif k in ("text", "limit", "subject"):
            continue
        elif k == "always" and isinstance(v, bool):
            if v is negated:
                res["notes"].append("never pickable (script-assigned only)")
        elif isinstance(v, (Block, Tagged)):
            res["notes"].append(f"{'not ' if negated else ''}{k.replace('_', ' ')}")
        elif v is True:
            res["notes"].append(f"{'not ' if negated else ''}{k.replace('_', ' ')}")
        else:
            res["notes"].append(f"{'not ' if negated else ''}{k.replace('_', ' ')} {v}")


def pick_info(trigger):
    res = {"incompat": [], "requires": [], "requiresCurrent": [], "religions": [], "notes": []}
    collect_pick(trigger, res)
    return {
        "incompatibleWith": sorted(set(res["incompat"])),
        "requiresDoctrines": sorted(set(res["requires"])),
        "requiresCurrent": sorted(set(res["requiresCurrent"])),
        "pickReligions": list(dict.fromkeys(res["religions"])),
        "pickNotes": list(dict.fromkeys(res["notes"])),
    }


# --- modifiers / traits -----------------------------------------------------

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


def trait_entries(traits, field):
    v = traits.get(field) if isinstance(traits, Block) else None
    out = []
    if not isinstance(v, Block):
        return out
    for k, _op, val in v:
        if k is None:
            if not isinstance(val, str):
                continue
            key, scale, weight = val, 1, 1
        else:
            key = k
            if isinstance(val, Block):
                scale, weight = val.get("scale", 1), val.get("weight", 1)
            else:
                scale, weight = (val if isinstance(val, (int, float)) else 1), 1
        out.append({"key": key, "name": loc_name(key, f"trait_{key}", key),
                    "scale": scale, "weight": weight})
    return out


def icon_of(blk, key):
    """Plain icon string, or the triggered list's untriggered/first reference."""
    ic = blk.get("icon")
    if isinstance(ic, str):
        return ic.removesuffix(".dds")
    refs = []
    for v in blk.get_all("icon"):
        if isinstance(v, Block):
            r = v.get("reference")
            if r:
                refs.append((v.get("trigger") is None, r))
    if refs:
        refs.sort(key=lambda x: not x[0])
        return str(refs[0][1]).removesuffix(".dds")
    return key


_GLOSSARY = re.compile(r"\[Glossary\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)\]")


def historical_glossary(blk):
    """historical_glossary -> [{term, text}] from `[Glossary('Term','key')]`
    loc entries (every variant: they differ by liturgical language)."""
    keys = []
    R._desc_keys(blk.get("historical_glossary"), keys)
    out = []
    for k in keys:
        raw = ck3.loc(k) or ""
        for term, dkey in _GLOSSARY.findall(raw):
            text = ck3.loc(dkey)
            entry = {"term": ck3.render_text(term),
                     "text": ck3.render_text(text) if text else None}
            if entry not in out:
                out.append(entry)
    return out


# --- records ----------------------------------------------------------------

def common_record(key, blk, path, unhandled, handled, skip):
    for k in blk.keys():
        if k not in handled and k not in skip:
            unhandled[k] += 1
    name, name_variants = R.dynamic_text(blk, "name", f"{key}_name")
    desc, desc_variants = R.dynamic_text(blk, "desc", f"{key}_desc")
    glossary = historical_glossary(blk)
    shown = {"religions": [], "conds": [], "dlc": None}
    collect_shown(blk.get("is_shown"), shown)
    traits = blk.get("traits")
    dlc, _features = ck3.dlc_tag(path, blk)
    return {
        "id": key,
        "name": name or key.replace("_", " ").title(),
        "nameVariants": name_variants,
        "desc": desc,
        "descVariants": desc_variants,
        "glossary": glossary,
        "visible": blk.get("visible", True) is not False,
        "pietyCost": piety_cost(blk.get("piety_cost")),
        "parameters": plain_params(blk.get("parameters")),
        "specialParameters": special_params(blk.get("special_parameters")),
        "characterModifier": modifier_lines(blk.get("character_modifier")),
        "clergyModifier": modifier_lines(blk.get("clergy_modifier")),
        "virtues": trait_entries(traits, "virtues"),
        "sins": trait_entries(traits, "sins"),
        "shownForReligions": shown["religions"],
        "shownConditions": shown["conds"],
        **pick_info(blk.get("can_pick")),
        "icon": icon_of(blk, key),
        "dlc": shown["dlc"] or dlc,
        "sourceFile": path.name,
    }


def main():
    unhandled = {"doctrine": Counter(), "tenet": Counter(), "group": Counter(),
                 "category": Counter()}

    categories = []
    for _p, ckey, blk in ck3.parse_dir(R.RELIGION / "doctrine_category_types"):
        for k in blk.keys():
            if k not in HANDLED_CATEGORY_FIELDS and k not in SKIP_CATEGORY_FIELDS:
                unhandled["category"][k] += 1
        categories.append({
            "id": ckey,
            "name": loc_name(ckey, f"doctrine_category_{ckey}"),
            "sortOrder": blk.get("sort_order", 0),
            "visible": blk.get("visible", True) is not False,
        })
    categories.sort(key=lambda c: -c["sortOrder"])  # higher appears earlier
    cat_name = {c["id"]: c["name"] for c in categories}

    out = []
    for path, key, blk in ck3.parse_dir(R.RELIGION / "doctrine_types"):
        if not isinstance(blk, Block):
            continue
        rec = common_record(key, blk, path, unhandled["doctrine"],
                            HANDLED_DOCTRINE_FIELDS, SKIP_DOCTRINE_FIELDS)
        rec.update({
            "isTenet": False,
            "group": blk.get("doctrine_group_type"),
            "index": blk.get("index", 0),
            "divergence": blk.get("divergence", 0),
        })
        out.append(rec)

    for path, key, blk in ck3.parse_dir(R.RELIGION / "tenet_types"):
        if not isinstance(blk, Block):
            continue
        rec = common_record(key, blk, path, unhandled["tenet"],
                            HANDLED_TENET_FIELDS, SKIP_TENET_FIELDS)
        flag = blk.get("requires_dlc_flag")
        personal = {"religions": [], "conds": [], "dlc": None}
        rec.update({
            "isTenet": True,
            "group": None,
            "requiresDlc": ck3.FEATURE_TO_DLC.get(flag, flag) if flag else None,
            "divergenceMultiplier": blk.get("divergence_multiplier", 1),
            "countyModifier": modifier_lines(blk.get("county_modifier")),
            "personalModifier": modifier_lines(blk.get("personal_tenet_modifier")),
            "personalParameters": plain_params(blk.get("personal_tenet_parameters")),
            "personalPick": pick_info(blk.get("can_pick_as_personal_tenet")),
        })
        rec["dlc"] = rec["dlc"] or rec["requiresDlc"]
        out.append(rec)

    order = {r["id"]: i for i, r in enumerate(out)}
    groups = []
    for _p, gkey, blk in ck3.parse_dir(R.RELIGION / "doctrine_group_types"):
        for k in blk.keys():
            if k not in HANDLED_GROUP_FIELDS and k not in SKIP_GROUP_FIELDS:
                unhandled["group"][k] += 1
        members = sorted((r for r in out if r["group"] == gkey),
                         key=lambda r: (r["index"], order[r["id"]]))
        avail = {"religions": [], "conds": [], "dlc": None}
        collect_shown(blk.get("is_available_on_create"), avail)
        cat = blk.get("category")
        groups.append({
            "id": gkey,
            "name": loc_name(gkey, f"{gkey}_name"),
            "category": cat,
            "categoryName": cat_name.get(cat, str(cat)),
            "divergence": blk.get("divergence"),
            "doctrineLock": blk.get("doctrine_lock", "none"),
            "mainRiteOnly": bool(blk.get("main_rite", False)),
            "doctrines": [r["id"] for r in members],
            "availability": (avail["religions"] + avail["conds"]) or None,
            "dlc": avail["dlc"],
        })

    group_ids = {g["id"] for g in groups}
    orphans = [r["id"] for r in out if not r["isTenet"] and r["group"] not in group_ids]

    nrite = {k: R.define("NRite", k) for k in (
        "RITE_CREATION_FERVOR_DISCOUNT_PER_MISSING_FERVOR", "RITE_CREATION_FERVOR_DISCOUNT_MAX",
        "RITE_CREATION_DIVERGENCE_FAITH_THRESHOLD", "RITE_CREATION_PIETY_COST",
        "RITE_DIVERGENCE_HERETICAL_THRESHOLD", "RITE_DIVERGENCE_HOSTILITY_THRESHOLD",
        "TENET_STATUS_DIVERGENCE")}
    defines = {
        **nrite,
        "FAITH_CORE_TENETS_CAP": R.define("NReligion", "FAITH_CORE_TENETS_CAP"),
        "MAX_VIRTUES_SINS": R.define("NFaith", "MAX_VIRTUES_SINS"),
    }
    concepts = {k: {"name": R.concept_name(k), "desc": R.concept(k)}
                for k in ("tenet", "tenet_status", "rite_divergence")}

    out.sort(key=lambda r: (not r["isTenet"], r["group"] or "", r.get("index", 0), r["id"]))
    ck3.write_json("doctrines.json", {"categories": categories, "groups": groups,
                                      "doctrines": out, "defines": defines,
                                      "concepts": concepts})
    n_t = sum(1 for r in out if r["isTenet"])
    print(f"  ({len(categories)} categories, {len(groups)} groups, "
          f"{len(out) - n_t} doctrines, {n_t} tenets)")

    for label, c in unhandled.items():
        if c:
            print(f"⚠ unhandled {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    if orphans:
        print(f"⚠ {len(orphans)} doctrines name an unknown group: {orphans[:10]}")
    unnamed = [r["id"] for r in out if r["name"] == r["id"].replace("_", " ").title()]
    if unnamed:
        print(f"⚠ {len(unnamed)} entries without localized names: {unnamed[:10]}")
    unmod = sum(1 for r in out if r["pietyCost"] and r["pietyCost"]["unmodelled"])
    print(f"  ({unmod} piety costs contain script conditions the calculator cannot evaluate)")
    for kind in ("parameters", "specialParameters"):
        n = sum(1 for r in out for p in r[kind] if p["text"] is None)
        print(f"  ({n} {kind} without loc text — shown as raw key: value)")


if __name__ == "__main__":
    main()
