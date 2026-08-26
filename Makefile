# ck3reference pipeline. `make patch` after each game update.
# Data source: the ck3ref mirror; set CK3REF_DIR if it is not at the default
# Dropbox location (see scripts/sync.sh).

.PHONY: patch sync version data art audit changelog build check

patch: sync version data art audit changelog build check

sync:
	@bash scripts/sync.sh

version:
	@python3 scripts/detect_version.py

data:
	@python3 scripts/build_maa.py
	@python3 scripts/build_traits.py
	@python3 scripts/build_lifestyles.py
	@python3 scripts/build_legacies.py
	@python3 scripts/build_buildings.py
	@python3 scripts/build_faiths.py
	@python3 scripts/build_doctrines.py
	@python3 scripts/build_holy_sites.py
	@python3 scripts/build_concepts.py
	@python3 scripts/build_entities.py
	@python3 scripts/build_backlinks.py

art:
	@python3 scripts/build_art.py

audit:
	@python3 scripts/audit.py

changelog:
	@python3 scripts/changelog.py

build:
	@npx astro build

check:
	@python3 scripts/check_links.py
