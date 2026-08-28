# ck3reference pipeline. `make patch` after each game update.
# Data source: the ck3ref mirror; set CK3REF_DIR if it is not at the default
# Dropbox location (see scripts/sync.sh).

.PHONY: patch sync version data art audit changelog build check compositions

patch: sync version data art audit changelog build check

sync:
	@bash scripts/sync.sh

version:
	@python3 scripts/detect_version.py

data:
	@python3 scripts/build_maa.py
	@python3 scripts/build_combat_sim.py
	@mkdir -p .cache && npx --no-install esbuild scripts/build_tiers.ts --bundle --platform=node --format=esm --outfile=.cache/build_tiers.mjs --log-level=error && node .cache/build_tiers.mjs
	@python3 scripts/build_traits.py
	@python3 scripts/build_lifestyles.py
	@python3 scripts/build_legacies.py
	@python3 scripts/build_buildings.py
	@python3 scripts/build_faiths.py
	@python3 scripts/build_doctrines.py
	@python3 scripts/build_holy_sites.py
	@python3 scripts/build_cbs.py
	@python3 scripts/build_titles.py
	@python3 scripts/build_startdates.py
	@python3 scripts/build_startworld.py
	@python3 scripts/build_concepts.py
	@python3 scripts/build_traditions.py
	@python3 scripts/build_innovations.py
	@python3 scripts/build_pillars.py
	@python3 scripts/build_cultures.py
	@python3 scripts/build_culture_rules.py
	@python3 scripts/build_court.py
	@python3 scripts/build_council.py
	@python3 scripts/build_holdings.py
	@python3 scripts/build_province_rules.py
	@python3 scripts/build_terrain.py
	@python3 scripts/build_great_projects.py
	@python3 scripts/build_activities.py
	@python3 scripts/build_decisions.py
	@python3 scripts/build_schemes.py
	@python3 scripts/build_nicknames.py
	@python3 scripts/build_struggles.py
	@python3 scripts/build_situations.py
	@python3 scripts/build_legends.py
	@python3 scripts/build_epidemics.py
	@python3 scripts/build_governments.py
	@python3 scripts/build_laws.py
	@python3 scripts/build_contracts.py
	@python3 scripts/build_accolades.py
	@python3 scripts/build_house.py
	@python3 scripts/build_domiciles.py
	@python3 scripts/build_task_contracts.py
	@python3 scripts/build_interactions.py
	@python3 scripts/build_realm2.py
	@python3 scripts/build_court2.py
	@python3 scripts/build_events.py
	@python3 scripts/build_event_details.py
	@python3 scripts/build_artifacts.py
	@python3 scripts/build_dlc.py
	@python3 scripts/build_genetics.py
	@python3 scripts/build_defines.py
	@python3 scripts/build_entities.py
	@python3 scripts/build_backlinks.py
	@python3 scripts/build_search_index.py

art:
	@python3 scripts/build_art.py

# Heavy two-unit composition search (~4 min); run on demand, not part of `data`.
compositions:
	@mkdir -p .cache && npx --no-install esbuild scripts/build_compositions.ts --bundle --platform=node --format=esm --outfile=.cache/build_compositions.mjs --log-level=error && node .cache/build_compositions.mjs

audit:
	@python3 scripts/audit.py

changelog:
	@python3 scripts/changelog.py

build:
	@npx astro build

check:
	@python3 scripts/check_links.py
