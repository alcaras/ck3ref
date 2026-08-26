#!/usr/bin/env python3
"""Build src/data/artifacts.json from common/artifacts/ plus the
create_artifact instantiations in common/scripted_effects/.

Data-model reality (differs from a first reading of the schema docs):
templates carry wield/benefit TRIGGERS and the FALLBACK modifier applied when
can_benefit fails — never the artifact's real modifier set. The real modifiers
of named artifacts live on `create_artifact` blocks inside scripted effects
(`modifier = <key>` resolved against common/modifiers/). Features carry NO
modifiers either — they are cosmetic material/decoration picks with
wealth-gated triggers and RNG weights that name and describe generated
artifacts. This script joins all of it: {types, templates, named,
featureGroups}.

Every field present in the data is emitted, consciously skipped (SKIP_*),
or reported unhandled.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

ART = ck3.COMMON / "artifacts"

# --- conscious skips, with reasons -----------------------------------------

SKIP_DIRS = {
    "blueprints": "reforge conversion rules; replacement modifiers are drawn "
                  "randomly per rarity at reforge time (RNG plumbing) — not v1",
    "visuals": "3D asset & icon selection triggers; consumed here only to "
               "derive each named artifact's icon key",
}

TYPE_HANDLED = {"slot", "required_features", "optional_features"}
TYPE_SKIP = {
    "default_visuals": "test-artifact generation only; no gameplay effect (per _types.info)",
    "can_reforge": "reforge gating trigger — the whole reforge flow (blueprints) is skipped",
}

TEMPLATE_HANDLED = {"can_equip", "can_benefit", "can_reforge", "can_repair",
                    "fallback", "unique"}
TEMPLATE_SKIP = {
    "ai_score": "AI equipping weight, not player-facing",
}

FEATURE_HANDLED = {"group", "trigger", "weight"}

SLOT_HANDLED = {"type", "category"}
SLOT_SKIP = {
    "icon": "GUI slot-icon override (trinket/journal slots), not reference data",
}

CA_HANDLED = {"name", "description", "type", "template", "modifier",
              "visuals", "decaying", "rarity"}
CA_SKIP = {
    "wealth": "creation-roll input (RNG/scope), not a property of the artifact",
    "quality": "creation-roll input (RNG/scope), not a property of the artifact",
    "history": "provenance flavor entries (creator/location), scripting detail",
    "creator": "scope wiring", "save_scope_as": "scope wiring",
    "title_history": "scope wiring", "title": "scope wiring",
    "visuals_source": "copies visuals from another artifact scope at runtime",
    "generate_history": "provenance flavor entries, scripting detail",
    "max_durability": "durability system not rendered in v1 (single override)",
}

# scripted_effects filename tokens -> DLC (dlc_tag's prefix regex misses the
# NN_dlc_xxx_ pattern these files use). exp1 = The Royal Court's internal name;
# ach = coronations (see scripted_triggers/00_has_dlc_scripted_triggers.txt).
SE_TOKEN_DLC = dict(ck3.PREFIX_TO_DLC, exp1="The Royal Court", ach="Crowns of the World")
_SE_TOKEN = re.compile(r"(?:^|_)(exp1|fp\d|ep\d|bp\d|mpo|tgp|ach|ce\d)(?=_|$)")

PLACEHOLDER_MODIFIER = "artifact_placeholder_modifier"


def se_dlc(filename):
    m = _SE_TOKEN.search(Path(filename).stem)
    return SE_TOKEN_DLC.get(m.group(1)) if m else None


def pretty(key):
    return re.sub(r"_", " ", re.sub(r"_trigger$", "", str(key))).strip().capitalize()


# --- shallow trigger description -------------------------------------------
# Conditions, not requirements: custom_tooltip texts are unmet-state phrasings
# and scripted-trigger macros are summarized by name, never recursed into.

def _entity_name(ref):
    """religion:x / faith:x / title:k_y / culture:z -> localized name."""
    key = ref.split(":", 1)[1]
    raw = ck3.loc(key) or ck3.loc(f"{key}_name")
    return ck3.render_text(raw) if raw else pretty(key)


def describe_trigger(blk, depth=0):
    """Trigger block -> flat list of human-readable condition strings."""
    if blk is None or depth > 4:
        return []
    if isinstance(blk, Tagged):
        blk = blk.block
    if not isinstance(blk, Block):
        return []
    out = []
    for k, op, v in blk:
        if k is None:
            continue
        if k == "always":
            continue  # always=yes: unrestricted; always=no handled by caller
        if k in ("OR",):
            parts = describe_trigger(v, depth + 1)
            if parts:
                out.append(" or ".join(parts))
        elif k in ("AND", "trigger_else"):
            out.extend(describe_trigger(v, depth + 1))
        elif k in ("NOT", "NOR", "NAND"):
            parts = describe_trigger(v, depth + 1)
            if parts:
                out.append("not: " + "; ".join(parts))
        elif k == "trigger_if" and isinstance(v, Block):
            body = Block([t for t in v.triples if t[0] != "limit"])
            parts = describe_trigger(body, depth + 1)
            limit = describe_trigger(v.get("limit"), depth + 1)
            if parts:
                out.append("; ".join(parts) + (f" (when {'; '.join(limit)})" if limit else ""))
        elif k in ("custom_tooltip", "custom_description") and isinstance(v, Block):
            txt = ck3.loc(v.get("text", ""))
            out.append(ck3.render_text(txt) if txt else pretty(v.get("text", k)))
        elif isinstance(v, str) and "var:" in v:
            var = re.search(r"var:(\w+)", v)
            out.append(f"Matches the artifact's {var.group(1).replace('_', ' ')}")
        elif k == "has_variable" and isinstance(v, str):
            out.append(f"has {v.replace('_', ' ')}")
        elif k == "culture" and isinstance(v, Block):
            for ck, _o, cv in v:
                if ck == "has_cultural_pillar":
                    raw = ck3.loc(f"{cv}_name") or ck3.loc(cv)
                    out.append(f"Culture: {ck3.render_text(raw) if raw else pretty(cv)}")
                elif ck == "has_cultural_parameter":
                    raw = ck3.loc(f"culture_parameter_{cv}")
                    out.append(ck3.render_text(raw) if raw else pretty(cv))
                elif ck is not None:
                    out.append(pretty(ck))
        elif k == "culture" and isinstance(v, str) and v.startswith("culture:"):
            out.append(f"Culture: {_entity_name(v)}")
        elif k in ("has_religion", "religion") and isinstance(v, str) and ":" in v:
            out.append(f"Religion: {_entity_name(v)}")
        elif k == "faith.religion" and isinstance(v, str) and ":" in v:
            out.append(f"Religion: {_entity_name(v.removesuffix('.religion'))}")
        elif k == "has_title" and isinstance(v, str) and ":" in v:
            out.append(f"Holds {_entity_name(v)}")
        elif k == "has_trait" and isinstance(v, str):
            raw = ck3.loc(f"trait_{v}")
            out.append(f"Trait: {ck3.render_text(raw) if raw else pretty(v)}")
        elif k == "has_realm_law" and isinstance(v, str):
            raw = ck3.loc(v) or ck3.loc(f"{v}_name")
            out.append(f"Realm law: {ck3.render_text(raw) if raw else pretty(v)}")
        elif k == "government_allows" and isinstance(v, str):
            out.append(f"{pretty(v)} government")
        elif k == "has_government" and isinstance(v, str):
            raw = ck3.loc(v)
            out.append(ck3.render_text(raw) if raw else pretty(v))
        elif k == "government_has_flag" and isinstance(v, str):
            out.append(pretty(v.removeprefix("government_")))
        elif k == "knows_language" and isinstance(v, str):
            raw = ck3.loc(v)
            out.append(f"Speaks {ck3.render_text(raw) if raw else pretty(v.removeprefix('language_'))}")
        elif k == "has_doctrine" and isinstance(v, str):
            raw = ck3.loc(v) or ck3.loc(f"{v}_name")
            out.append(f"Doctrine: {ck3.render_text(raw) if raw else pretty(v)}")
        elif k == "faith" and isinstance(v, Block):
            out.extend(f"Faith {p[0].lower() + p[1:]}" for p in describe_trigger(v, depth + 1))
        elif k.startswith("scope:artifact") and isinstance(v, Block):
            var = re.search(r"var:(\w+)", repr(v.triples))
            if var:
                out.append(f"Matches the artifact's {var.group(1).replace('_', ' ')}")
            else:
                inner = describe_trigger(v, depth + 1)
                out.append("artifact " + "; ".join(inner) if inner else "artifact state")
        elif k == "category" and isinstance(v, str):
            out.append(f"in a {v} slot")
        elif re.match(r"^has_\w+_dlc_trigger$", k):
            token = re.match(r"^has_(\w+?)_dlc_trigger$", k).group(1)
            out.append(f"{SE_TOKEN_DLC.get(token, pretty(token))} DLC")
        elif k.endswith("_trigger"):
            out.append(pretty(k))  # scripted-trigger macro: name only, never recurse
        elif op in ("<", ">", "<=", ">="):
            n, _r = ck3.resolve_value(v)
            out.append(f"{pretty(k)} {op} {n if n is not None else v}")
        elif isinstance(v, (Block, Tagged)):
            inner = describe_trigger(v, depth + 1)
            out.append(f"{pretty(k)}: {'; '.join(inner)}" if inner else pretty(k))
        else:
            out.append(f"{pretty(k)}" + ("" if v is True else f" = {v}"))
    return list(dict.fromkeys(out))


def trigger_field(blk):
    """-> (allowed: bool, conditions: list). always=no -> (False, [])."""
    if isinstance(blk, Tagged):
        blk = blk.block
    if isinstance(blk, Block) and blk.get("always") is False and len(blk.items()) == 1:
        return False, []
    return True, describe_trigger(blk)


def render_mod_block(blk, unhandled):
    lines = []
    if isinstance(blk, Block):
        for mk, _o, mv in blk:
            if mk is None:
                continue
            if isinstance(mv, (Block, Tagged)):
                unhandled[f"modifier:{mk}"] += 1
                continue
            lines.append({"key": mk, "text": ck3.render_modifier(mk, mv),
                          "polarity": ck3.modifier_polarity(mk, mv)})
    return lines


# --- named-artifact extraction ---------------------------------------------

def walk_create_artifact(b, out):
    if isinstance(b, Tagged):
        b = b.block
    if not isinstance(b, Block):
        return
    for k, _op, v in b:
        if k == "create_artifact" and isinstance(v, Block):
            out.append(v)
        elif isinstance(v, (Block, Tagged)):
            walk_create_artifact(v, out)


_RARITY = re.compile(r"^set_artifact_rarity_(\w+)$")


def walk_rarity(b, found):
    if isinstance(b, Tagged):
        b = b.block
    if not isinstance(b, Block):
        return
    for k, _op, v in b:
        m = _RARITY.match(k) if isinstance(k, str) else None
        if m:
            found.add(m.group(1))
        if isinstance(v, (Block, Tagged)):
            walk_rarity(v, found)


def sets_historical_unique(b):
    """Does the effect body mark its artifact with historical_unique_artifact?"""
    if isinstance(b, Tagged):
        b = b.block
    if not isinstance(b, Block):
        return False
    for k, _op, v in b:
        if k == "set_variable":
            if v == "historical_unique_artifact":
                return True
            if isinstance(v, Block) and v.get("name") == "historical_unique_artifact":
                return True
        if isinstance(v, (Block, Tagged)) and sets_historical_unique(v):
            return True
    return False


def main():
    unhandled = Counter()

    # -- slot instances: slot type -> category (inventory | court) ----------
    slot_category = {}
    for _p, key, blk in ck3.parse_dir(ART / "slots"):
        slot_category[blk.get("type")] = blk.get("category")
        for k in blk.keys():
            if k not in SLOT_HANDLED and k not in SLOT_SKIP:
                unhandled[f"slots:{k}"] += 1

    # -- types --------------------------------------------------------------
    types = []
    type_by_id = {}
    for path, key, blk in ck3.parse_dir(ART / "types"):
        dlc, _feats = ck3.dlc_tag(path, blk)
        name = ck3.loc(f"artifact_{key}")
        slot = blk.get("slot")
        rec = {
            "id": key,
            "name": ck3.render_text(name) if name else pretty(key),
            "slot": slot,
            "category": slot_category.get(slot),
            "requiredFeatures": [v for v in (blk.get("required_features") or Block()).values()],
            "optionalFeatures": [v for v in (blk.get("optional_features") or Block()).values()],
            "dlc": dlc,
        }
        for k in blk.keys():
            if k not in TYPE_HANDLED and k not in TYPE_SKIP:
                unhandled[f"types:{k}"] += 1
        types.append(rec)
        type_by_id[key] = rec
    types.sort(key=lambda r: (r["category"] or "", r["slot"] or "", r["id"]))

    # -- templates ----------------------------------------------------------
    templates = []
    template_by_id = {}
    for path, key, blk in ck3.parse_dir(ART / "templates"):
        dlc, _feats = ck3.dlc_tag(path, blk)
        _always_equip, equip = trigger_field(blk.get("can_equip"))
        _always_benefit, benefit = trigger_field(blk.get("can_benefit"))
        can_reforge, reforge_conds = trigger_field(blk.get("can_reforge")) if blk.has("can_reforge") else (True, [])
        can_repair, repair_conds = trigger_field(blk.get("can_repair")) if blk.has("can_repair") else (True, [])
        rec = {
            "id": key,
            "label": pretty(key.removesuffix("_template")),
            "unique": bool(blk.get("unique", False)),
            "equip": equip,
            "benefit": benefit,
            "fallback": render_mod_block(blk.get("fallback"), unhandled),
            "canReforge": can_reforge, "reforgeConditions": reforge_conds,
            "canRepair": can_repair, "repairConditions": repair_conds,
            "dlc": dlc,
            "artifacts": [],  # filled from the named scan below
            "sourceFile": path.name,
        }
        for k in blk.keys():
            if k not in TEMPLATE_HANDLED and k not in TEMPLATE_SKIP:
                unhandled[f"templates:{k}"] += 1
        templates.append(rec)
        template_by_id[key] = rec
    templates.sort(key=lambda r: r["id"])

    # -- visuals: key -> icon (plain string wins; else last fallback block) --
    icon_by_visual = {}
    for _p, key, blk in ck3.parse_dir(ART / "visuals"):
        icon = None
        for k, _op, v in blk:
            if k == "icon":
                if isinstance(v, str):
                    icon = v
                elif isinstance(v, Block) and isinstance(v.get("reference"), str):
                    icon = v.get("reference")  # last one = broadest fallback
        if icon:
            icon_by_visual[key] = str(icon).removesuffix(".dds")

    # -- modifier library (all of common/modifiers) -------------------------
    modlib = {}
    for p in sorted((ck3.COMMON / "modifiers").glob("*.txt")):
        if p.name.startswith("_"):
            continue
        for k, _op, v in ck3.parse_file(p):
            if k is not None and isinstance(v, Block):
                modlib[k] = v

    # -- named artifacts from create_artifact blocks ------------------------
    named = {}
    ca_total = ca_kept = 0
    for p in sorted((ck3.COMMON / "scripted_effects").glob("*.txt")):
        if p.name.startswith("_"):
            continue
        text_probe = p.read_text(encoding="utf-8-sig", errors="replace")
        if "create_artifact" not in text_probe:
            continue
        top = ck3.parse_file(p)
        for effect_key, _op, body in top:
            if not isinstance(body, (Block, Tagged)):
                continue
            cas = []
            walk_create_artifact(body, cas)
            if not cas:
                continue
            rarities = set()
            walk_rarity(body, rarities)
            hist_unique = sets_historical_unique(body)
            for ca in cas:
                ca_total += 1
                name_key = ca.get("name")
                tmpl = ca.get("template")
                mods = [m for m in ca.get_all("modifier") if isinstance(m, str) and "$" not in m]
                if not (isinstance(name_key, str) and "$" not in name_key and ck3.loc(name_key)):
                    continue  # dynamic/parameterized name: a generated artifact
                if not (isinstance(tmpl, str) and tmpl in template_by_id):
                    # untemplated generic creation (base weapons etc.) — unless
                    # the effect marks it as a historical unique (e.g. Excalibur)
                    if not hist_unique:
                        continue
                    tmpl = None
                name = ck3.render_text(ck3.loc(name_key))
                if "…" in name:
                    continue  # name needs runtime data (e.g. owner's dynasty)
                mods = [m for m in mods if m != PLACEHOLDER_MODIFIER]
                if not mods:
                    continue  # placeholder modifier: real bonus assigned later by RNG
                ca_kept += 1
                for k in ca.keys():
                    if k not in CA_HANDLED and k not in CA_SKIP:
                        unhandled[f"create_artifact:{k}"] += 1
                atype = ca.get("type")
                desc_key = ca.get("description")
                rec = named.setdefault(name_key, {
                    "id": name_key,
                    "name": name,
                    "desc": None,
                    "types": [],
                    "template": tmpl,
                    "unique": hist_unique or (template_by_id[tmpl]["unique"] if tmpl else False),
                    "rarity": sorted(rarities),
                    "permanent": ca.get("decaying") is False,
                    "modifiers": [],
                    "icon": None,
                    "dlc": se_dlc(p.name),
                    "sourceFile": p.name,
                })
                if isinstance(atype, str) and atype in type_by_id and atype not in rec["types"]:
                    rec["types"].append(atype)
                if rec["desc"] is None and isinstance(desc_key, str) and ck3.loc(desc_key):
                    d = ck3.render_text(ck3.loc(desc_key))
                    rec["desc"] = d if "…" not in d else None
                if rec["icon"] is None:
                    vis = ca.get("visuals")
                    if isinstance(vis, str):
                        rec["icon"] = icon_by_visual.get(vis)
                rec["rarity"] = sorted(set(rec["rarity"]) | rarities)
                for m in mods:
                    if m not in [x["key"] for x in rec["modifiers"]]:
                        if m in modlib:
                            rec["modifiers"].append({"key": m,
                                                     "lines": render_mod_block(modlib[m], unhandled)})
                        else:
                            unhandled[f"missing_modifier_def:{m}"] += 1

    named_list = sorted(named.values(),
                        key=lambda r: (slot_category.get(type_by_id[r["types"][0]]["slot"], "") if r["types"] else "~",
                                       r["types"][0] if r["types"] else "~", r["name"]))
    for r in named_list:
        if r["template"]:
            template_by_id[r["template"]]["artifacts"].append(r["id"])

    # -- features & groups ---------------------------------------------------
    groups = {key: {"id": key, "label": pretty(key), "features": []}
              for _p, key, _b in ck3.parse_dir(ART / "feature_groups")}
    orphan_groups = Counter()
    for path, key, blk in ck3.parse_dir(ART / "features"):
        for k in blk.keys():
            if k not in FEATURE_HANDLED:
                unhandled[f"features:{k}"] += 1
        gkey = blk.get("group")
        weight_n, _rules = ck3.resolve_value(blk.get("weight", 1))
        # wealth window from the trigger; anything else is a flagged condition
        lo = hi = None
        conditional = False
        trig = blk.get("trigger")
        if isinstance(trig, Block):
            for tk, top_, tv in trig:
                if tk == "scope:wealth" and isinstance(tv, (int, float)):
                    if top_ in (">=", ">"):
                        lo = max(lo, tv) if lo is not None else tv
                    elif top_ in ("<", "<="):
                        hi = min(hi, tv) if hi is not None else tv
                elif tk is not None:
                    conditional = True
        wealth = None
        if lo is not None or hi is not None:
            wealth = f"{int(lo) if lo is not None else 0}–{int(hi) if hi is not None else '∞'}"
        raw = ck3.loc(f"feature_{key}")
        text = ck3.render_text(raw) if raw else None
        rec = {
            "id": key,
            "text": text if text and "…" not in text else None,
            "weight": weight_n if weight_n is not None else "varies",
            "wealth": wealth,
            "conditional": conditional,
        }
        if gkey in groups:
            groups[gkey]["features"].append(rec)
        else:
            orphan_groups[gkey or "(none)"] += 1

    feature_groups = [g for g in groups.values() if g["features"]]
    empty_groups = [g["id"] for g in groups.values() if not g["features"]]

    data = {
        "types": types,
        "templates": templates,
        "named": named_list,
        "featureGroups": feature_groups,
    }
    ck3.write_json("artifacts.json", data)
    print(f"  types {len(types)} · templates {len(templates)} · named {len(named_list)}"
          f" (from {ca_kept}/{ca_total} create_artifact blocks)"
          f" · feature groups {len(feature_groups)} "
          f"({sum(len(g['features']) for g in feature_groups)} features)")
    if empty_groups:
        print(f"  (feature groups with no features, omitted: {len(empty_groups)})")
    if orphan_groups:
        print(f"⚠ features referencing undeclared groups: {dict(orphan_groups)}")
    if unhandled:
        print("⚠ unhandled artifact fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k} ×{n}")
    unnamed = [r["id"] for r in named_list if not r["name"]]
    if unnamed:
        print(f"⚠ {len(unnamed)} named artifacts without localized names: {unnamed[:10]}")


if __name__ == "__main__":
    main()
