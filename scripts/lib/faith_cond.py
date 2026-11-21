"""Faith-side conditions shared by builders whose modifier blocks are gated on
a doctrine or a rite parameter (1.20 `rite_modifier`, `faith_character_modifier`,
`province_rite_modifier`, `county_rite_modifier`).

Everything here is read from `reference/` at build time:

- doctrine / tenet display names: `<key>_descriptive_name` (the game's own
  name for use inside a condition, e.g. "Encouraged Pilgrimages"), else
  `<key>_name`, else the key;
- rite parameters: the `parameters = { … }` blocks of
  `common/religion/doctrine_types` and `common/religion/tenet_types` tell us
  which doctrines/tenets grant a parameter; `doctrine_parameter_<p>` is the
  game's own description of what the parameter does.
"""

from collections import defaultdict

import ck3
from ck3 import Block

_param_sources: dict | None = None


def doctrine_cond_name(key):
    """Doctrine or tenet name as the game words it inside a condition."""
    for k in (f"{key}_descriptive_name", f"{key}_name", key):
        raw = ck3.loc(k)
        if raw:
            t = ck3.render_text(raw)
            if t:
                return t
    return key.replace("_", " ")


def _sources():
    global _param_sources
    if _param_sources is None:
        _param_sources = defaultdict(list)
        for sub in ("doctrine_types", "tenet_types"):
            for _p, key, blk in ck3.parse_dir(ck3.COMMON / "religion" / sub):
                if not isinstance(blk, Block):
                    continue
                for pb in blk.get_all("parameters"):
                    if not isinstance(pb, Block):
                        continue
                    for k, _op, v in pb:
                        name = k if k is not None else v
                        if isinstance(name, str) and key not in _param_sources[name]:
                            _param_sources[name].append(key)
    return _param_sources


def rite_param_sources(param):
    """Display names of the doctrines/tenets that grant a rite parameter."""
    out = []
    for key in _sources().get(param, []):
        n = doctrine_cond_name(key)
        if n not in out:
            out.append(n)
    return out


def rite_param_desc(param):
    """The game's description of a doctrine parameter, or None."""
    raw = ck3.loc(f"doctrine_parameter_{param}")
    return ck3.render_text(raw) if raw else None


def rite_param_label(param):
    """Short condition label: 'Rite has A, B or C' (falls back to the raw
    parameter key when no doctrine/tenet in the files grants it)."""
    names = rite_param_sources(param)
    if not names:
        return f"Rite has parameter {param}"
    if len(names) == 1:
        return f"Rite has {names[0]}"
    return "Rite has " + ", ".join(names[:-1]) + " or " + names[-1]
