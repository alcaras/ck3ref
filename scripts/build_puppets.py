#!/usr/bin/env python3
"""Build src/data/puppets.json from common/puppets/{types,actions}/.

1.20 (By God Alone). A puppet is a character a ruler can command to take
actions the ruler could not take alone. Per _puppet_types.info and
_puppet_actions.info:

  type    interaction (sets the puppet up), can_have, is_valid, priority,
          actions (each action belongs to exactly one... list per type; the
          same action may appear under several types), asset/animation (UI
          only), color
  action  type = character_interaction | decision | great_project | trigger,
          the linked interaction/decision/great_project, is_enabled (extra
          gate), is_important (highlighted in the intrigue window)

Loc: <type> / <type>_desc; puppet_action_description_<action> for
interaction and trigger actions (decisions and great projects use their own
names). Section headings are the comments in puppet_actions.txt itself.

Must run after build_interactions/decisions/great_projects: links are only
emitted for targets those pages actually list.
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

HANDLED_TYPE = {"interaction", "can_have", "is_valid", "priority", "actions", "color"}
SKIP_TYPE = {
    "asset": "UI icon/background art for the intrigue window",
    "animation": "UI portrait animation",
}
HANDLED_ACTION = {"type", "interaction", "decision", "great_project", "is_enabled", "is_important"}

DATA = Path(__file__).resolve().parent.parent / "src" / "data"

_INTERACTION = re.compile(r"\[GetPlayer\.GetPlayerInteractionName\('(\w+)'\)\]")
_DECISION = re.compile(r"\[GetDecisionWithKey\('(\w+)'\)\.GetName\]")


def text(raw):
    if not raw:
        return None
    raw = _INTERACTION.sub(lambda m: ck3.loc(m.group(1)) or m.group(1), raw)
    raw = _DECISION.sub(lambda m: ck3.loc(m.group(1)) or m.group(1), raw)
    return ck3.render_text(raw)


def site_index(name, path=None):
    """id -> display name for the records a site page lists."""
    try:
        d = json.loads((DATA / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    recs = d[path] if path else d
    return {r["id"]: r.get("name") for r in recs if isinstance(r, dict) and "id" in r}


def trait_name(k):
    return ck3.render_text(ck3.loc(f"trait_{k}") or k.replace("_", " "))


_STRIGGERS: dict | None = None
_DLC_TRIGGERS: dict | None = None


def striggers():
    """The DLC's own scripted triggers (one file), expanded inline so a gate
    like can_have_realm_priest_puppet_trigger reads as its conditions."""
    global _STRIGGERS, _DLC_TRIGGERS
    if _STRIGGERS is None:
        _STRIGGERS, _DLC_TRIGGERS = {}, {}
        st = ck3.COMMON / "scripted_triggers"
        p = st / "pam_scripted_triggers.txt"
        if p.exists():
            _STRIGGERS = {k: b for k, _o, b in ck3.parse_file(p) if isinstance(b, Block)}
        p = st / "00_has_dlc_scripted_triggers.txt"
        if p.exists():
            for k, _o, b in ck3.parse_file(p):
                if isinstance(b, Block) and isinstance(b.get("has_dlc_feature"), str):
                    f = b.get("has_dlc_feature")
                    _DLC_TRIGGERS[k] = ck3.FEATURE_TO_DLC.get(f, f)
    return _STRIGGERS


def _join(parts, word):
    """Join with ' and '/' or ', bracketing any part that uses the other word."""
    other = " or " if word == " and " else " and "
    return word.join(f"({x})" if other in x and len(parts) > 1 else x for x in parts)


def _opaque(parts):
    return all(set(re.split(r"[\s()]+|\bor\b|\band\b|\bnot\b", x)) <= {"", "…"} for x in parts)


TIERS = {"tier_barony": "a barony", "tier_county": "a county", "tier_duchy": "a duchy",
         "tier_kingdom": "a kingdom", "tier_empire": "an empire"}


def describe(blk, who="ruler", depth=0):
    """Readable gate text for the common shapes in is_enabled / can_have.
    Anything else becomes '…' so the page never claims more than it read."""
    parts = []
    yes = ("yes", True)
    for k, op, v in blk:
        if k is None:
            continue
        if isinstance(v, (str, bool)) and k.endswith("_trigger") and v in ("yes", "no", True, False):
            striggers()
            if k in _DLC_TRIGGERS:
                parts.append(f"owns {_DLC_TRIGGERS[k]}" if v in yes else f"does not own {_DLC_TRIGGERS[k]}")
                continue
            if k in _STRIGGERS and depth < 3:
                inner = describe(_STRIGGERS[k], who, depth + 1)
                if _opaque(inner):
                    inner = None  # nothing readable inside: fall through to its name
            if k in _STRIGGERS and depth < 3 and inner:
                if v in yes:
                    parts.extend(inner)
                else:
                    parts.append("not (" + _join(inner, " and ") + ")")
                continue
        if k == "is_available_quick" and isinstance(v, Block):
            parts.append(f"{who} is available")
            parts.extend(describe(v, who, depth))
            continue
        if k in ("adult", "is_clergy", "advanced_ruler") and v in ("yes", "no", True, False):
            label = {"adult": "an adult", "is_clergy": "clergy", "advanced_ruler": "an advanced ruler"}[k]
            parts.append(f"{who} is {label}" if v in yes else f"{who} is not {label}")
            continue
        if k == "government_has_flag" and isinstance(v, str):
            parts.append(f"{v.removeprefix('government_is_').replace('_', ' ')} government")
            continue
        if k == "government_allows" and isinstance(v, str):
            parts.append(f"government allows a {v.replace('_', ' ')}")
            continue
        if k == "highest_held_title_tier" and op == ">=" and v in TIERS:
            parts.append(f"{who} holds at least {TIERS[v]}")
            continue
        if k == "rite" and isinstance(v, Block):
            parts.append(_join(describe(v, "Rite", depth), " and "))
            continue
        if k.startswith("puppet:") and isinstance(v, str) and v.endswith("scope:puppet"):
            t = k[7:]
            parts.append(f"puppet is a {ck3.render_text(ck3.loc(t) or t)}")
            continue
        if k == "rite_has_doctrine" and isinstance(v, str):
            parts.append(f"{who} has {faith_cond.doctrine_cond_name(v)}")
            continue
        if k in ("OR", "AND", "NOR", "NOT") and isinstance(v, Block):
            inner = describe(v, who, depth)
            if not inner:
                continue
            if k == "OR":
                parts.append(_join(inner, " or "))
            elif k == "AND":
                parts.append(_join(inner, " and "))
            else:
                parts.append("not (" + _join(inner, " or ") + ")")
        elif k == "scope:puppet" and isinstance(v, Block):
            parts.append(_join(describe(v, "puppet", depth), " and "))
        elif k == "has_trait" and isinstance(v, str):
            parts.append(f"{who} has {trait_name(v)}")
        elif k == "has_title" and isinstance(v, str) and v.startswith("title:"):
            t = v[6:]
            parts.append(f"{who} holds {ck3.render_text(ck3.loc(t) or t)}")
        elif k == "custom_tooltip" and isinstance(v, Block) and isinstance(v.get("text"), str):
            raw = ck3.loc(v.get("text"))
            parts.append(text(raw) if raw else "…")
        elif k == "always" and v in ("yes", True):
            parts.append("always")
        elif v in ("yes", "no", True, False) and k.endswith("_trigger"):
            # scripted triggers carry no loc; the key is the only name there is
            label = k.removesuffix("_trigger")
            for pre in ("puppet_action_", "pam_"):
                label = label.removeprefix(pre)
            label = label.replace("_", " ")
            parts.append(label if v in ("yes", True) else f"not {label}")
        else:
            parts.append("…")
    return parts


def section_label(raw):
    """'Secular ruler puppet - Legends (CE1 DLC)' -> 'Legends (Community Pack 1 (free))';
    file tags (PAM, CE1, BP2, EP3 …) become DLC names via ck3.PREFIX_TO_DLC."""
    parts = [p.strip() for p in raw.split(" - ")]
    if len(parts) > 1 and parts[0].lower().endswith("puppet"):
        parts = parts[1:]
    dlc = None
    if len(parts) > 1 and parts[-1].lower() in ck3.PREFIX_TO_DLC:
        dlc = ck3.PREFIX_TO_DLC[parts.pop().lower()]
    label = " - ".join(parts)
    m = re.search(r"\s*\((\w+)[^)]*DLC\)$", label)
    if m:
        dlc = ck3.PREFIX_TO_DLC.get(m.group(1).lower(), dlc)
        label = label[:m.start()]
    return label, dlc


def section_map(path):
    """action key -> the '# Heading' comment above it in the file."""
    out, cur = {}, None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^#\s*(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^(\w+)\s*=\s*\{", line)
        if m and cur:
            out[m.group(1)] = cur
    return out


def main():
    unhandled = Counter()
    interactions = site_index("interactions.json")
    decisions = site_index("decisions.json", "decisions")
    projects = site_index("great_projects.json")

    actions = {}
    adir = ck3.COMMON / "puppets" / "actions"
    sections = {}
    for p in sorted(adir.glob("*.txt")):
        sections.update(section_map(p))
    for path, key, blk in ck3.parse_dir(adir):
        if not isinstance(blk, Block):
            continue
        for k, _op, _v in blk:
            if k not in HANDLED_ACTION:
                unhandled[f"action.{k}"] += 1
        kind = blk.get("type") or "character_interaction"
        field = {"character_interaction": "interaction", "decision": "decision",
                 "great_project": "great_project"}.get(kind)
        target = blk.get(field) if field else None
        link = name = None
        if kind == "character_interaction":
            name = interactions.get(target) or ck3.render_text(ck3.loc(target) or "") or None
            link = f"interactions#{target}" if target in interactions else None
        elif kind == "decision":
            name = decisions.get(target) or ck3.render_text(ck3.loc(target) or "") or None
            link = f"decisions#{target}" if target in decisions else None
        elif kind == "great_project":
            name = projects.get(target) or ck3.render_text(ck3.loc(target) or "") or None
            link = f"great-projects#{target}" if target in projects else None
        gate = blk.get("is_enabled")
        gate_parts = describe(gate) if isinstance(gate, Block) else []
        actions[key] = {
            "id": key,
            "kind": kind,
            "target": target,
            "targetName": name,
            "link": link,
            "desc": text(ck3.loc(f"puppet_action_description_{key}")),
            "important": blk.get("is_important") in ("yes", True),
            "gate": gate_parts if gate_parts and gate_parts != ["always"] else [],
            "gateUnmodelled": "…" in " ".join(gate_parts),
            "section": section_label(sections[key])[0] if key in sections else None,
            "dlc": ck3.dlc_tag(path, blk)[0] or (section_label(sections[key])[1] if key in sections else None),
            "usedBy": [],
        }

    types = []
    for path, key, blk in ck3.parse_dir(ck3.COMMON / "puppets" / "types"):
        if not isinstance(blk, Block):
            continue
        for k, _op, _v in blk:
            if k not in HANDLED_TYPE and k not in SKIP_TYPE:
                unhandled[f"type.{k}"] += 1
        al = blk.get("actions")
        keys = [v for k, _o, v in al if k is None] if isinstance(al, Block) else []
        missing = [a for a in keys if a not in actions]
        for a in keys:
            if a in actions:
                actions[a]["usedBy"].append(key)
        col = blk.get("color")
        rgb = None
        if isinstance(col, Block):
            nums = [v for k, _o, v in col if k is None and isinstance(v, (int, float))]
            if len(nums) >= 3:
                rgb = "#" + "".join(f"{round(max(0, min(1, x)) * 255):02x}" for x in nums[:3])
        ch = blk.get("can_have")
        iv = blk.get("is_valid")
        inter = blk.get("interaction")
        icon = None
        for a in blk.get_all("asset"):
            if isinstance(a, Block) and a.get("trigger") is None and isinstance(a.get("icon"), str):
                icon = Path(a.get("icon")).stem
        types.append({
            "id": key,
            "name": ck3.render_text(ck3.loc(key) or key),
            "desc": text(ck3.loc(f"{key}_desc")),
            "interaction": inter,
            "interactionName": interactions.get(inter) or ck3.render_text(ck3.loc(inter) or "") or None,
            "interactionLink": f"interactions#{inter}" if inter in interactions else None,
            "canHave": describe(ch) if isinstance(ch, Block) else [],
            "isValid": describe(iv) if isinstance(iv, Block) else [],
            "color": rgb,
            "icon": icon,
            "actions": [a for a in keys if a in actions],
            "missingActions": missing,
            "dlc": ck3.dlc_tag(path, blk)[0],
        })

    # an action whose name we cannot resolve falls back to its key, labelled
    for a in actions.values():
        a["name"] = a["targetName"] or (a["desc"] if a["kind"] == "trigger" else None) \
            or a["id"].removeprefix("puppet_action_").removeprefix("puppet_trigger_").replace("_", " ")

    concept = ck3.loc("game_concept_puppet_desc")
    out = {
        "types": types,
        "actions": list(actions.values()),
        "about": ck3.render_text(concept) if concept else None,
    }
    ck3.write_json("puppets.json", out)
    orphan = [a for a in actions.values() if not a["usedBy"]]
    print(f"  {len(types)} puppet types, {len(actions)} actions "
          f"({sum(1 for a in actions.values() if a['link'])} linked, {len(orphan)} unused)")
    for t in types:
        if t["missingActions"]:
            print(f"⚠ {t['id']} lists undefined actions: {t['missingActions']}")
    if unhandled:
        print("⚠ unhandled puppet fields (add to HANDLED or SKIP):")
        for k, n in unhandled.most_common():
            print(f"    {k}: {n}")


if __name__ == "__main__":
    main()
