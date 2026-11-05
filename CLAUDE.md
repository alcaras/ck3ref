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

## Status (2026-11-05, CK3 1.20.1.2 + By God Alone)

**Live: https://alcaras.github.io/ck3ref/** — repo `alcaras/ck3ref`, Pages via
Actions (CI compiles Astro only; data and art are committed).

62 catalog pages, no placeholders. **9,538 routes** — the bulk is one page per
event (8,659) and one per geographical region (612). ~57 build scripts, ~7.6k
registered entities, 10k+ backlinks, ~4.2k converted icons plus 21 panoramic
legacy banners and 97 decision scenes, and a 1.1 MB province-index map payload
under `public/map/`. Full build ≈ 15s; `make data` ≈ 60s (the region
cross-reference scan is ~14s of it).

Tools (all client-side, all shareable by URL):
`legacy-builder` (dynasty legacy path, purchase order matters),
`culture-builder` (hybridize / diverge / reform), `province-planner`
(what you can build in a holding), `genetics`, `faith-creator`,
`culture-calculator`, `army-builder`, `regions` (the province map).

Known gaps / next steps:

- **Event option outcomes are partial by design.** `effect_localization`
  covers 989 effects; anything the game does not phrase is COUNTED, never
  invented ("+N further scripted effects with no tooltip text"). Expanding
  coverage means adding a real effect renderer, not more guessing.
- **Unused illustration art**: `gfx/interface/illustrations/` has 44 folders;
  only `legacy_tracks` and `decisions` are wired. `activities` has scenes for
  5 of 21 activity types (rest live in `activity_backgrounds`,
  `activity_header_backgrounds`, `activity_splash_screens`) — needs a
  name-resolution pass, not a CATEGORIES row.
- **Province planner** cannot know per-county terrain, other holdings in the
  county, or faith — those conditions are surfaced as "N conditions depend on
  your realm" rather than resolved. Per-county terrain would need
  `history/provinces` joined to `landed_titles` (the join already exists in
  `build_startworld.py`).
- Backlinks surface on 10 pages; the graph covers more.
- `on_action`, `scripted_*` dirs remain conscious SKIPs (engine plumbing).

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
- **Alpha-mask icons.** Several icon sets (buildings, holdings, legacies,
  domiciles, travel options, faith doctrines, pillars) ship with RGB all zero
  and the shape in the ALPHA channel — the game tints them at runtime.
  Converted as-is they render black-on-black and look "missing".
  `build_art.py::_is_alpha_mask` detects this (every visible pixel black) and
  tints with `MASK_TINT`. If an icon set looks invisible, check this first.
- **Congenital-inheritance modifiers are multiplicative, and only over the
  recessive table.** `positive/negative_inactive_inheritance_chance`,
  `*_random_genetic_chance` and `genetic_trait_strengthen_chance` (Blood
  legacy, and the `strong_blood` event modifier) apply as
  `chance x (1 + modifier)` — the game documents the form in
  `common/modifiers/00_event_modifiers.txt`: `positive_random_genetic_chance =
  4 # This will for instance cause a .2% chance to become 1%`. "Inactive"
  means the INACTIVE_TRAIT_CHANCE_* (recessive) defines, per the
  ACTIVE_ACTIVE = 150 comment about modifiers not letting you avoid a bad
  trait; nothing modifies the outright-inheritance table.
- **`inherit_chance` traits are a second, separate inheritance system.**
  Pure-blooded, Inbred, the two poxes, Sayyid and Golden Lineage are NOT
  `genetic = yes` — they carry a flat `inherit_chance` (and only Pure-blooded
  a `both_parent_has_trait_inherit_chance`), which is why they never appeared
  on the genetics page. The first Pure-blooded/Inbred in a line comes from an
  engine-side relatedness roll (`INBREEDING_ANCESTOR_GENERATIONS`,
  `INBRED_RELATEDNESS_MULT`, `PUREBLOODED_INBRED_RELATEDNESS_MULT`); the
  formula is not in script, so don't put a number on it.
- **Astro scoped CSS does not reach `innerHTML`-injected markup.** Anything a
  page builds at runtime (tooltips, builder panels, planner cards) must be
  styled in a `<style is:global>` block, ideally keyed on a container id.
  Symptom: text runs together / no spacing, only in the dynamic parts.
- **Never `import fs from 'node:fs'` in Astro frontmatter.** It fails the
  build with a misleading "Unterminated string literal" pointing at an
  unrelated line. To test for a file's existence at build time use
  `import.meta.glob('/public/img/{a,b}/*.webp')` and match on the keys.
- **Effect text comes from `common/effect_localization/`** — the game's own
  map from each scriptable effect to the loc keys it uses in tooltips (989
  entries; prefer the `first` variant). Fill its `$VALUE|fmt$` slot with the
  scripted amount BEFORE `render_text`, and never substitute a bare `VALUE`
  token — that also matches inside nested keys like `$DREAD_VALUE_GAIN$` and
  destroys them.
- **Inline icon tokens carry meaning.** `[dread_i]`-style tokens in loc
  templates are where the noun lives ("You gain [dread_i]+10"); `render_text`
  resolves them to the concept name, otherwise outcomes read "You gain +10".
- **Building categories say which holding a chain belongs to** (they come from
  the game's own file grouping): Castle/City/Temple holdings, Temple citadels,
  Tribal, Nomadic. Everything else is holding-agnostic. Used by the province
  planner for holding-type gating.
- **`special` and `great_building` chains are site-specific** — their triggers
  name a county, so no terrain/holding setting makes them "buildable here".
  280 of 366 chains are in this bucket; treat them separately or they swamp
  any buildability list.
- **Dynasty legacy perk cost is GLOBAL, not per track**: `PERK_COST_BASE` +
  `PERK_COST_MULTIPLIER` x perks already unlocked (250 + 500N). See hard rule 6.
- **The map is a raster of province indices, not a picture.**
  `build_map.py` decodes `map_data/provinces.png` (9216x4608) against
  `definition.csv`, downscales ÷3 with a MODE filter (averaging indices would
  invent provinces) and writes `public/map/provinces-index.png` as
  `R = idx & 255, G = idx >> 8, B = 0`. Write it with no gamma/ICC chunk and
  set `imageSmoothingEnabled = false` before any `drawImage`, or a
  colour-managed decode resamples indices into garbage. The build asserts both.
- **`definition.csv` row 0 and province 12946 share RGB (0,0,0).** Black is the
  null province; 12946 is undrawable. A naive colour→id dict gives every black
  pixel on the map to 12946. 519 provinces are defined but never painted
  (12,750 of 13,269) — expected, counted, not an error.
- **÷3 swallows two provinces** (9666, 12828, 4-5 source pixels each). The
  build force-stamps the drawn pixel nearest their centroid — the *centroid
  itself* can land outside a crescent-shaped province — and then re-checks
  that stamping evicted nobody who had survived.
- **`el.hidden` loses to any class that sets `display`.** An author rule
  (`.rrow { display:flex }`) outranks the UA's `[hidden] { display:none }`, so
  the attribute gets set and nothing happens. Bit twice on the regions page:
  the map's `inset:0` loading note kept eating every pointer event (hover did
  nothing, `elementFromPoint` still returned it), and the region list's filter
  hid no rows while the "N of 612" counter dutifully updated. Fixed once, for
  the whole site, with `[hidden] { display: none !important }` in theme.css —
  don't re-solve it per component. Symptom to recognise: `el.hidden === true`
  and the element still laid out.
- **Region membership is declared at mixed granularity** — duchies (365),
  sub-regions (140), counties (117), kingdoms (37), bare province ids (25).
  Ship the DECLARED form plus `geo-tree.json` and resolve in the browser:
  resolved sets total 320k province ids. Counts of counties/duchies/kingdoms
  are derived UPWARD from the resolved provinces, so a region declared as bare
  ids still reports the counties it covers.
- **365 of 612 regions have no localized name.** The "localized name is
  mandatory" audit rule is explicitly waived for regions; they render as the
  prettified key with a `key` mark, never title-cased into a fake name.
- **Region families are ours, not the game's.** `build_regions.py` maps every
  key by file / exact key / suffix / prefix and REFUSES to emit an unmapped
  key — that tripwire is what caught `togskol_khanatede_jure_region`, whose
  game-side key is missing an underscore.
- **Three region keys contain a literal `&`** (`ghw_region_finland_&_estonia`
  and two more), so routes use a `slug` with `&`→`and`. `check_links.py` used
  to truncate hrefs at the `#` of `&#38;` — it now unescapes entities first.
- **`/titles/` has a page per EMPIRE only**; kingdoms, duchies and counties are
  anchors on it. `src/data/title-index.json` (from `build_map.py`) carries
  `name`/`tier`/`page` so links resolve to `/titles/<empire>#<title>`. Titles
  with no empire ancestor are all titular noble-family titles with no land.
- **Hybridization is gated on cultural acceptance, not prestige**: base 40
  (`hybridization_threshold_flat_number_value`), x0.5 / x2 from the traditions
  carrying `easier_to_hybridize` / `harder_to_hybridize` (the target culture's
  parameter applies too), clamped 0-100. Cooldowns: 50y hybrid, 100y
  divergence, 50y per tradition change.
- **1.20 (By God Alone) restructured religion — Religion → Faith → Rite.**
  `religion_types/` (now a `religion_details` block), `faith_types/` (faiths
  moved out of their religion; holy sites split into `eminent_holy_sites` and
  `holy_sites`; optional `main_rite`), `rite_types/` (each names its parent
  `faith =`). Effective doctrines: faith overrides religion per doctrine
  group, rite overrides both; a faith with a scripted main Rite takes that
  Rite's tenets and doctrines. A main Rite's default parent can be another
  faith and be handed over in `history/faiths` (roman_rite: christian_faith
  -> catholic at 1054.7.16). Doctrines name their own `doctrine_group_type` +
  `index`; tenets are a separate database (`tenet_types/`, icons in
  `icons/faith_tenets/`); the 3-tenet cap is define
  `NReligion.FAITH_CORE_TENETS_CAP`. Cost limits use `rite_has_doctrine` /
  `rite_has_tenet` / `rite_religion_tag`. Province and character history set
  `rite =`, not `religion =`. Laws likewise split: groups in
  `common/law_groups/`, laws carry `law_group_type` + `index`.
- **Windows PC pipeline**: no `rsync`/`make`. Sync mirror ← Steam with the
  robocopy lines of the mirror's `update-ck3ref.bat` (drop its `pause`), then
  robocopy the `scripts/sync.sh` SUBTREES into `reference/` and compare file
  counts; run the Makefile `data:` lines with `python` and `PYTHONUTF8=1`.
  The committed lockfile lacks Rollup's Windows binary: `npm i --no-save
  @rollup/rollup-win32-x64-msvc@<rollup version>`.
