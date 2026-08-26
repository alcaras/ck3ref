#!/usr/bin/env python3
"""Build src/data/traditions.json from common/culture/traditions/.

Schema: common/culture/_cultural_traits.info + traditions/_traditions.info.
Every field present in the data is either emitted, consciously skipped
(SKIP_FIELDS), or reported unhandled — audit.py's contract.

Cost note: every real tradition prices in prestige through the same canonical
script_value chain (add base + conditional penalty ifs + replacement multiply).
The base script values (tradition_base_cost=2000 etc.) each carry a runtime
Kurultai-influence discount for nomad cultures (Khans of the Steppe); we emit
the static base and a single structured note instead of collapsing or hiding
the conditional — the full rule set is rendered per tradition.
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
    "ai_will_do": "AI divergence/hybridization pick weighting, not player-facing",
    "can_pick_for_hybridization": "hybridization-only variant of can_pick (AI/flow plumbing, mirrors can_pick)",
}

HANDLED_FIELDS = {
    "category", "layers", "cost", "parameters", "character_modifier",
    "province_modifier", "county_modifier", "culture_modifier",
    "doctrine_character_modifier", "can_pick", "is_shown",
    # per _cultural_traits.info these can appear; none do today but honor them
    "name", "desc", "icon",
}

# The four cost script values every tradition composes from. Each carries the
# same runtime conditional (nomad Kurultai influence reduces it by 1%/point);
# emitted once as costNote rather than duplicated into every rule list.
KNOWN_COST_VALUES = {
    "tradition_base_cost": 2000,
    "tradition_double_base_cost": 4000,
    "tradition_incompatible_ethos_penalty": 2000,
    "tradition_unfulfilled_criteria_penalty": 3000,
}
COST_NOTE = ("Nomad cultures with a Kurultai pay less: every point of Kurultai "
             "influence reduces base costs and penalties by 1% (Khans of the Steppe).")

NEGATORS = {"NOT", "NOR", "NAND"}
_DLC_TRIGGER = re.compile(r"^has_([a-z0-9]+)_dlc_trigger$")

# Scripted-trigger macros seen in can_pick, phrased for display. Fallback is
# the prettified key, so new triggers degrade visibly rather than vanish.
TRIGGER_LABELS = {
    "culture_not_pacifistic_trigger": "Culture is not pacifistic",
    "culture_not_warlike_trigger": "Culture is not warlike",
    "culture_in_winter_geographical_region_trigger": "Culture is in a wintery region",
    "culture_in_non_sedentary_geographical_region_trigger": "Culture is in a steppe/desert region",
}


def resolve_amount(v):
    """Cost component -> number where statically known, else None."""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        if v in KNOWN_COST_VALUES:
            return KNOWN_COST_VALUES[v]
        n, _rules = ck3.resolve_value(v)
        return n
    return None


def extract_cost(cost_blk):
    """Canonical tradition cost -> {currency: {base, rules[]}}.

    rules: [{when, op, amount}] — `when` is the game's own desc loc for the
    condition, rendered; amounts left None render as 'varies'.
    """
    if cost_blk is None:
        return None
    out = {}
    for cur, _op, v in cost_blk:
        if cur is None:
            continue
        if isinstance(v, (int, float)):
            out[cur] = {"base": v, "rules": []}
            continue
        if not isinstance(v, Block):
            out[cur] = {"base": resolve_amount(v), "rules": []}
            continue
        base = None
        rules = []
        for k, _o, item in v:
            if k == "add":
                amt = resolve_amount(item.get("value") if isinstance(item, Block) else item)
                if base is None:
                    base = amt
                else:
                    rules.append({"when": None, "op": "add", "amount": amt})
            elif k == "multiply":
                if item == "tradition_replacement_cost_if_relevant":
                    rules.append({"when": "Replacing an existing tradition",
                                  "op": "multiply", "amount": 1.5})
                else:
                    amt = resolve_amount(item.get("value") if isinstance(item, Block) else item)
                    rules.append({"when": None, "op": "multiply", "amount": amt})
            elif k == "if" and isinstance(item, Block):
                when = None
                op = None
                amt = None
                for ik, _io, iv in item:
                    if ik in ("add", "multiply", "subtract"):
                        op = ik
                        if isinstance(iv, Block):
                            amt = resolve_amount(iv.get("value"))
                            d = iv.get("desc")
                            if d:
                                when = _render(ck3.loc(d) or d)
                        else:
                            amt = resolve_amount(iv)
                if when is None:
                    when = describe_limit(item.get("limit"))
                rules.append({"when": when, "op": op, "amount": amt})
        out[cur] = {"base": base, "rules": rules}
    return out


def describe_limit(limit):
    """Cost-rule limits whose desc the game left out: name the has_trait
    checks (the only shape in the data); anything else falls back to the
    library's honest shallow dump."""
    traits = []

    def walk(b, depth=0):
        if isinstance(b, Tagged):
            b = b.block
        if not isinstance(b, Block) or depth > 4:
            return
        for k, _o, v in b:
            if k == "has_trait" and isinstance(v, str):
                traits.append(_render(ck3.loc(f"trait_{v}") or ck3.loc(v) or v.replace("_", " ").title()))
            elif isinstance(v, (Block, Tagged)):
                walk(v, depth + 1)

    walk(limit)
    if traits:
        return "Character has the " + " or ".join(traits) + " trait"
    return ck3._describe_trigger(limit)


def trigger_label(key):
    if key in TRIGGER_LABELS:
        return TRIGGER_LABELS[key]
    return key.removesuffix("_trigger").replace("_", " ").capitalize()


def collect_reqs(trigger, reqs, negated=False, depth=0):
    """Shallow requirement extraction (the build_maa pattern).

    custom_tooltip/custom_description texts are the game's own *unmet*-state
    strings, so they are emitted as kind=text and the page labels the list
    honestly; their inner trigger blocks are covered by the text and skipped.
    """
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
            continue  # inner triggers are what the text describes
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
            dlc = ck3.FEATURE_TO_DLC.get(v, v)
            reqs.append({"kind": "dlc", "key": v, "text": dlc, "negated": negated})
        elif isinstance(k, str) and _DLC_TRIGGER.match(k):
            prefix = _DLC_TRIGGER.match(k).group(1)
            dlc = ck3.PREFIX_TO_DLC.get(prefix, prefix)
            reqs.append({"kind": "dlc", "key": k, "text": dlc, "negated": negated})
        elif k == "always" and isinstance(v, bool):
            if v is not negated:
                continue  # always-true: no requirement
            reqs.append({"kind": "never", "text": "never (special grant only)", "negated": False})
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            reqs.append({"kind": "trigger", "key": k, "text": trigger_label(k), "negated": negated})
        elif isinstance(k, str) and k.endswith("_trigger") and isinstance(v, (Block, Tagged)):
            # scripted-trigger macro invoked with arguments; the args are macro
            # plumbing, the trigger name is the requirement
            reqs.append({"kind": "trigger", "key": k, "text": trigger_label(k),
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


def main():
    entries = ck3.parse_dir(ck3.COMMON / "culture" / "traditions")
    unhandled = Counter()
    out = []
    skipped_debug = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        if path.name == "00_debug_traditions.txt":
            skipped_debug.append(key)  # modder parameter containers, never shown
            continue
        dlc, features = ck3.dlc_tag(path, blk)

        name_key = blk.get("name") or f"{key}_name"
        desc_key = blk.get("desc") or f"{key}_desc"
        name = ck3.loc(name_key)
        desc = ck3.loc(desc_key)

        params = []
        pb = blk.get("parameters")
        if isinstance(pb, Block):
            for pk, _o, pv in pb:
                if pk is None:
                    continue
                lk = pk if ck3.loc(f"culture_parameter_{pk}") is None else f"culture_parameter_{pk}"
                txt = culture_text.render(lk, pv)
                params.append({
                    "key": pk,
                    "value": pv,
                    "text": txt if txt else pk.replace("_", " ").capitalize(),
                    "hasLoc": bool(txt),
                })

        mods = {}
        for field, label in (("character_modifier", "Characters"),
                             ("province_modifier", "Provinces"),
                             ("county_modifier", "Counties"),
                             ("culture_modifier", "Culture")):
            lines = modifier_lines(blk.get(field))
            if lines:
                mods[label] = lines
        for dcm in blk.get_all("doctrine_character_modifier"):
            if isinstance(dcm, Block):
                doctrine = dcm.get("doctrine")
                dname = _render(ck3.loc(doctrine) or ck3.loc(f"{doctrine}_name") or str(doctrine))
                lines = [culture_text.render_modifier(k, v) for k, _o, v in dcm
                         if k not in (None, "doctrine")]
                if lines:
                    mods[f"Characters ({dname} faiths)"] = lines

        reqs = []
        collect_reqs(blk.get("can_pick"), reqs)
        shown = []
        collect_reqs(blk.get("is_shown"), shown)

        layers = {}
        lb = blk.get("layers")
        if isinstance(lb, Block):
            for idx, _o, v in lb:
                if idx is not None:
                    layers[str(idx)] = str(v).removesuffix(".dds")
        icon = blk.get("icon") or layers.get("4")
        icon = str(icon).removesuffix(".dds") if icon else None

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        out.append({
            "id": key,
            "name": _render(name) if name else None,
            "desc": _render(desc) if desc else None,
            "category": blk.get("category"),
            "categoryName": _render(ck3.loc(f"tradition_group_{blk.get('category')}") or str(blk.get("category"))),
            "cost": extract_cost(blk.get("cost")),
            "parameters": params,
            "modifiers": mods,
            "requirements": dedupe(reqs),
            "shownWhen": dedupe(shown),
            "layers": layers,
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (r["category"] or "", r["id"]))
    ck3.write_json("traditions.json", {"costNote": COST_NOTE, "traditions": out})
    print(f"  ({len(out)} traditions; debug container entries skipped: {skipped_debug})")

    if unhandled:
        print("⚠ unhandled tradition fields (add to HANDLED or SKIP):")
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
