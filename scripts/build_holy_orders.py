#!/usr/bin/env python3
"""Build src/data/holy_orders.json from common/holy_orders/.

1.20 (By God Alone) turned holy orders into weighted *types*: when an order
is founded (create_holy_order), the game picks among the types of the
requested kind (military | monastic) whose `trigger` passes, by `weight`.
Per _holy_orders.info the scopes are founder, leader and province (the
barony being leased out).

What we render, honestly:

  trigger   most types split into a game-start branch
            (`trigger_if = { limit = { …has_variable = *_game_start_founder } }`)
            and the normal-play branch (`trigger_else`); both are described
            separately. Conditions we cannot phrase render as "…".
  weight    base `value`, then each top-level `if` as {add|multiply, when}.
  tenets    the `tenet` field plus every `set_order_tenet` in `effect`
            (conditional when set inside an if).
  name      loc of `name` (or the title's name); scope placeholders such as
            [FOUNDER.GetCulture.GetNameNoTooltip] become ‹founder's culture›.

Must run after build_titles/build_regions/build_maa: names and links come
from the site's own data so they match the pages they point to.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
import faith_cond
from ck3 import Block, Tagged

HANDLED = {"type", "government", "trigger", "weight", "title", "name",
           "men_at_arms", "tenet", "effect"}
SKIP = {"coat_of_arms": "scripted coat of arms (art)"}

DATA = Path(__file__).resolve().parent.parent / "src" / "data"

FILE_GROUPS = {"christian": "Christian", "muslim": "Islamic", "generic": "Any faith"}


def site(name):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


_titles = site("title-index.json") or {}
_regions = {r["id"]: r for r in (site("regions.json") or {}).get("regions", [])}
_maa = {m["id"]: m.get("name") for m in (site("maa.json") or [])}


def lname(key, *suffixes):
    for k in [key, *[f"{key}{s}" for s in suffixes]]:
        raw = ck3.loc(k)
        if raw:
            t = ck3.render_text(raw)
            if t:
                return t
    return key.replace("_", " ")


def title_name(t):
    return _titles.get(t, {}).get("name") or lname(t)


# --- name placeholders -------------------------------------------------------

_PH = re.compile(r"\[([A-Z_]+)\.([^\]|]*)(?:\|[^\]]*)?\]")
_WHO = {"FOUNDER": "founder's", "LEADER": "leader's", "LEFT_CHARACTER": "founder's"}


def _placeholder(m):
    scope, chain = m.group(1), m.group(2)
    who = _WHO.get(scope)
    if "FirstName" in chain and who:
        return f"‹{who} first name›"
    if "DynastyHouse" in chain and who:
        return f"‹{who} house›"
    if "GetCulture" in chain and who:
        return f"‹{who} culture›"
    tm = re.search(r"GetDeJureLiegeOfTier\(\s*'(\w+)'\s*\)", chain)
    if tm:
        return f"‹{tm.group(1)} adjective›" if "Adjective" in chain else f"‹{tm.group(1)}›"
    if scope == "PROVINCE":
        return "‹barony›"
    if scope == "TITLE":
        return "‹title›"
    for k, v in (("WarGod", "war god"), ("HighGod", "high god"), ("Adjective", "faith adjective"),
                 ("ReligiousSymbol", "religious symbol"), ("DivineRealm", "divine realm")):
        if k in chain:
            return f"‹{v}›"
    return "‹…›"


def order_name(key, title):
    raw = ck3.loc(key) if key else None
    if raw:
        return ck3.render_text(_PH.sub(_placeholder, raw)), "‹" in _PH.sub(_placeholder, raw)
    if title:
        return title_name(title), False
    return (key or "").replace("_", " "), False


# --- condition text -----------------------------------------------------------

def _join(parts, word):
    other = " or " if word == " and " else " and "
    return word.join(f"({x})" if other in x and len(parts) > 1 else x for x in parts)


def _ref_name(v):
    """title:/religion:/faith:/rite:/culture: reference -> (kind, display)."""
    if not isinstance(v, str) or ":" not in v:
        return None, None
    kind, key = v.split(":", 1)
    if kind == "title":
        return "title", title_name(key)
    if kind in ("religion", "faith", "rite", "culture"):
        return kind, lname(key)
    return None, None


TIER_FIELDS = {"county", "duchy", "kingdom", "empire"}
YEAR_OPS = {">=": "from {}", ">": "after {}", "<": "before {}", "<=": "up to {}"}


def _subject(key):
    """scope:founder.faith -> ('founder', 'faith'); location -> (None, None)."""
    if not key.startswith("scope:"):
        return None, None
    path = key[6:].split(".")
    return path[0], path[-1] if len(path) > 1 else None


def is_gamestart(blk):
    """Does this limit test the *_game_start_founder variable?"""
    if not isinstance(blk, Block):
        return False
    for k, _op, v in blk:
        if k == "has_variable":
            name = v.get("name") if isinstance(v, Block) else v
            if isinstance(name, str) and name.endswith("_game_start_founder"):
                return True
        if isinstance(v, Block) and is_gamestart(v):
            return True
    return False


def describe(blk, who="founder"):
    parts = []
    pre = "" if who in ("founder", "province") else f"{who} "
    for k, op, v in blk:
        if k is None:
            continue
        if k in ("exists", "save_temporary_scope_as", "save_scope_as"):
            continue  # scope plumbing, not a condition a player meets
        if k in ("OR", "AND", "NOT", "NOR") and isinstance(v, Block):
            inner = describe(v, who)
            if not inner:
                continue
            if k == "OR":
                parts.append(_join(inner, " or "))
            elif k == "AND":
                parts.append(_join(inner, " and "))
            else:
                parts.append("not " + (f"({_join(inner, ' or ')})" if len(inner) > 1 or " " in inner[0] else inner[0]))
            continue
        subj, field = _subject(k) if isinstance(k, str) else (None, None)
        if subj:
            nwho = subj if subj in ("founder", "leader", "province") else who
            if isinstance(v, Block):
                inner = describe(v, nwho)
                if field in TIER_FIELDS:
                    # scope:province.kingdom = { OR = { this = title:k_x … } }
                    inner = [x.replace("is ", "in ", 1) if x.startswith("is ") else x for x in inner]
                if inner:
                    parts.append(_join(inner, " and "))
                continue
            kind, name = _ref_name(v)
            if field in TIER_FIELDS and kind == "title":
                parts.append(f"in {name}")
                continue
            if field in ("religion", "faith", "rite", "culture") and kind:
                parts.append(f"{('' if nwho == 'founder' else nwho + ' ')}{kind}: {name}")
                continue
            if field in ("title", "primary_title") and kind == "title":
                parts.append(f"{nwho} {'holds' if field == 'primary_title' else 'is'} {name}")
                continue
            parts.append("…")
            continue
        if k in ("faith", "rite", "culture", "location", "religion") and isinstance(v, Block):
            inner = describe(v, who)
            if inner:
                parts.append(_join(inner, " and "))
            continue
        if k in TIER_FIELDS and isinstance(v, str):
            kind, name = _ref_name(v)
            parts.append(f"in {name}" if kind == "title" else "…")
            continue
        if k == "this" and isinstance(v, str):
            kind, name = _ref_name(v)
            parts.append(f"is {name}" if kind == "title" else (f"culture: {name}" if kind == "culture" else "…"))
            continue
        if k in ("religion", "faith", "rite", "culture") and isinstance(v, str):
            kind, name = _ref_name(v)
            parts.append(f"{pre}{kind}: {name}" if kind else "…")
            continue
        if k == "geographical_region" and isinstance(v, str):
            r = _regions.get(v)
            parts.append(f"in {r['name'] if r else v.replace('_', ' ')}")
            continue
        if k == "has_doctrine_parameter" and isinstance(v, str):
            src = faith_cond.rite_param_sources(v)
            parts.append(f"faith has {' or '.join(src)}" if src else f"faith has parameter {v}")
            continue
        if k == "rite_has_doctrine" and isinstance(v, str):
            parts.append(f"Rite has {faith_cond.doctrine_cond_name(v)}")
            continue
        if k == "rite_has_tenet" and isinstance(v, str):
            parts.append(f"Rite has {faith_cond.doctrine_cond_name(v)}")
            continue
        if k == "has_cultural_pillar" and isinstance(v, str):
            parts.append(f"{lname(v, '_name')} culture")
            continue
        if k == "has_cultural_parameter" and isinstance(v, str):
            parts.append(lname(f"culture_parameter_{v}"))
            continue
        if k == "knows_language" and isinstance(v, str):
            parts.append(f"{pre}knows {lname(v, '_name')}")
            continue
        if k == "current_year" and op in YEAR_OPS:
            parts.append(YEAR_OPS[op].format(v))
            continue
        if k == "years_from_game_start" and op == "<":
            parts.append("at game start")
            continue
        if k in ("is_female", "is_male") and v in ("yes", "no", True, False):
            sex = "female" if (k == "is_female") == (v in ("yes", True)) else "male"
            parts.append(f"{who} is {sex}")
            continue
        if k == "has_character_modifier" and isinstance(v, str) and ck3.loc(v):
            parts.append(f"{who} has {lname(v)}")
            continue
        if k == "has_trait" and isinstance(v, str):
            parts.append(f"{who} has {lname('trait_' + v)}")
            continue
        if k == "has_variable":
            name = v.get("name") if isinstance(v, Block) else v
            if isinstance(name, str) and name.endswith("_game_start_founder"):
                parts.append("at game start")
            else:
                parts.append("…")
            continue
        if k == "any_faith_holy_order" and isinstance(v, Block):
            # uniqueness checks: the inner conditions test an existing order's title
            parts.append("the faith already has such an order")
            continue
        if k == "always":
            if v in ("no", False):
                parts.append("never")
            continue
        parts.append("…")
    return parts


def trigger_branches(t):
    """-> (normal, game_start). game_start None: no separate start branch."""
    if not isinstance(t, Block):
        return [], None
    ti = t.get("trigger_if")
    if isinstance(ti, Block) and is_gamestart(ti.get("limit")):
        body = Block([x for x in ti if x[0] != "limit"])
        start = describe(body)
        te = t.get("trigger_else")
        rest = Block([x for x in t if x[0] not in ("trigger_if", "trigger_else")])
        normal = describe(te) if isinstance(te, Block) else []
        normal += describe(rest)
        return normal, start
    return describe(t), None


def weight_terms(w):
    if not isinstance(w, Block):
        return None, []
    base = w.get("value")
    n, _r = ck3.resolve_value(base) if isinstance(base, str) else (base, None)
    terms = []
    for k, _op, v in w:
        if k not in ("if", "else_if") or not isinstance(v, Block):
            continue
        lim = v.get("limit")
        for op in ("add", "multiply"):
            val = v.get(op)
            if val is None:
                continue
            if isinstance(val, str):
                vv, _r = ck3.resolve_value(val)
                val = vv if vv is not None else val
            if not isinstance(val, (int, float)):
                val = None
            when = describe(lim) if isinstance(lim, Block) else []
            terms.append({"op": op, "value": val,
                          "when": when or ["…"],
                          "gameStart": is_gamestart(lim) or "at game start" in when})
    return (n if isinstance(n, (int, float)) else None), terms


def tenets_of(blk):
    """tenet field + set_order_tenet in effect -> [{id, name, conditional}]."""
    out = {}
    t = blk.get("tenet")
    if isinstance(t, str):
        out[t] = False

    def walk(b, cond):
        for k, _op, v in b:
            if k == "set_order_tenet" and isinstance(v, str):
                key = v.split(":", 1)[-1]
                out.setdefault(key, cond)
                out[key] = out[key] and cond
            elif isinstance(v, Block):
                walk(v, cond or k in ("if", "else_if", "else", "random_list", "random"))
    eff = blk.get("effect")
    if isinstance(eff, Block):
        walk(eff, False)
    return [{"id": k, "name": faith_cond.doctrine_cond_name(k), "conditional": c} for k, c in out.items()]


def main():
    unhandled = Counter()
    orders = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "holy_orders"):
        if not isinstance(blk, Block):
            continue
        for k, _op, _v in blk:
            if k not in HANDLED and k not in SKIP:
                unhandled[k] += 1
        stem = Path(path).stem
        group = next((v for g, v in FILE_GROUPS.items() if g in stem), stem)
        title = blk.get("title") if isinstance(blk.get("title"), str) else None
        name, templated = order_name(blk.get("name"), title)
        normal, start = trigger_branches(blk.get("trigger"))
        base, terms = weight_terms(blk.get("weight"))
        ma = blk.get("men_at_arms")
        maa = [v for k, _o, v in ma if k is None] if isinstance(ma, Block) else []
        gov = blk.get("government")
        orders.append({
            "id": key,
            "name": name,
            "templated": templated,
            "kind": blk.get("type") or "military",
            "group": group,
            "government": gov,
            "governmentName": lname(gov) if isinstance(gov, str) else None,
            "title": title,
            "titleName": title_name(title) if title else None,
            "requires": normal,
            "gameStart": start,
            "baseWeight": base,
            "weight": terms,
            "menAtArms": [{"id": m, "name": _maa.get(m) or lname(m), "known": m in _maa} for m in maa],
            "tenets": tenets_of(blk),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })

    out = {
        "orders": orders,
        "about": ck3.render_text(ck3.loc("game_concept_holy_order_desc") or "") or None,
    }
    ck3.write_json("holy_orders.json", out)
    kinds = Counter(o["kind"] for o in orders)
    opaque = sum(1 for o in orders if any("…" in x for x in o["requires"]))
    print(f"  {len(orders)} holy order types ({dict(kinds)}); "
          f"{opaque} with a condition rendered as …")
    if unhandled:
        print("⚠ unhandled holy-order fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k}: {n}")


if __name__ == "__main__":
    main()
