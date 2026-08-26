#!/usr/bin/env python3
"""Build src/data/interactions.json and secrets.json.

Character interactions (470), plus secret types and hook types. Costs resolve
through script values; availability gates are extracted shallowly with
negation tracking, the same way build_maa.py does it.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

SKIP = {
    "on_accept", "on_decline", "on_send", "on_blocked_effect", "on_auto_accept",
    "ai_targets", "ai_will_do", "ai_frequency_by_tier", "ai_potential",
    "ai_accept", "ai_min_reply_days", "ai_max_reply_days", "ai_set_target",
    "interface_priority", "greeting", "notification_text", "extra_icon",
    "should_use_extra_icon", "highlighted_reason", "on_intermediary_accept",
    "on_intermediary_decline", "populate_actor_list", "populate_recipient_list",
    "localization_values", "answer_block_key", "answer_accept_key",
    "answer_reject_key", "answer_acknowledge_key", "options_heading",
    "pre_answer_maybe_breakdown_key", "pre_answer_yes_breakdown_key",
    "pre_answer_no_breakdown_key", "send_name", "target_type", "target_filter",
    "hidden", "common_interaction", "category_header", "sound", "is_highlighted",
    "can_send_despite_reject", "needs_recipient_to_open", "show_effects_in_notification",
    "recipient_message_key", "message_key", "confirm_text", "auto_accept",
    "send_option_conditional", "redirect", "cooldown_against_recipient",
    "banner_text", "on_intermediary_invalidated", "intermediary_owner",
    "use_diplomatic_range", "recipient_bar_text",
}

GATE_KEYS = {
    "has_trait": "trait", "has_government": "government",
    "government_has_flag": "government_flag", "has_doctrine": "doctrine",
    "has_realm_law": "law", "has_perk": "perk", "is_ruler": "state",
    "is_landed": "state", "is_adult": "state", "is_imprisoned": "state",
    "has_dlc_feature": "dlc",
}
NEG = {"NOT", "NOR", "NAND"}


def _pretty_trigger(k):
    """A scripted-trigger macro name is the only honest label we have for the
    condition it encodes; prettify rather than pretend we expanded it."""
    t = (k.removesuffix("_trigger").removeprefix("is_").removeprefix("can_")
          .replace("_", " ").strip())
    return t[:1].upper() + t[1:] if t else k


def gates(block, out, negated=False, depth=0):
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block) or depth > 4:
        return
    for k, _op, v in block:
        if k in GATE_KEYS and isinstance(v, (str, bool)):
            if isinstance(v, bool):
                label = k.replace("_", " ").capitalize()
            else:
                loc = (ck3.loc(f"trait_{v}") if GATE_KEYS[k] == "trait" else ck3.loc(v))
                label = ck3.render_text(loc) if loc else v.replace("_", " ").title()
            out.append({"kind": GATE_KEYS[k], "name": label, "negated": negated})
        elif isinstance(k, str) and v is True and k.endswith("_trigger"):
            out.append({"kind": "condition", "negated": negated,
                        "name": _pretty_trigger(k)})
        elif isinstance(v, (Block, Tagged)):
            gates(v, out, negated or (k in NEG), depth + 1)


def cost_of(blk):
    """(costs dict, has_conditional). Uses the desc-tagged base where present."""
    out = {}
    cb = blk.get("cost")
    if not isinstance(cb, Block):
        return out
    for k, _op, v in cb:
        if k in ("gold", "prestige", "piety", "influence", "renown"):
            n, rules = ck3.resolve_value(v)
            if n is not None:
                out[k] = round(n, 1)
            else:
                base = None
                if isinstance(rules, list):
                    for r in rules:
                        if isinstance(r, dict) and isinstance(r.get("base"), (int, float)):
                            base = r["base"]
                            break
                out[k] = {"varies": True, "base": base}
    return out


def cooldown(blk):
    for field in ("cooldown", "cooldown_against_recipient"):
        cd = blk.get(field)
        if isinstance(cd, Block):
            for unit in ("years", "months", "days"):
                v = cd.get(unit)
                if isinstance(v, (int, float)):
                    return f"{v:g} {unit}"
    return None


def build_interactions():
    cat_names = {}
    for _p, key, blk in ck3.parse_dir(ck3.COMMON / "character_interaction_categories"):
        nm = ck3.loc(key) or ck3.loc(f"{key}_name")
        label = ck3.render_text(nm) if nm else None
        # some category names are character-scoped data functions ("… Vassals")
        if not label or "…" in label:
            label = (key.removeprefix("interaction_category_")
                        .replace("_", " ").title())
        cat_names[key] = label

    unhandled = Counter()
    out = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "character_interactions"):
        if not isinstance(blk, Block):
            continue
        cat = blk.get("category") or ""
        if "debug" in cat.lower():
            continue  # developer console interactions
        name = ck3.loc(key)
        if not name:
            continue  # hidden interactions with no player text
        dlc, _f = ck3.dlc_tag(path, blk)
        g = []
        for field in ("is_shown", "is_valid", "is_valid_showing_failures_only",
                      "can_send", "can_be_picked"):
            gates(blk.get(field), g)
        seen, gg = set(), []
        for x in g:
            sig = (x["kind"], x["name"], x["negated"])
            if sig not in seen:
                seen.add(sig)
                gg.append(x)
        for k in blk.keys():
            if k in SKIP or k.startswith("ai_") or k.startswith("on_"):
                continue
            if k not in ("category", "icon", "desc", "cost", "cooldown", "is_shown",
                         "is_valid", "is_valid_showing_failures_only", "can_send",
                         "can_be_picked", "send_option", "use_hooks", "hook_options",
                         "needs_recipient_to_open", "scheme", "desc_actor",
                         "desc_recipient", "options", "can_be_picked"):
                unhandled[k] += 1
        opts = blk.get_all("send_option")
        out.append({
            "id": key,
            "name": ck3.render_text(name),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "category": blk.get("category"),
            "categoryName": cat_names.get(blk.get("category")) or "Other",
            "cost": cost_of(blk),
            "cooldown": cooldown(blk),
            "usesHooks": bool(blk.get("use_hooks", False)),
            "scheme": blk.get("scheme"),
            "optionCount": len(opts),
            "gates": gg[:8],
            "icon": str(blk.get("icon") or key).removesuffix(".dds"),
            "dlc": dlc,
            "sourceFile": path.name,
        })
    out.sort(key=lambda r: (r["categoryName"] == "Other", r["categoryName"], r["name"]))
    ck3.write_json("interactions.json", out)
    if unhandled:
        print(f"  note: {len(unhandled)} unmodelled fields, top: "
              f"{[k for k, _ in unhandled.most_common(6)]}")


def build_secrets():
    secrets = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "secret_types"):
        if not isinstance(blk, Block):
            continue
        dlc, _f = ck3.dlc_tag(path, blk)
        shunned, criminal = [], []
        gates(blk.get("is_shunned"), shunned)
        gates(blk.get("is_criminal"), criminal)
        for field, bucket in (("is_shunned", shunned), ("is_criminal", criminal)):
            b = blk.get(field)
            if isinstance(b, Block) and not bucket:
                for k2, _o, _v in b:
                    if isinstance(k2, str):
                        bucket.append({"kind": "condition", "negated": False,
                                       "name": _pretty_trigger(k2)})
        name = ck3.loc(key) or ck3.loc(f"{key}_name")
        secrets.append({
            "id": key,
            "name": ck3.render_text(name) if name else key.replace("secret_", "").replace("_", " ").title(),
            "desc": ck3.render_text(ck3.loc(f"{key}_desc") or "") or None,
            "category": blk.get("category"),
            "shunnedWhen": [g["name"] for g in shunned][:6],
            "criminalWhen": [g["name"] for g in criminal][:6],
            "dlc": dlc,
        })
    secrets.sort(key=lambda r: (r["category"] or "", r["name"]))

    hooks = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "hook_types"):
        if not isinstance(blk, Block):
            continue
        name = ck3.loc(key) or ck3.loc(f"{key}_name")
        hooks.append({
            "id": key,
            "name": ck3.render_text(name) if name else key.replace("_", " ").title(),
            "strong": bool(blk.get("strong", False)),
            "perpetual": bool(blk.get("perpetual", False)),
            "expiryDays": blk.get("expiration_days"),
            "requiresSecret": bool(blk.get("requires_secret", False)),
            "dlc": ck3.dlc_tag(path, blk)[0],
        })
    hooks.sort(key=lambda r: (not r["strong"], r["name"]))

    # Explanatory text comes from the game's own concept glossary, not from us.
    concepts = {}
    for key, label in (("hook", "Hooks"), ("strong_hook", "Strong Hooks"),
                       ("weak_hook", "Weak Hooks"), ("secret", "Secrets")):
        desc = ck3.loc(f"game_concept_{key}_desc")
        if desc:
            concepts[key] = {
                "name": ck3.render_text(ck3.loc(f"game_concept_{key}") or label),
                "desc": ck3.render_text(desc),
            }
    ck3.write_json("secrets.json", {"secrets": secrets, "hooks": hooks,
                                    "concepts": concepts})


if __name__ == "__main__":
    build_interactions()
    build_secrets()
