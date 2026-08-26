#!/usr/bin/env python3
"""Per-event detail data: options and what each one does.

"What it does" is rendered from the game's own tooltip vocabulary:
common/effect_localization/ maps every scriptable effect to the loc keys the
game itself uses to describe it. We render the `first`-person variant where
the game defines one, so an option reads the way it reads in game.

Effects the game does not localize (control flow, scope plumbing, scripted
effect macros) are NOT invented — they are counted and reported as
"unlocalized script" so a reader knows something further happens.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

EVENTS = ck3.REF / "game" / "events"

# Effect keys that are control flow / plumbing, not player-facing outcomes.
STRUCTURAL = {
    "if", "else", "else_if", "trigger_if", "trigger_else", "trigger_else_if",
    "limit", "while", "random", "random_list", "switch", "hidden_effect",
    "trigger", "save_scope_as", "save_scope_value_as", "scope", "every_", "any_",
    "random_", "ordered_", "custom_tooltip", "show_as_tooltip", "name",
    "ai_chance", "flavor", "custom_description", "duel", "first_valid",
    "triggered_desc", "desc", "trait", "value", "add", "compare_modifier",
    "modifier", "opinion_modifier", "years", "months", "days", "target",
    "reason", "tooltip",
}


def effect_loc_table():
    """effect key -> loc key, preferring the first-person present phrasing."""
    table = {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "effect_localization"):
        if not isinstance(blk, Block):
            continue
        for variant in ("first", "global", "third", "first_past", "global_past"):
            v = blk.get(variant)
            if isinstance(v, str):
                table[key] = v
                break
    return table


EFFECT_LOC = None


_VALUE_SLOT = re.compile(r"\$VALUE(\|[^$]*)?\$")


def render_effect(key, value):
    """One readable outcome line, or None if the game gives us no words.

    The game's effect templates carry a $VALUE|fmt$ slot for the amount; fill
    it with the scripted value so the line reads as it does in game."""
    loc_key = EFFECT_LOC.get(key)
    if not loc_key:
        return None
    text = ck3.loc(loc_key)
    if not text:
        return None

    if isinstance(value, bool):
        amount = None
    elif isinstance(value, (int, float)):
        amount = f"{value:+g}"
    elif isinstance(value, str):
        n, _rules = ck3.resolve_value(value)
        if n is not None:
            amount = f"{n:+g}"
        else:
            pretty = (ck3.loc(f"trait_{value}") or ck3.loc(value)
                      or value.replace("_", " ").title())
            amount = ck3.render_text(pretty)
    else:
        amount = None

    # substitute before rendering so the slot's own formatting is consumed
    if amount is not None:
        text = _VALUE_SLOT.sub(lambda _m: amount, text)
    out = ck3.render_text(text)
    if amount is not None and amount not in out and "…" in out:
        out = out.replace("…", amount, 1)
    return out.strip(" :") or None


def walk_effects(block, lines, unloc, depth=0):
    """Collect readable outcome lines; count what we cannot phrase."""
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block) or depth > 4:
        return
    for k, _op, v in block:
        if not isinstance(k, str):
            continue
        if k in ("ai_chance", "trigger", "limit", "is_shown", "is_valid",
                 "compare_modifier", "opinion_modifier", "modifier"):
            continue  # weights and conditions, not outcomes
        if isinstance(v, (Block, Tagged)):
            # recurse through control flow and scope changes
            walk_effects(v, lines, unloc, depth + 1)
            continue
        if k in STRUCTURAL:
            continue
        line = render_effect(k, v)
        if line:
            if line not in lines:
                lines.append(line)
        else:
            unloc.add(k)


def option_text(opt):
    """The option's button text, from its own loc key."""
    nm = opt.get("name")
    if isinstance(nm, str):
        t = ck3.render_text(ck3.loc(nm) or "")
        if t:
            return t
    if isinstance(nm, (Block, Tagged)):
        refs = []
        b = nm.block if isinstance(nm, Tagged) else nm
        for k, _o, v in b:
            if k in ("text", "desc") and isinstance(v, str):
                refs.append(v)
        for r in reversed(refs):
            t = ck3.render_text(ck3.loc(r) or "")
            if t:
                return t
    return None


def tooltip_text(opt):
    """The game's own explanatory line for the option, when it has one."""
    out = []
    for ct in opt.get_all("custom_tooltip"):
        if isinstance(ct, str):
            t = ck3.render_text(ck3.loc(ct) or "")
            if t:
                out.append(t)
        elif isinstance(ct, Block):
            ref = ct.get("text")
            if isinstance(ref, str):
                t = ck3.render_text(ck3.loc(ref) or "")
                if t:
                    out.append(t)
    return out


def main():
    global EFFECT_LOC
    EFFECT_LOC = effect_loc_table()
    print(f"  effect vocabulary: {len(EFFECT_LOC)} localized effects")

    details = {}
    unloc_all = Counter()
    n_opts = 0
    for f in sorted(EVENTS.rglob("*.txt")):
        try:
            blk = ck3.parse_file(f)
        except Exception:
            continue
        for key, _op, v in blk:
            if not (isinstance(key, str) and "." in key and isinstance(v, Block)):
                continue
            opts = v.get_all("option")
            if not opts:
                continue
            rendered = []
            for opt in opts:
                if not isinstance(opt, Block):
                    continue
                lines, unloc = [], set()
                walk_effects(opt, lines, unloc)
                unloc_all.update(unloc)
                rendered.append({
                    "text": option_text(opt),
                    "tooltip": tooltip_text(opt),
                    "outcomes": lines[:12],
                    "unlocalized": len(unloc),
                })
                n_opts += 1
            if rendered:
                details[key] = rendered

    out = ck3.ROOT / "public/data/event-options.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    named = sum(1 for v in details.values() for o in v if o["text"])
    print(f"✓ wrote public/data/event-options.json — {len(details)} events, "
          f"{n_opts} options ({named} with button text)")
    print(f"  top unlocalized effect keys: "
          f"{[k for k, _ in unloc_all.most_common(8)]}")


if __name__ == "__main__":
    main()
