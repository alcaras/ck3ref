"""Shared helpers for the religion build scripts (faiths, doctrines, holy sites).

Religion in 1.21 is three tiers: religion -> faith -> rite. Faiths live in
common/religion/faith_types/, rites in rite_types/, core tenets in
tenet_types/ (no longer a doctrine group). Kept out of ck3.py on purpose.
"""

from __future__ import annotations

import ck3
from ck3 import Block, Tagged

RELIGION = ck3.COMMON / "religion"
FAITH_HISTORY = ck3.REF / "game" / "history" / "faiths"


def concept(key: str) -> str | None:
    """Rendered game_concept_<key>_desc text (bullets kept as '• ')."""
    raw = ck3.loc(f"game_concept_{key}_desc")
    if not raw:
        return None
    raw = raw.replace("$EFFECT_LIST_BULLET$", "• ")
    return ck3.render_text(raw)


def concept_name(key: str) -> str:
    raw = ck3.loc(f"game_concept_{key}")
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


_defines: Block | None = None


def define(section: str, key: str):
    """A value from common/defines/00_defines.txt (read at build time)."""
    global _defines
    if _defines is None:
        _defines = ck3.parse_file(ck3.COMMON / "defines" / "00_defines.txt")
    sec = _defines.get(section)
    if not isinstance(sec, Block):
        raise KeyError(section)
    v = sec.get(key)
    if v is None:
        raise KeyError(f"{section}.{key}")
    if isinstance(v, Block):
        return list(v.values())
    return v


def block_list(v) -> list:
    """`{ a b c }` -> [a, b, c]; anything else -> []."""
    if isinstance(v, Tagged):
        v = v.block
    if not isinstance(v, Block):
        return []
    return [x for x in v.values() if isinstance(x, str)]


def _desc_keys(v, out):
    if isinstance(v, Tagged):
        v = v.block
    if isinstance(v, str):
        out.append(v)
        return
    if not isinstance(v, Block):
        return
    for k, _op, val in v:
        if k == "desc" and isinstance(val, str):
            out.append(val)
        elif isinstance(val, (Block, Tagged)):
            _desc_keys(val, out)


def dynamic_text(blk, field: str, default_key: str):
    """(primary, variants) for a dynamic name/desc block.

    The primary is the LAST (untriggered fallback) entry, per CLAUDE.md;
    the default `<key>_<field>` key is used when the block is absent."""
    keys: list[str] = []
    _desc_keys(blk.get(field) if blk is not None else None, keys)
    if not keys:
        keys = [default_key]
    rendered = []
    for k in keys:
        raw = ck3.loc(k)
        if raw:
            t = ck3.render_text(raw)
            if t and t not in rendered:
                rendered.append(t)
    if not rendered:
        return None, []
    # fallback (last) first, the triggered variants after it
    primary = rendered[-1]
    return primary, [t for t in rendered if t != primary]


_tenets: dict | None = None


def tenet_blocks() -> dict:
    global _tenets
    if _tenets is None:
        _tenets = {k: b for _p, k, b in ck3.parse_dir(RELIGION / "tenet_types")
                   if isinstance(b, Block)}
    return _tenets


def tenet_name(key: str) -> str:
    name, _ = dynamic_text(tenet_blocks().get(key), "name", f"{key}_name")
    return name or key.replace("_", " ").title()


_doctrines: dict | None = None


def doctrine_blocks() -> dict:
    global _doctrines
    if _doctrines is None:
        _doctrines = {k: b for _p, k, b in ck3.parse_dir(RELIGION / "doctrine_types")
                      if isinstance(b, Block)}
    return _doctrines


def doctrine_name(key: str) -> str:
    if key in tenet_blocks():
        return tenet_name(key)
    name, _ = dynamic_text(doctrine_blocks().get(key), "name", f"{key}_name")
    if name:
        return name
    raw = ck3.loc(key)
    return ck3.render_text(raw) if raw else key.replace("_", " ").title()


def doctrine_group_of() -> dict:
    """doctrine key -> doctrine_group_type (declared on the doctrine itself)."""
    return {k: b.get("doctrine_group_type") for k, b in doctrine_blocks().items()}


def title_name(key: str | None) -> str | None:
    if not key:
        return None
    raw = ck3.loc(key)
    return ck3.render_text(raw) if raw else None


def merge_doctrines(layers: list[list[str]]) -> list[str]:
    """Apply doctrine layers in order (religion, faith, rite...): a later
    layer's doctrine replaces an earlier one in the same doctrine group, and
    within a layer the later definition wins (order of definition)."""
    g = doctrine_group_of()
    by_group: dict = {}
    order: list = []
    for layer in layers:
        for d in layer:
            grp = g.get(d) or f"?{d}"
            if grp not in by_group:
                order.append(grp)
            by_group[grp] = d
    return [by_group[grp] for grp in order]
