#!/usr/bin/env python3
"""Build src/data/pillars.json from common/culture/pillars/.

Schema: common/culture/_cultural_traits.info + pillars/_pillars.info.
Types: ethos, heritage, language, martial_custom, head_determination.
Name loc is <key>_name (bare key fallback); desc falls back to
<type>_generic_label_desc per the schema doc. Language colors resolve
through common/named_colors.
"""

import colorsys
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
    "ai_will_do": "AI divergence pick weighting, not player-facing",
    "is_shown": "uniform UI-visibility macros (language/heritage_is_shown_trigger), no reference value",
    "audio_parameter": "sound-engine hook on heritages",
}

HANDLED_FIELDS = {
    "type", "character_modifier", "province_modifier", "county_modifier",
    "culture_modifier", "doctrine_character_modifier", "parameters", "desc",
    "name", "icon", "color", "can_pick", "head_determination_type",
}

TYPE_ORDER = ["ethos", "heritage", "language", "martial_custom", "head_determination"]
TYPE_LABELS = {
    "ethos": "Ethos", "heritage": "Heritage", "language": "Language",
    "martial_custom": "Martial Custom", "head_determination": "Head Determination",
}

NEGATORS = {"NOT", "NOR", "NAND"}

_named_colors: dict | None = None


def named_colors():
    """Flatten common/named_colors into name -> [r, g, b] (0-255)."""
    global _named_colors
    if _named_colors is None:
        _named_colors = {}

        def walk(blk):
            pending = None  # a few colors are written `name { r g b }` with no `=`
            for k, _op, v in blk:
                if k is None:
                    if isinstance(v, str):
                        pending = v
                    elif pending and isinstance(v, Block):
                        rgb = to_rgb(Tagged("rgb", v))
                        if rgb:
                            _named_colors[pending] = rgb
                        pending = None
                    continue
                pending = None
                if isinstance(v, Tagged):
                    rgb = to_rgb(v)
                    if rgb:
                        _named_colors[k] = rgb
                elif isinstance(v, Block):
                    vals = v.values()
                    if len(vals) == 3 and all(isinstance(x, (int, float)) for x in vals):
                        _named_colors[k] = to_rgb(Tagged("rgb", v))
                    else:
                        walk(v)

        for p in sorted((ck3.COMMON / "named_colors").glob("*.txt")):
            walk(ck3.parse_file(p))
    return _named_colors


def to_rgb(v):
    """A color value (Tagged rgb/hsv or 3-number block) -> [r, g, b] 0-255."""
    if isinstance(v, Tagged):
        vals = v.block.values()
        if len(vals) != 3 or not all(isinstance(x, (int, float)) for x in vals):
            return None
        if v.tag == "hsv":
            r, g, b = colorsys.hsv_to_rgb(*vals)
            return [round(r * 255), round(g * 255), round(b * 255)]
        if v.tag == "hsv360":
            r, g, b = colorsys.hsv_to_rgb(vals[0] / 360, vals[1] / 100, vals[2] / 100)
            return [round(r * 255), round(g * 255), round(b * 255)]
        # rgb: floats are 0-1, ints are 0-255
        if all(isinstance(x, float) or x <= 1 for x in vals):
            return [round(x * 255) for x in vals]
        return [round(x) for x in vals]
    if isinstance(v, str):
        return named_colors().get(v)
    if isinstance(v, Block):
        return to_rgb(Tagged("rgb", v))
    return None


def collect_reqs(trigger, reqs, negated=False, depth=0):
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
        elif isinstance(k, str) and k.endswith("_trigger") and v is True:
            reqs.append({"kind": "trigger", "key": k,
                         "text": k.removesuffix("_trigger").replace("_", " ").capitalize(),
                         "negated": negated})
        elif isinstance(k, str) and k.endswith("_trigger") and isinstance(v, (Block, Tagged)):
            # scripted-trigger macro invoked with arguments; the args are macro
            # plumbing, the trigger name is the requirement
            reqs.append({"kind": "trigger", "key": k, "text": k.removesuffix("_trigger").replace("_", " ").capitalize(),
                         "negated": negated})
        elif isinstance(v, (Block, Tagged)):
            collect_reqs(v, reqs, negated or (k in NEGATORS), depth + 1)


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
    entries = ck3.parse_dir(ck3.COMMON / "culture" / "pillars")
    unhandled = Counter()
    out = []
    for path, key, blk in entries:
        if isinstance(blk, Tagged):
            continue
        dlc, features = ck3.dlc_tag(path, blk)
        ptype = blk.get("type")

        name_key = blk.get("name") or f"{key}_name"
        name = ck3.loc(name_key) or ck3.loc(key)
        desc_key = blk.get("desc") or f"{key}_desc"
        desc = ck3.loc(desc_key) or ck3.loc(f"{ptype}_generic_label_desc")

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

        icon = blk.get("icon") or key
        icon = str(icon).removesuffix(".dds")

        for k in blk.keys():
            if k not in HANDLED_FIELDS and k not in SKIP_FIELDS:
                unhandled[k] += 1

        out.append({
            "id": key,
            "name": _render(name) if name else None,
            "desc": _render(desc) if desc else None,
            "type": ptype,
            "typeName": TYPE_LABELS.get(ptype, str(ptype).replace("_", " ").title()),
            "color": to_rgb(blk.get("color")) if blk.has("color") else None,
            "headDeterminationType": blk.get("head_determination_type"),
            "parameters": params,
            "modifiers": mods,
            "requirements": reqs,
            "icon": icon,
            "dlc": dlc,
            "features": features,
            "sourceFile": path.name,
        })

    out.sort(key=lambda r: (TYPE_ORDER.index(r["type"]) if r["type"] in TYPE_ORDER else 99,
                            r["name"] or r["id"]))
    ck3.write_json("pillars.json", out)

    if unhandled:
        print("⚠ unhandled pillar fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    missing_names = [r["id"] for r in out if not r["name"]]
    if missing_names:
        print(f"⚠ {len(missing_names)} entries without localized names: {missing_names[:10]}")
    no_color = [r["id"] for r in out if r["type"] == "language" and not r["color"]]
    if no_color:
        print(f"⚠ {len(no_color)} languages without resolvable color: {no_color[:10]}")
    noloc_params = sorted({p["key"] for r in out for p in r["parameters"] if not p["hasLoc"]})
    if noloc_params:
        print(f"⚠ {len(noloc_params)} parameters without loc (prettified): {noloc_params}")


if __name__ == "__main__":
    main()
