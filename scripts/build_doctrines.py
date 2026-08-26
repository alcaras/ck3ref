#!/usr/bin/env python3
"""Build src/data/doctrines.json from common/religion/doctrine_types/ and
doctrine_group_types/.

Emits {groups, doctrines}. Tenets are the doctrines in the 3-pick
doctrine_core_tenets group. Piety costs stay honest: the value/if/else chains
in the data become {values: [{when, value}], mults: [{when, factor}]} rule
structures; only the unconditional single-value case collapses to a number.

Schema docs: _doctrine_types.info, _doctrine_group_types.info.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

RELIGION = ck3.COMMON / "religion"

SKIP_FIELDS = {
    # (none yet)
}

HANDLED_FIELDS = {
    "icon", "name", "desc", "visible", "parameters", "piety_cost", "is_shown",
    "can_pick", "character_modifier", "clergy_modifier", "traits",
}

SKIP_GROUP_FIELDS = {}
HANDLED_GROUP_FIELDS = {"category", "number_of_picks", "doctrine_types",
                        "is_available_on_create"}

CATEGORY_NAMES = {
    "main_group": "Main Tenets & Doctrines",
    "marriage": "Marriage",
    "crimes": "Crimes",
    "clergy": "Clergy",
    "core_tenets": "Tenets",
    "special": "Special",
    "not_creatable": "Hostility & Script-only",
}


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
    if not isinstance(v, Block):
        return
    for k, _op, val in v:
        if k == "desc" and isinstance(val, str):
            out.append(val)
        elif isinstance(val, (Block, Tagged)):
            _desc_keys(val, out)


def dynamic_names(blk, field, default_key):
    """(primary, variants) for a doctrine's name/desc, honoring dynamic blocks."""
    keys = []
    _desc_keys(blk.get(field), keys)
    if default_key not in keys:
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

def _religion_names(limit):
    names = []
    def walk(b):
        for k, _op, v in b:
            if k == "religion_tag" and isinstance(v, str):
                names.append(ck3.render_text(ck3.loc(v) or v))
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


def describe_limit(limit, self_key):
    """A piety_cost limit -> short human condition ('' if unrecognized)."""
    if not isinstance(limit, Block):
        return None
    keys = limit.keys()
    if keys == ["has_doctrine"]:
        d = limit.get("has_doctrine")
        if d == self_key:
            return "keeping this doctrine"
        return f"had {doctrine_display_name(d)}"
    rels = _religion_names(limit)
    if rels and all(k in ("religion_tag", "religion", "OR", "AND") for k in keys):
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
            when = "otherwise" if k == "else" else describe_limit(v.get("limit"), self_key)
            iv, im = v.get("value"), v.get("multiply")
            if iv is not None:
                n, r = ck3.resolve_value(iv)
                values.append({"when": when, "value": n if n is not None else str(r)})
            if im is not None:
                n, r = ck3.resolve_value(im)
                mults.append({"when": when, "factor": n if n is not None else str(r)})
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

HOSTILITY_PARAMS = {
    "hostility_same_religion": "Faiths of the same religion",
    "hostility_same_family": "Faiths of the same family",
    "hostility_others": "Faiths of other families",
}


def _hostility_level_name(n):
    key = ("faith_righteous", "faith_astray", "faith_hostile", "faith_evil")[
        max(0, min(3, int(n)))]
    raw = ck3.loc(f"game_concept_{key}")
    return ck3.render_text(raw) if raw else key.removeprefix("faith_").title()


def param_text(key, value):
    if key in HOSTILITY_PARAMS and isinstance(value, (int, float)):
        return f"{HOSTILITY_PARAMS[key]} are considered {_hostility_level_name(value)}"
    if key == "same_hof_hostility_override" and isinstance(value, (int, float)):
        return ("Faiths sharing their Head of Faith are considered "
                f"{_hostility_level_name(value)}")
    m = re.match(r"^hostility_override_(\w+)$", key)
    if m and isinstance(value, (int, float)):
        return (f"Faiths with {doctrine_display_name(m.group(1))} are considered "
                f"{_hostility_level_name(value)}")
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
            num = value if not isinstance(value, bool) else ""
            if isinstance(num, float) and num.is_integer():
                num = int(num)
            return ck3.render_text(_VALUE_SUB.sub(str(num), raw))
    return None


# --- triggers ---------------------------------------------------------------

NEGATORS = {"NOT", "NOR", "NAND"}
_DOCTRINE_REF = re.compile(r"^doctrine:(\w+)$")


def collect_shown(trigger, out, negated=False):
    """is_shown -> ([condition strings], dlc name or None)."""
    if isinstance(trigger, Tagged):
        trigger = trigger.block
    if not isinstance(trigger, Block):
        return
    for k, _op, v in trigger:
        neg = negated or (k in NEGATORS)
        pre = "not " if neg else ""
        if k == "religion_tag" and isinstance(v, str):
            out["religions"].append(pre + ck3.render_text(ck3.loc(v) or v))
        elif k == "has_doctrine" and isinstance(v, str):
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
        return lines, None
    label = None
    for k, _op, v in blk:
        if k is None:
            continue
        if k == "name":
            raw = ck3.loc(str(v))
            label = ck3.render_text(raw) if raw else None
            continue
        if isinstance(v, str):
            n, _r = ck3.resolve_value(v)
            v = n if n is not None else v
        if isinstance(v, (Block, Tagged)):
            lines.append(f"{ck3.modifier_name(k)}: (conditional)")
        else:
            lines.append(ck3.render_modifier(k, v))
    return lines, label


def main():
    unhandled, unhandled_grp = Counter(), Counter()

    groups = []
    tenet_group_doctrines = set()
    for _p, gkey, blk in ck3.parse_dir(RELIGION / "doctrine_group_types"):
        for k in blk.keys():
            if k not in HANDLED_GROUP_FIELDS and k not in SKIP_GROUP_FIELDS:
                unhandled_grp[k] += 1
        dts = blk.get("doctrine_types")
        doctrine_keys = dts.values() if isinstance(dts, Block) else []
        if gkey == "doctrine_core_tenets":
            tenet_group_doctrines = set(doctrine_keys)
        avail = {"religions": [], "conds": [], "dlc": None}
        collect_shown(blk.get("is_available_on_create"), avail)
        groups.append({
            "id": gkey,
            "name": ck3.render_text(ck3.loc(f"{gkey}_name") or gkey.replace("_", " ").title()),
            "category": blk.get("category"),
            "categoryName": CATEGORY_NAMES.get(blk.get("category"),
                                               str(blk.get("category")).replace("_", " ").title()),
            "picks": blk.get("number_of_picks", 1),
            "doctrines": doctrine_keys,
            "availability": (avail["religions"] + avail["conds"]) or None,
            "dlc": avail["dlc"],
        })
    group_of = {d: g["id"] for g in groups for d in g["doctrines"]}

    out = []
    for path, key, blk in ck3.parse_dir(RELIGION / "doctrine_types"):
        if isinstance(blk, Tagged):
            continue
        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        name, name_variants = dynamic_names(blk, "name", f"{key}_name")
        desc, desc_variants = dynamic_names(blk, "desc", f"{key}_desc")

        shown = {"religions": [], "conds": [], "dlc": None}
        collect_shown(blk.get("is_shown"), shown)
        incompat, requires, pick_notes = [], [], []
        collect_pick(blk.get("can_pick"), incompat, requires, pick_notes)
        pick_notes = list(dict.fromkeys(pick_notes))

        params = []
        pblk = blk.get("parameters")
        if isinstance(pblk, Block):
            for pk, _op, pv in pblk:
                if pk is None:
                    pk, pv = str(pv), True  # bare parameter name means "set"
                params.append({"key": pk, "value": pv, "text": param_text(pk, pv)})

        char_mods, _ = modifier_lines(blk.get("character_modifier"))
        clergy_mods, _ = modifier_lines(blk.get("clergy_modifier"))

        traits = blk.get("traits")
        def tlist(field):
            v = traits.get(field) if isinstance(traits, Block) else None
            out = []
            if isinstance(v, Block):
                keys = [x for x in v.values() if isinstance(x, str)] + \
                       [k for k, _op, _v in v if k is not None]
                for t in keys:
                    raw = ck3.loc(f"trait_{t}") or ck3.loc(t)
                    out.append(ck3.render_text(raw) if raw else t.replace("_", " ").title())
            return out

        gkey = group_of.get(key)
        dlc, _features = ck3.dlc_tag(path, blk)
        rec = {
            "id": key,
            "name": name or key.replace("_", " ").title(),
            "nameVariants": name_variants,
            "desc": desc,
            "descVariants": desc_variants,
            "group": gkey,
            "isTenet": key in tenet_group_doctrines,
            "visible": blk.get("visible", True) is not False,
            "pietyCost": piety_cost(blk.get("piety_cost"), key),
            "parameters": params,
            "characterModifier": char_mods,
            "clergyModifier": clergy_mods,
            "virtues": tlist("virtues"),
            "sins": tlist("sins"),
            "shownForReligions": shown["religions"],
            "shownConditions": shown["conds"],
            "incompatibleWith": sorted(set(incompat)),
            "requiresDoctrines": sorted(set(requires)),
            "pickNotes": pick_notes,
            "icon": str(blk.get("icon") or key).removesuffix(".dds"),
            "dlc": shown["dlc"] or dlc,
            "sourceFile": path.name,
        }
        out.append(rec)

    out.sort(key=lambda r: (r["group"] or "zz", r["id"]))
    ck3.write_json("doctrines.json", {"groups": groups, "doctrines": out})
    print(f"  ({len(groups)} groups, {len(out)} doctrines, "
          f"{sum(1 for r in out if r['isTenet'])} tenets)")

    for label, c in (("doctrine", unhandled), ("group", unhandled_grp)):
        if c:
            print(f"⚠ unhandled {label} fields (add to HANDLED or SKIP):")
            for k, n in c.most_common():
                print(f"    {k} ×{n}")
    unnamed = [r["id"] for r in out if not r["name"]]
    if unnamed:
        print(f"⚠ {len(unnamed)} doctrines without localized names: {unnamed[:10]}")
    unloc_params = sum(1 for r in out for p in r["parameters"] if p["text"] is None)
    print(f"  ({unloc_params} parameter values without loc text — shown as raw key: value)")


if __name__ == "__main__":
    main()
