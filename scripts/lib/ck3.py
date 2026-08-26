"""Shared CK3 data-access layer for build scripts.

- Jomini script parser (text form only; no binary saves)
- file-local @constants and @[a + 2*b] expression evaluation
- localization loader + mini-language renderer (v1)
- modifier formatter driven by common/modifier_definition_formats
- script_value resolver (static scalars + named chains; conditional -> rule dicts)
- DLC provenance tagger (filename prefix + has_dlc_feature)

All reads go through reference/ (repo-local, populated by scripts/sync.sh).
Never point this at the Dropbox mirror directly — see sync.sh header.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "reference"
COMMON = REF / "game" / "common"
LOC_DIR = REF / "game" / "localization" / "english"
CACHE = ROOT / ".cache"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class Block:
    """An ordered multimap: list of (key, op, value) triples.

    Loose array elements (e.g. color lists, `counters = { skirmishers }`) are
    stored as (None, None, value).
    """

    __slots__ = ("triples",)

    def __init__(self, triples=None):
        self.triples = triples if triples is not None else []

    def items(self):
        return [(k, v) for k, _op, v in self.triples if k is not None]

    def values(self):
        return [v for k, _op, v in self.triples if k is None]

    def get(self, key, default=None):
        for k, _op, v in self.triples:
            if k == key:
                return v
        return default

    def get_all(self, key):
        return [v for k, _op, v in self.triples if k == key]

    def keys(self):
        return [k for k, _op, v in self.triples if k is not None]

    def has(self, key):
        return any(k == key for k, _op, _v in self.triples)

    def __iter__(self):
        return iter(self.triples)

    def __len__(self):
        return len(self.triples)

    def __repr__(self):
        return f"Block({self.triples!r})"


class Tagged:
    """A tagged block like `rgb { 255 0 0 }` or `hsv { 0.1 0.5 0.9 }`."""

    __slots__ = ("tag", "block")

    def __init__(self, tag, block):
        self.tag = tag
        self.block = block

    def __repr__(self):
        return f"Tagged({self.tag}, {self.block!r})"


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>\#[^\n]*)
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<atexpr>@\[[^\]]*\])
  | (?P<op><=|>=|==|!=|\?=|=|<|>)
  | (?P<brace>[{}])
  | (?P<ident>[^\s{}=<>!?"\#]+)
    """,
    re.VERBOSE,
)

_EXPR_OK = re.compile(r"^[\w+\-*/(). ]*$")


def _tokenize(text):
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        val = m.group()
        tokens.append((kind, val))
    return tokens


class Parser:
    def __init__(self, text, path="<string>"):
        self.tokens = _tokenize(text)
        self.i = 0
        self.path = path
        self.constants = {}

    def _peek(self, offset=0):
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else (None, None)

    def _next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _resolve(self, kind, val):
        """Turn a token into a python value; substitute @constants."""
        if kind == "str":
            return val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "atexpr":
            return self._eval_expr(val[2:-1])
        if val.startswith("@") and len(val) > 1:
            name = val[1:]
            if name in self.constants:
                return self.constants[name]
            return val  # unknown constant: keep symbolic
        return _coerce(val)

    def _eval_expr(self, expr):
        if not _EXPR_OK.match(expr):
            return f"@[{expr}]"
        def sub(m):
            name = m.group(0)
            v = self.constants.get(name)
            return repr(v) if isinstance(v, (int, float)) else name
        substituted = re.sub(r"[A-Za-z_]\w*", sub, expr)
        try:
            return eval(substituted, {"__builtins__": {}}, {})  # noqa: S307 - charset-validated arithmetic
        except Exception:
            return f"@[{expr}]"

    def parse(self):
        return self._parse_block(top=True)

    def _parse_block(self, top=False):
        triples = []
        while self.i < len(self.tokens):
            kind, val = self._peek()
            if kind == "brace" and val == "}":
                if top:
                    self._next()  # stray closing brace at top level: skip
                    continue
                self._next()
                return Block(triples)
            nkind, nval = self._peek(1)
            if nkind == "op":
                self._next()
                _opk, op = self._next()
                vkind, vval = self._peek()
                if vkind == "brace" and vval == "{":
                    self._next()
                    value = self._parse_block()
                elif vkind == "ident" and self._peek(1) == ("brace", "{"):
                    tag = vval
                    self._next()
                    self._next()
                    value = Tagged(tag, self._parse_block())
                else:
                    vk, vv = self._next()
                    value = self._resolve(vk, vv)
                key = val if kind != "str" else val[1:-1]
                if top and isinstance(key, str) and key.startswith("@") and not isinstance(value, (Block, Tagged)):
                    self.constants[key[1:]] = value
                else:
                    triples.append((key, op, value))
            elif kind == "brace" and val == "{":
                self._next()
                triples.append((None, None, self._parse_block()))
            else:
                self._next()
                triples.append((None, None, self._resolve(kind, val)))
        if not top:
            raise ValueError(f"{self.path}: unexpected EOF inside block")
        return Block(triples)


_DATE_RE = re.compile(r"^\d{1,4}\.\d{1,2}\.\d{1,2}$")


def _coerce(val):
    if val == "yes":
        return True
    if val == "no":
        return False
    if _DATE_RE.match(val):
        return val
    try:
        if re.match(r"^-?\d+$", val):
            return int(val)
        if re.match(r"^-?\d*\.\d+$", val):
            return float(val)
    except ValueError:
        pass
    return val


def parse_file(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return Parser(text, str(path)).parse()


def parse_dir(dirpath, glob="*.txt"):
    """Parse every file in a category dir. Returns list of (path, key, block)."""
    out = []
    for p in sorted(Path(dirpath).glob(glob)):
        if p.name.startswith("_"):
            continue  # _*.info schema docs and .lookup indexes
        blk = parse_file(p)
        for key, _op, val in blk:
            if key is not None and isinstance(val, (Block, Tagged)):
                out.append((p, key, val))
    return out


# ---------------------------------------------------------------------------
# Localization
# ---------------------------------------------------------------------------

_LOC_LINE = re.compile(r'^\s*([\w\-.\'’]+):\d*\s*"(.*)"[^"]*$')
_loc_cache: dict | None = None


def load_loc(force=False):
    """All english loc keys -> raw strings, cached to .cache/loc.json."""
    global _loc_cache
    if _loc_cache is not None and not force:
        return _loc_cache
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / "loc.json"
    files = sorted(LOC_DIR.rglob("*.yml"))
    newest = max((f.stat().st_mtime for f in files), default=0)
    if cache_file.exists() and cache_file.stat().st_mtime >= newest and not force:
        _loc_cache = json.loads(cache_file.read_text(encoding="utf-8"))
        return _loc_cache
    loc = {}
    for f in files:
        for line in f.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            m = _LOC_LINE.match(line)
            if m:
                loc[m.group(1)] = m.group(2)
    cache_file.write_text(json.dumps(loc, ensure_ascii=False), encoding="utf-8")
    _loc_cache = loc
    print(f"  (loc cache rebuilt: {len(loc):,} keys)")
    return loc


def loc(key, default=None):
    return load_loc().get(key, default)


# --- mini-language renderer -------------------------------------------------
# Policy: fully resolve $key$ chains and concept links; strip formatting tags
# and icons; data functions [Scope.GetX] have no static answer -> placeholder,
# counted so the audit can track unresolved density.

_UNRESOLVED: list[str] = []

_TAG_OPEN = re.compile(r"#\w+([;:!]\w+)*[ \n]")  # e.g. "#V ", "#bold;italic "
_TAG_CLOSE = re.compile(r"#!")
_ICON = re.compile(r"@(\w+)!")
_DOLLAR = re.compile(r"\$([\w.\-|]+)\$")
_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_CONCEPT_FN = re.compile(r"^Concept\(\s*'(\w+)'\s*,\s*'([^']*)'\s*\)(\|\w+)?$")
# Statically resolvable data functions: [GetMaA('kheshig').GetName] etc.
_GET_ENTITY = re.compile(
    r"^Get(MaA|Trait|Doctrine|Perk|Faith|Religion|Culture|Innovation|Title|Scheme|"
    r"Dynasty|House|Terrain|Building|Law|Focus|Lifestyle|Legacy|Decision|Activity|"
    r"CasusBelli|CouncilTask|CourtPosition|Modifier|Nickname|Trigger|Accolade\w*)"
    r"\(\s*'([\w.-]+)'\s*\)\.GetName(\([^)]*\))?(\|\w+)?$"
)
_SIMPLE_CONCEPT = re.compile(r"^(\w+)\|E$", re.IGNORECASE)

_concepts: set | None = None


def concept_keys():
    global _concepts
    if _concepts is None:
        _concepts = set()
        gc_dir = COMMON / "game_concepts"
        if gc_dir.exists():
            for _p, key, blk in parse_dir(gc_dir):
                _concepts.add(key)
                aliases = blk.get("alias")
                if isinstance(aliases, Block):
                    _concepts.update(a for a in aliases.values() if isinstance(a, str))
        _concepts = _concepts
    return _concepts


def render_text(s, _depth=0):
    """Render a loc string to plain display text (v1: links become plain names)."""
    if not isinstance(s, str) or _depth > 8:
        return s

    def dollar(m):
        inner = m.group(1).split("|")[0]
        val = loc(inner)
        if val is None:
            _UNRESOLVED.append(f"$${inner}$$")
            return inner
        return render_text(val, _depth + 1)

    s = _DOLLAR.sub(dollar, s)

    def bracket(m):
        inner = m.group(1).strip()
        cm = _CONCEPT_FN.match(inner)
        if cm:
            return cm.group(2)
        gm = _GET_ENTITY.match(inner)
        if gm:
            k = gm.group(2)
            v = loc(k) or loc(f"{k}_name") or loc(f"trait_{k}")
            if v is not None:
                return render_text(v, _depth + 1)
        sm = _SIMPLE_CONCEPT.match(inner)
        if sm and sm.group(1) in concept_keys():
            name = loc("game_concept_" + sm.group(1)) or loc(sm.group(1))
            return render_text(name, _depth + 1) if name else sm.group(1).replace("_", " ")
        _UNRESOLVED.append(inner)
        return "…"

    s = _BRACKET.sub(bracket, s)
    s = _ICON.sub("", s)
    s = _TAG_OPEN.sub("", s)
    s = _TAG_CLOSE.sub("", s)
    s = s.replace("\\n", "\n")
    return re.sub(r"[ \t]+", " ", s).strip()


def unresolved_report():
    return list(_UNRESOLVED)


# ---------------------------------------------------------------------------
# Modifier formatting
# ---------------------------------------------------------------------------

_mod_formats: dict | None = None


def modifier_formats():
    global _mod_formats
    if _mod_formats is None:
        _mod_formats = {}
        for _p, key, blk in parse_dir(COMMON / "modifier_definition_formats"):
            if isinstance(blk, Block):
                _mod_formats[key] = {
                    "decimals": blk.get("decimals", 0),
                    "percent": bool(blk.get("percent", False)),
                    "already_percent": bool(blk.get("already_percent", False)),
                    "prefix": blk.get("prefix"),
                    "suffix": blk.get("suffix"),
                }
    return _mod_formats


_MISSING_MOD: set = set()


def modifier_name(key):
    """Game-authored display name for a modifier key."""
    for cand in (f"MOD_{key.upper()}", f"MOD_{key.upper()}_PREFIX", key):
        v = loc(cand)
        if v is not None:
            return render_text(v)
    _MISSING_MOD.add(key)
    return key.replace("_", " ").title()


def render_modifier(key, value):
    """One modifier line, phrased the way the game renders it."""
    fmt = modifier_formats().get(key, {})
    name = modifier_name(key)
    if isinstance(value, bool):
        return name
    if not isinstance(value, (int, float)):
        return f"{name}: {value}"
    num = value * 100 if fmt.get("percent") and not fmt.get("already_percent") else value
    decimals = fmt.get("decimals", 0)
    magnitude = f"{num:+.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{num:+.0f}"
    pct = "%" if fmt.get("percent") or fmt.get("already_percent") else ""
    return f"{magnitude}{pct} {name}"


def missing_modifier_report():
    return sorted(_MISSING_MOD)


# ---------------------------------------------------------------------------
# Script values
# ---------------------------------------------------------------------------

_script_values: dict | None = None


def script_values():
    global _script_values
    if _script_values is None:
        _script_values = {}
        for p in sorted((COMMON / "script_values").glob("*.txt")):
            if p.name.startswith("_"):
                continue
            blk = parse_file(p)
            for key, _op, val in blk:
                if key is not None:
                    _script_values[key] = val
    return _script_values


def resolve_value(v, _depth=0):
    """Resolve to a number where statically possible.

    Returns (number, None) for static values, or (None, rules) where rules is a
    human-readable structure for conditional values. Honest fallback: never
    collapse a conditional value to a single number.
    """
    if _depth > 12:
        return None, str(v)
    if isinstance(v, bool):
        return None, str(v)
    if isinstance(v, (int, float)):
        return v, None
    if isinstance(v, str):
        sv = script_values().get(v)
        if sv is not None:
            return resolve_value(sv, _depth + 1)
        return None, v
    if isinstance(v, Block):
        base = v.get("value")
        if base is not None and len(v.items()) == 1:
            return resolve_value(base, _depth + 1)
        # conditional / arithmetic chain -> structured rules
        rules = []
        for k, _op, val in v:
            if k is None:
                continue
            if k == "value":
                n, r = resolve_value(val, _depth + 1)
                rules.append({"base": n if n is not None else r})
            elif k in ("add", "multiply", "subtract", "divide", "min", "max"):
                n, r = resolve_value(val, _depth + 1)
                rules.append({k: n if n is not None else r})
            elif k == "if" and isinstance(val, Block):
                rules.append({"if": _describe_trigger(val.get("limit")),
                              "then": [f"{kk} {_short(vv)}" for kk, _o, vv in val if kk not in (None, "limit")]})
            else:
                rules.append({k: _short(val)})
        return None, rules
    return None, str(v)


def _short(v):
    if isinstance(v, (Block, Tagged)):
        return "…"
    n, r = resolve_value(v) if isinstance(v, str) else (v, None)
    return n if n is not None else str(v)


def _describe_trigger(limit):
    if not isinstance(limit, Block):
        return str(limit)
    parts = []
    for k, op, v in limit:
        if isinstance(v, (Block, Tagged)):
            parts.append(f"{k} …")
        else:
            parts.append(f"{k} {op} {v}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# DLC provenance
# ---------------------------------------------------------------------------

# Filename prefixes and has_dlc_feature flags both map (many-to-one) onto DLCs.
# No table ships in the data; this map is hand-maintained. audit.py fails the
# build when a new feature flag or prefix shows up unmapped.
FEATURE_TO_DLC = {
    "royal_court": "The Royal Court",
    "court_artifacts": "The Royal Court",
    "diverge_culture": "The Royal Court",
    "hybridize_culture": "The Royal Court",
    "the_northern_lords": "Northern Lords",
    "the_fate_of_iberia": "Fate of Iberia",
    "friends_and_foes": "Friends & Foes",
    "tours_and_tournaments": "Tours & Tournaments",
    "advanced_activities": "Tours & Tournaments",
    "accolades": "Tours & Tournaments",
    "wards_and_wardens": "Wards & Wardens",
    "legacy_of_persia": "Legacy of Persia",
    "legends_of_the_dead": "Legends of the Dead",
    "legends": "Legends of the Dead",
    "roads_to_power": "Roads to Power",
    "landless_playable": "Roads to Power",
    "admin_gov": "Roads to Power",
    "wandering_nobles": "Wandering Nobles",
    "khans_of_the_steppe": "Khans of the Steppe",
    "all_under_heaven": "All Under Heaven",
    "coronations": "Crowns of the World",
    "crowns_of_the_world": "Crowns of the World",
    "holy_buildings": "Medieval Monuments",
    "medieval_monuments": "Medieval Monuments",
    "east_asian_wonders": "All Under Heaven",
    # cosmetic packs — gate attire/music/CoA only; tagged for completeness
    "arctic_attire": "Northern Lords",
    "celestial_court_attire": "All Under Heaven",
    "north_african_attire": "Legacy of Persia",
    "north_pacific_attire": "Khans of the Steppe",
    "west_slavic_attire": "West Slavic Attire",
    "high_medieval_warfare_attire": "Crowns of the World",
    "elegance_of_the_empire": "Elegance of the Empire",
    "symbols_of_authority": "Symbols of Authority",
    "songs_of_the_realm": "Songs of the Realm",
}

PREFIX_TO_DLC = {
    "fp1": "Northern Lords", "fp2": "Fate of Iberia", "fp3": "Legacy of Persia",
    "ep1": "The Royal Court", "ep2": "Tours & Tournaments", "ep3": "Roads to Power",
    "ep4": "All Under Heaven",
    "bp1": "Friends & Foes", "bp2": "Wards & Wardens", "bp3": "Legends of the Dead",
    "bp4": "Wandering Nobles",
    "mpo": "Khans of the Steppe",
    "ce1": "Community Pack 1 (free)", "ce2": "Couture of the Capets",
    "tgp": "The Great People",
    "afr": "African Attire", "laamp": "Roads to Power",
}

_KNOWN_FEATURES: set = set()
_UNKNOWN_FEATURES: set = set()


def _scan_features(block, found):
    if isinstance(block, Tagged):
        block = block.block
    if not isinstance(block, Block):
        return
    for k, _op, v in block:
        if k == "has_dlc_feature" and isinstance(v, str):
            found.add(v)
        if isinstance(v, (Block, Tagged)):
            _scan_features(v, found)


def dlc_tag(path, block):
    """Best-effort DLC provenance for one entry: (dlc_name|None, features)."""
    features = set()
    _scan_features(block, features)
    for f in features:
        if f in FEATURE_TO_DLC:
            _KNOWN_FEATURES.add(f)
        else:
            _UNKNOWN_FEATURES.add(f)
    m = re.match(r"^\d*_?([a-z]+\d?)_", Path(path).name)
    prefix_dlc = PREFIX_TO_DLC.get(m.group(1)) if m else None
    feature_dlcs = sorted({FEATURE_TO_DLC[f] for f in features if f in FEATURE_TO_DLC})
    dlc = feature_dlcs[0] if feature_dlcs else prefix_dlc
    return dlc, sorted(features)


def unknown_feature_report():
    return sorted(_UNKNOWN_FEATURES)


# ---------------------------------------------------------------------------
# Output helper
# ---------------------------------------------------------------------------

def write_json(relpath, data):
    out = ROOT / "src" / "data" / relpath
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    n = len(data) if isinstance(data, (list, dict)) else 1
    print(f"✓ wrote src/data/{relpath} — {n} entries")
