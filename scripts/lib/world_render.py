"""Shared rendering helpers for the World pages' build scripts
(struggles, situations, legends, epidemics).

Everything here is presentation-side sugar over ck3.resolve_value /
ck3.render_modifier: compact human strings for rule structures, durations
({ months = { 6 8 } }), numeric ranges ({ 30 55 }), and modifier blocks.
Honest-rendering rule applies: conditional values keep their rule text; they
are never collapsed to one number.
"""

import ck3
from ck3 import Block, Tagged

UNIT_ORDER = ("days", "weeks", "months", "years")


def num(n):
    """Trim floats like 3.0 -> 3 for display."""
    if isinstance(n, float) and n == int(n):
        return int(n)
    if isinstance(n, float):
        return round(n, 3)
    return n


def range_text(v):
    """A scalar or a loose `{ 30 55 }` range -> '30' / '30–55'."""
    if isinstance(v, Block):
        vals = [x for x in v.values() if isinstance(x, (int, float))]
        if len(vals) == 2:
            return f"{num(vals[0])}–{num(vals[1])}"
        if len(vals) == 1:
            return str(num(vals[0]))
        return None
    if isinstance(v, (int, float)):
        return str(num(v))
    if isinstance(v, str):
        n, rules = ck3.resolve_value(v)
        return str(num(n)) if n is not None else rule_text(rules)
    return None


def duration_text(v):
    """A scripted duration block -> '6–8 months' / '25 days'."""
    if not isinstance(v, Block):
        return None
    for unit in UNIT_ORDER:
        if v.has(unit):
            amount = range_text(v.get(unit))
            if amount is None:
                continue
            u = unit[:-1] if amount.isdigit() and amount == "1" else unit
            return f"{amount} {u}"
    return None


def rule_text(rules, depth=0):
    """resolve_value's rule structure -> one compact human string."""
    if rules is None:
        return None
    if isinstance(rules, (int, float)):
        return str(num(rules))
    if isinstance(rules, str):
        return rules.replace("_", " ")
    if isinstance(rules, dict):
        parts = []
        for k, v in rules.items():
            if k == "base":
                parts.append(f"base {rule_text(v, depth + 1)}")
            elif k == "value":
                parts.append(f"{rule_text(v, depth + 1)}")
            elif k == "add":
                parts.append(f"+{rule_text(v, depth + 1)}")
            elif k == "subtract":
                parts.append(f"−{rule_text(v, depth + 1)}")
            elif k == "multiply":
                parts.append(f"×{rule_text(v, depth + 1)}")
            elif k == "divide":
                parts.append(f"÷{rule_text(v, depth + 1)}")
            elif k in ("min", "max"):
                parts.append(f"{k} {rule_text(v, depth + 1)}")
            elif k == "if":
                cond = str(v).replace("_", " ")
                then = rules.get("then")
                then_s = "; ".join(str(t).replace("_", " ") for t in then) if then else ""
                parts.append(f"(if {cond}: {then_s})")
            elif k == "then":
                continue  # rendered with its "if"
            elif k == "desc":
                continue  # tooltip plumbing inside script values
            elif k == "else_if" or k == "else":
                parts.append("(else …)")
            else:
                parts.append(f"{k.replace('_', ' ')} {rule_text(v, depth + 1)}")
        return " ".join(parts)
    if isinstance(rules, list):
        return " ".join(filter(None, (rule_text(r, depth + 1) for r in rules)))
    return str(rules)


def value_out(v):
    """A cost/chance/points value -> {'value': n} or {'rules': text}."""
    n, rules = ck3.resolve_value(v)
    if n is not None:
        return {"value": num(n)}
    return {"rules": rule_text(rules)}


def cost_out(blk):
    """A scripted_cost block -> {resource: value_out}, skipping `round`."""
    if blk is None:
        return None
    if isinstance(blk, (int, float, str)):
        return {"gold": value_out(blk)}
    out = {}
    for k, _op, v in blk:
        if k is None or k == "round":
            continue
        out[k] = value_out(v)
    return out


def mods_out(blk):
    """A modifier block -> rendered lines [{key, text, polarity}]."""
    out = []
    if not isinstance(blk, Block):
        return out
    for k, _op, v in blk:
        if k is None:
            continue
        n, _rules = (ck3.resolve_value(v) if isinstance(v, str) else (v, None))
        polarity = ck3.modifier_polarity(k, n if n is not None else v)
        out.append({"key": k, "text": ck3.render_modifier(k, v), "polarity": polarity})
    return out


def loc_chain(*keys):
    """First present loc key from candidates, rendered; else None."""
    for k in keys:
        if k is None:
            continue
        raw = ck3.loc(k)
        if raw is not None:
            return ck3.render_text(raw)
    return None


def last_desc_key(block):
    """A dynamic name/desc block (first_valid/random_valid/triggered_desc) ->
    the LAST bare `desc = key` (the untriggered fallback), per the repo's
    dynamic-name quirk."""
    found = []

    def walk(b):
        if isinstance(b, Tagged):
            b = b.block
        if not isinstance(b, Block):
            return
        for k, _op, v in b:
            if k == "desc" and isinstance(v, str):
                found.append(v)
            elif isinstance(v, (Block, Tagged)):
                walk(v)

    walk(block)
    return found[-1] if found else None


def scan_dlc_features_negation_aware(block):
    """(positive_features, negated_features) for has_dlc_feature occurrences.
    A feature seen ONLY under NOT/NOR/NAND is a base-game compensation branch,
    not a DLC requirement (the epidemics pattern)."""
    pos, neg = set(), set()
    NEGATORS = {"NOT", "NOR", "NAND"}

    def walk(b, negated):
        if isinstance(b, Tagged):
            b = b.block
        if not isinstance(b, Block):
            return
        for k, _op, v in b:
            if k == "has_dlc_feature" and isinstance(v, str):
                (neg if negated else pos).add(v)
            elif isinstance(v, (Block, Tagged)):
                walk(v, negated or (k in NEGATORS))

    walk(block, False)
    return pos, neg
