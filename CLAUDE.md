# CLAUDE.md — agent guide for ck3reference

Static Astro site generated from CK3's own game files. Sibling of
`owreference` (Old World) and `eu5ref` (EU5); the master plan lives in the
data mirror's `PLAN.md`. Pipeline: `make patch` = sync → version → data → art
→ audit → changelog → build → check.

## Hard rules

1. **No personal names, emails, or absolute home paths in anything committed.**
   Mirror location comes from `CK3REF_DIR`; `data/patch.json` records version
   hashes and dates only.
2. **Never read the Dropbox mirror in batch** — it silently drops files under
   `find`/`xargs` (verified). All builds read repo-local `reference/`
   (populated + manifest-verified by `scripts/sync.sh`). Single-file reads
   from the mirror (icons) are fine.
3. **XML→JSON determinism**: every build script emits
   `json.dumps(..., indent=2, sort_keys=True)` via `ck3.write_json`, prints
   `✓ wrote … — N entries`, and is registered in the Makefile `data:` target.
4. **Honest rendering over silent omission.** A field the game shows that we
   don't render must be in the build script's `SKIP_FIELDS` with a reason, or
   it's reported unhandled. Never collapse a conditional script_value to one
   number — `ck3.resolve_value` returns rule structures; render them.
5. **Never edit `reference/`** — it's synced game data.
6. **NEVER invent a game value, formula, or mechanic.** Every number on the
   site must come from a file under `reference/`. Before writing any constant,
   grep `common/defines/`, `common/script_values/`, and the category's
   `_*.info` doc. Read constants at BUILD TIME so they follow patches — never
   paste a literal. If a value isn't statically derivable, render "varies" and
   name the contributing factors; if a rule is documented ambiguously, say on
   the page that it isn't modelled. Explanatory prose about mechanics should
   quote the game's own `game_concept_*_desc` text rather than paraphrase from
   memory. Anything editorial must be labelled as such.
   *This rule exists because an invented dynasty-legacy cost ladder shipped,
   was shared publicly, and was immediately corrected by a player. The real
   formula (`PERK_COST_BASE` + `PERK_COST_MULTIPLIER` x perks owned) was in
   defines all along, documented in its own comment.*

## The library (`scripts/lib/ck3.py`)

- `parse_file` / `parse_dir` — Jomini parser. `Block` is an ordered multimap
  (`.get`, `.get_all`, `.items`, iterate `(key, op, value)`); `Tagged` wraps
  `rgb {…}`-style values. File-local `@x = 1` constants and `@[a + 2*b]`
  expressions resolve automatically.
- `loc(key)` — 287k English keys, cached in `.cache/loc.json`.
- `render_text(s)` — loc mini-language → plain text: `$key$` inlined,
  `#tag …#!` and `@icon!` stripped, `[concept|E]` → concept name,
  `[GetMaA('x').GetName]`-style statically resolved, anything else → `…` and
  counted in `unresolved_report()`.
- `render_modifier(key, value)` — game-authored phrasing via
  `modifier_definition_formats` + `MOD_*` loc (percent/decimals handled).
- `resolve_value(v)` → `(number, None)` if static, `(None, rules)` if
  conditional.
- `dlc_tag(path, block)` → `(dlc_name, features)` from filename prefix +
  `has_dlc_feature`. New feature flags must be added to `FEATURE_TO_DLC` or
  the audit fails.
- `write_json(relpath, data)` — the only way to emit.

## Design rules (LOAD-BEARING)

Theme: "rubricated manuscript". Dark warm-umber ground, vellum text, TWO
accents with fixed roles — **rubric red** = structural emphasis (versals,
fleurons `❧`, active states, counter marks), **brass** = interactive (links,
hover, ruling). Six skill colors (`--sk-*`) are the only other hues.

- Fonts: Cinzel (display — inscriptional caps by nature, that's intended),
  Inter (body), JetBrains Mono (numbers, keys, footer). No all-caps in body.
- Page titles get the rubricated versal automatically via `Base.astro`.
- Tables: `.ntbl` inside `.tbl-scroll`; group headers `.group-h`; chips
  (`.chip--counter` red-tinted, `.chip--terrain` dashed + `title` tooltip,
  `.chip--req` blue-tinted); stat bars `.stat` with `--w` fill share.
- DLC badges `.badge-dlc` from `rec.dlc`. Reuse existing classes before
  inventing new ones; page-specific styles go in the page's scoped `<style>`.
- Icons: emit the game's icon key in build scripts; `build_art.py` converts
  `game/gfx/interface/icons/<category>/<key>.dds` → `public/img/<cat>/…webp`
  from the mirror (Pillow reads DDS directly).

## Status (2026-08-26)

All 54 catalog pages are built — `src/data/tabs.ts` has no placeholders. Live at
https://alcaras.github.io/ck3ref/ (repo `alcaras/ck3ref`, Pages via Actions;
CI compiles Astro only, data + art are committed).

~50 build scripts, ~7k registered entities, 10k+ backlinks, 9,823 indexed
events, ~3.8k converted icons + 21 panoramic legacy banners.

Known gaps / next steps:

- **More illustration art is available and unused.** `gfx/interface/illustrations/`
  has 44 folders; only `legacy_tracks` is wired up. `activities` has 5 scenes
  (of 21 activities — the rest are in `activity_backgrounds`,
  `activity_header_backgrounds`, `activity_splash_screens`), `decisions` has 66
  shared scene illustrations addressed via each decision's `picture` field
  (which `build_decisions.py` currently skips). Wiring either needs a
  name-resolution pass, not just a CATEGORIES row.
- Event option trees are not rendered (effect-script layer).
- Backlinks are surfaced on 6 pages; the graph covers far more.
- `province_terrain`, `on_action`, and the scripted_* dirs remain conscious
  SKIPs (engine plumbing).

## Adding a page (the men-at-arms pattern)

1. Read the category's `_*.info` schema doc in `reference/game/common/<dir>/`.
2. `scripts/build_<thing>.py`: parse_dir → records with HANDLED/SKIP field
   accounting → `ck3.write_json`. Localized `name` is mandatory (audit).
3. Register in `Makefile` `data:`, move the dir from `SKIP` to `MAPPED` in
   `scripts/audit.py`.
4. `src/pages/<slug>.astro` modeled on `men-at-arms.astro` (Base + filterbar
   + grouped `.ntbl` + inline filter script).
5. Flip the tab to `built` in `src/data/tabs.ts`.
6. `make data audit && npx astro build && python3 scripts/check_links.py`.

## Quirks discovered (don't re-debug)

- MAA `can_recruit` gates hide in scripted-trigger macros
  (`valid_for_maa_trigger = { PARAMETER = unlock_maa_x }`) — the PARAMETER is
  a cultural parameter granted by a tradition. Negation context (NOT/NOR/NAND)
  must be tracked or bans render as requirements.
- Cultural parameter loc keys: `culture_parameter_<key>`; dynasty perks:
  `<key>_name`; traits: `trait_<key>`. Government flags have no loc.
- `game/dlc/` has no script content; feature→DLC mapping is many-to-one and
  hand-maintained in `ck3.FEATURE_TO_DLC`.
- Some icons legitimately share art via the `icon =` field; `build_art.py`
  falls back to `_default.dds` and warns (Dropbox may also still be syncing).
  Categories where absence is normal (doctrines, pillars, traditions) run
  `quiet=True`. The FUSE mount sometimes returns an EMPTY folder listing until
  an `ls` materializes it — a 0/N art run usually means that, not missing art.
- **Loc key patterns confirmed per category**: traits `trait_<key>`; perks &
  focuses & doctrines & tenets & pillars & dynasty perks & doctrine groups
  `<key>_name` (+`_desc`); buildings `building_<key>`; faiths/religions bare
  `<key>` (+`_adj`/`_adherent`); holy sites `holy_site_<key>_name`; concepts
  `game_concept_<key>`; traditions `<key>_name`; innovations bare `<key>`;
  culture params `culture_parameter_<key>`; MAA bare `<key>` + `<key>_flavor`.
- **Dynamic `name`/`desc` blocks** (first_valid/triggered_desc) appear on ~57
  perks, 24 doctrines, 52 traits — extract loc refs from the block and prefer
  the LAST (untriggered fallback) entry.
- Dynasty perk order = file definition order, NOT the key's numeric suffix.
- `effect` blocks' player text resolves three ways: direct loc key,
  `effect_localization/` entry, or the implicit `<key>_global` loc convention.
- Tradition costs: prestige only — base 2000 (4000 ritual) + conditional
  penalties (+2000 wrong ethos, +3000 unmet criteria) ×0.5 "inspired" ×1.5
  replacement; no per-count scaling (cap is 5 traditions).
- Doctrine piety costs chain through `faith_doctrine_cost_low/mid/high`
  (200/400/600) and `faith_tenet_cost_*` (500/1000/1500), nearly always with
  the ×0.5 unchanged-doctrine multiplier. Never collapse to one number.
- DLC gating variants: `requires_dlc_flag` (concepts; cosmetic building
  assets — NOT a badge source for buildings), `has_dlc_feature` (most),
  DLC scripted triggers (`has_*_dlc_trigger` in
  scripted_triggers/00_has_dlc_scripted_triggers.txt — doctrines),
  filename prefixes. Faiths have NO derivable DLC provenance.
- `custom_tooltip` texts inside `can_pick`/`is_shown` are UNMET-state
  phrasings ("Your Government is Nomadic" = blocker) — label as conditions,
  never as positive requirements.
- Building terrain gates live one level down in
  `building_*_requirement_terrain` scripted triggers; an empty (commented-out)
  trigger body = no restriction. `building_requirement_castle_city_church =
  { LEVEL = N }` → "Holding level N".
- Scripted-trigger macros invoked with argument blocks
  (`valid_for_maa_trigger = { PARAMETER = x }`) — collect the macro's args,
  don't recurse into them as triggers.
- Modifier VALUES can be script-value names — `render_modifier` resolves them.
- **Icons vs illustrations are different trees.** `gfx/interface/icons/<cat>/`
  holds small square icons (CATEGORIES in build_art.py);
  `gfx/interface/illustrations/<cat>/` holds large art — legacy tracks are
  4216x368 panoramas, activity scenes are 1592x848. Wide art goes through
  `ILLUSTRATIONS` in build_art.py, which downscales; running it through the
  icon path would emit multi-MB files.
- Dynasty legacies have NO per-perk art — the game reuses the track icon for
  every step. Track icon (`icons/dynasty/<track>.dds`) and track banner
  (`illustrations/legacy_tracks/<track>.dds`) share the same key.
- game_concepts: no `.info` doc; `parent` may name an alias; 20 concepts have
  `shown_in_encyclopedia = no` (exclude, as the game does).
