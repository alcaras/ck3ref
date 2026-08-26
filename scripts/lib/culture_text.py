"""Static pre-resolution for culture-page loc strings.

The culture files lean on data functions ck3.render_text can't see through,
but each has a static answer in the game files: icon refs render as nothing,
SelectLocalization/AddLocalizationIf take their DLC branch (we document DLC
content), entity GetName/GetTypeName variants have plain loc chains, script
values resolve statically, and GetPlayer.Custom has a declared fallback in
customizable_localization. Numeric parameters inject their own value via
$VALUE$. Everything unmatched still falls through to render_text's honest
"…" + unresolved counting.

Used by build_traditions / build_innovations / build_pillars only.
"""

import re

import ck3
from ck3 import Block

_ICON_REF = re.compile(r"\[\w+_i\]")
_SELECT_LOC = re.compile(
    r"\[SelectLocalization\(\s*HasDlcFeature\(\s*'\w+'\s*\)\s*,\s*'(\w*)'\s*,\s*'(\w*)'\s*\)(\|\w+)?\]")
_ADD_LOC_IF = re.compile(r"\[AddLocalizationIf\(\s*[^,\]]+,\s*'(\w+)'\s*\)(\|\w+)?\]")
_OBLIGATION = re.compile(
    r"\[GetSubjectContractType\(\s*'\w+'\s*\)\.GetObligationName(?:Short)?\(\s*'(\w+)'\s*\)(\|\w+)?\]")
_PLAYER_CUSTOM = re.compile(r"\[GetPlayer\.Custom\(\s*'(\w+)'\s*\)(\|\w+)?\]")
_SCHEME = re.compile(r"\[GetScheme\(\s*'(\w+)'\s*\)\.GetTypeName(\|\w+)?\]")
_BUILDING = re.compile(r"\[GetBuilding\(\s*'(\w+)'\s*\)\.GetTypeName(\|\w+)?\]")
_DOMICILE_B = re.compile(r"\[GetDomicileBuilding\(\s*'(\w+)'\s*\)\.\w+(\|\w+)?\]")
_MODIFIER = re.compile(r"\[GetModifier\(\s*'(\w+)'\s*\)\.GetName\w*(\|\w+)?\]")
_DOCTRINE_BASE = re.compile(r"\[GetFaithDoctrine\(\s*'(\w+)'\s*\)\.GetBaseName(\|\w+)?\]")
_TRAIT = re.compile(r"\[GetTrait\(\s*'(\w+)'\s*\)\.GetName\([^)]*\)(\|\w+)?\]")
_DECISION = re.compile(r"\[GetDecisionWithKey\(\s*'(\w+)'\s*\)\.GetName(\|\w+)?\]")
_SCRIPT_VALUE = re.compile(r"\[EmptyScope\.ScriptValue\(\s*'(\w+)'\s*\)(\|[^\]]+)?\]")
_GLOSSARY = re.compile(r"\[Glossary\(\s*'([^']+)'\s*,\s*'\w+'\s*\)(\|\w+)?\]")
_COLLECTIVE = re.compile(r"\[GetCultureByKey\(\s*'(\w+)'\s*\)\.GetCollectiveNoun(\|\w+)?\]")
_INTERACTION = re.compile(r"\[GetPlayer\.GetPlayerInteractionName\(\s*'(\w+)'\s*\)(\|\w+)?\]")
_HEAD_DET_CONCEPT = re.compile(r"\[head_determination\|E\]")  # not a game_concept; no loc

_custom_loc_fallbacks: dict | None = None
_custom_loc_defs: dict | None = None


def _fallbacks():
    """customizable_localization name -> its declared fallback loc key.

    Entries can also inherit: `parent = X` + `suffix = "_plural"` means this
    entry's keys are the parent's with the suffix appended; chains recurse.
    """
    global _custom_loc_fallbacks, _custom_loc_defs
    if _custom_loc_fallbacks is None:
        _custom_loc_defs = {}
        for _p, name, blk in ck3.parse_dir(ck3.COMMON / "customizable_localization"):
            if isinstance(blk, Block):
                _custom_loc_defs[name] = blk
        _custom_loc_fallbacks = {}

        def resolve(name, depth=0):
            if name in _custom_loc_fallbacks or depth > 6:
                return _custom_loc_fallbacks.get(name)
            blk = _custom_loc_defs.get(name)
            if blk is None:
                return None
            for t in blk.get_all("text"):
                if isinstance(t, Block) and t.get("fallback") is True:
                    lk = t.get("localization_key")
                    if isinstance(lk, str):
                        _custom_loc_fallbacks[name] = lk
                        return lk
            parent = blk.get("parent")
            if isinstance(parent, str):
                base = resolve(parent, depth + 1)
                if base:
                    lk = base + (blk.get("suffix") or "")
                    _custom_loc_fallbacks[name] = lk
                    return lk
            return None

        for name in list(_custom_loc_defs):
            resolve(name)
    return _custom_loc_fallbacks


def _pretty(key):
    return key.replace("_", " ").title()


def static_value(name):
    """Script value -> number, folding pure-arithmetic chains that
    ck3.resolve_value reports as rule structures (value/add/multiply/...)."""
    n, rules = ck3.resolve_value(name)
    if n is not None:
        return n
    if not isinstance(rules, list):
        return None
    acc = None
    for r in rules:
        if not isinstance(r, dict) or len(r) != 1:
            return None
        (op, v), = r.items()
        if not isinstance(v, (int, float)):
            return None
        if op == "base":
            acc = v
        elif acc is None:
            return None
        elif op == "add":
            acc += v
        elif op == "subtract":
            acc -= v
        elif op == "multiply":
            acc *= v
        elif op == "divide" and v:
            acc /= v
        else:
            return None
    return acc


def render_modifier(key, value):
    """ck3.render_modifier, but with the modifier's display name run through
    the same static pre-resolution (MOD_* loc can embed icon refs and
    $knight$ chains). Falls back to ck3's version (and its missing-format
    reporting) when no loc exists."""
    raw = _chain(f"MOD_{key.upper()}", f"MOD_{key.upper()}_PREFIX", key)
    if raw is None:
        return ck3.render_modifier(key, value)
    name = ck3.render_text(expand(raw))
    fmt = ck3.modifier_formats().get(key, {})
    if isinstance(value, bool):
        return name
    if not isinstance(value, (int, float)):
        return f"{name}: {value}"
    num = value * 100 if fmt.get("percent") and not fmt.get("already_percent") else value
    decimals = fmt.get("decimals", 0)
    magnitude = f"{num:+.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{num:+.0f}"
    pct = "%" if fmt.get("percent") or fmt.get("already_percent") else ""
    return f"{magnitude}{pct} {name}"


def _chain(*keys):
    for k in keys:
        if not k:
            continue
        v = ck3.loc(k)
        if v is not None:
            return v
    return None


def pre_resolve(raw):
    """Substitute statically-answerable data functions before render_text.

    Substituted loc can itself contain data functions (SelectLocalization
    inlining a string with icon refs), so iterate to a fixpoint.
    """
    for _ in range(4):
        out = _pre_resolve_once(raw)
        if out == raw:
            break
        raw = out
    return raw


def _pre_resolve_once(raw):
    raw = _ICON_REF.sub("", raw)
    raw = _SELECT_LOC.sub(lambda m: "" if m.group(1) in ("", "blank_line")
                          else (ck3.loc(m.group(1)) or ""), raw)
    raw = _ADD_LOC_IF.sub(lambda m: ck3.loc(m.group(1)) or "", raw)
    raw = _OBLIGATION.sub(lambda m: _chain(m.group(1), f"{m.group(1)}_name") or _pretty(m.group(1)), raw)
    raw = _SCHEME.sub(lambda m: _chain(m.group(1), f"{m.group(1)}_name") or _pretty(m.group(1)), raw)
    raw = _BUILDING.sub(lambda m: _chain(f"building_{m.group(1)}", m.group(1)) or _pretty(m.group(1)), raw)
    raw = _DOMICILE_B.sub(lambda m: _chain(f"{m.group(1)}_domicile_building", m.group(1)) or _pretty(m.group(1)), raw)
    raw = _MODIFIER.sub(lambda m: _chain(m.group(1), f"{m.group(1)}_name") or _pretty(m.group(1)), raw)
    raw = _DOCTRINE_BASE.sub(lambda m: _chain(f"{m.group(1)}_name", m.group(1)) or _pretty(m.group(1)), raw)
    raw = _TRAIT.sub(lambda m: _chain(f"trait_{m.group(1)}", m.group(1)) or _pretty(m.group(1)), raw)
    raw = _DECISION.sub(lambda m: _chain(m.group(1), f"{m.group(1)}_name") or _pretty(m.group(1)), raw)
    raw = _GLOSSARY.sub(lambda m: m.group(1), raw)
    raw = _COLLECTIVE.sub(lambda m: _chain(f"{m.group(1)}_collective_noun", m.group(1)) or _pretty(m.group(1)), raw)
    raw = _INTERACTION.sub(lambda m: "" , raw)  # interaction names are themselves dynamic; drop from prose
    raw = _HEAD_DET_CONCEPT.sub("Head Determination", raw)

    def script_value(m):
        n = static_value(m.group(1))
        if n is None:
            return m.group(0)  # conditional: leave for render_text's honest "…"
        fmt = m.group(2) or ""
        num = f"{n:g}"
        return f"{num}%" if "%" in fmt else num

    raw = _SCRIPT_VALUE.sub(script_value, raw)

    def player_custom(m):
        fb = _fallbacks().get(m.group(1))
        return (ck3.loc(fb) or m.group(0)) if fb else m.group(0)

    raw = _PLAYER_CUSTOM.sub(player_custom, raw)
    return raw


_DOLLAR = re.compile(r"\$([\w.\-|]+)\$")


def expand(raw, _depth=0):
    """Inline $key$ chains ourselves so pre_resolve sees every level; keys
    without loc (e.g. $VALUE$ placeholders) are left for the caller."""
    raw = pre_resolve(raw)
    raw = raw.replace("$EFFECT_LIST_BULLET$", "• ")  # UI bullet glyph, no loc
    if _depth > 8:
        return raw

    def sub(m):
        inner = m.group(1).split("|")[0]
        v = ck3.loc(inner)
        return m.group(0) if v is None else expand(v, _depth + 1)

    return _DOLLAR.sub(sub, raw)


def render(key, value=None):
    """Loc key -> display text; numeric `value` fills the $VALUE$ placeholder."""
    raw = ck3.loc(key)
    if raw is None:
        return None
    raw = expand(raw)
    if value is not None:
        vs = (f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool)
              else str(value))
        raw = re.sub(r"\$VALUE(\|\w+)?\$", vs, raw)
    return ck3.render_text(raw)
