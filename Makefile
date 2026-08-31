SHELL := /bin/bash

OTANIEMI_BASE_RECIPE := data/recipes/espoo-otaniemi-coastal-base-v1.json
OTANIEMI_SOURCE_RECIPE := data/recipes/espoo-otaniemi-coastal-v1.json
OTANIEMI_ELEVATION_RECIPE := data/recipes/espoo-otaniemi-coastal-elevation-v1.json
OTANIEMI_BASE_OUTPUT := data/derived/espoo-otaniemi-coastal-base-v1-base-network
OTANIEMI_FLOOD_OUTPUT := data/derived/espoo-otaniemi-coastal-v1-flood-exposure
OTANIEMI_SYKE_POINTER := data/source/scenario-builder/espoo-otaniemi-coastal-v1/syke/espoo-otaniemi-coastal-v1.syke-coastal-flood.archive.json

.PHONY: setup data data-refresh data-validate
.PHONY: otaniemi-offline otaniemi-base otaniemi-base-refresh otaniemi-base-validate
.PHONY: otaniemi-sources otaniemi-sources-all otaniemi-sources-refresh otaniemi-sources-coverage
.PHONY: otaniemi-elevation otaniemi-elevation-refresh otaniemi-elevation-coverage
.PHONY: otaniemi-flood otaniemi-flood-validate
.PHONY: dev dev-api dev-web test test-python test-web test-e2e build lint

setup:
	@test -x .venv/bin/python || python3 -m venv .venv
	.venv/bin/pip install -e '.[dev,data]'
	npm --prefix apps/web ci

# Deterministically rebuild from the checked-in compressed Overpass response.
data:
	.venv/bin/python scripts/build_scenario.py

# Intentionally opt-in: contacts Overpass and replaces the archived source snapshot.
data-refresh:
	.venv/bin/python scripts/build_scenario.py --refresh

data-validate:
	.venv/bin/python scripts/build_scenario.py --validate-only

# Rebuild the checked-in Otaniemi foundation without contacting upstream services.
otaniemi-offline:
	@$(MAKE) --no-print-directory otaniemi-sources-all
	@$(MAKE) --no-print-directory otaniemi-elevation
	@$(MAKE) --no-print-directory otaniemi-base
	@$(MAKE) --no-print-directory otaniemi-flood

# Rebuild the directed OSM mode network from its frozen content-addressed archive.
otaniemi-base:
	.venv/bin/python scripts/build_base_network.py --recipe $(OTANIEMI_BASE_RECIPE)

# Intentionally opt-in: contact the adapter-controlled Overpass endpoint first.
otaniemi-base-refresh:
	.venv/bin/python scripts/build_base_network.py --recipe $(OTANIEMI_BASE_RECIPE) --refresh

otaniemi-base-validate:
	.venv/bin/python scripts/build_base_network.py --recipe $(OTANIEMI_BASE_RECIPE) --validate-only

# Verify and republish only the frozen SYKE and Espoo evidence used by this pilot.
# The full recipe also declares OSM, whose independently frozen build is above.
otaniemi-sources:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_SOURCE_RECIPE) \
		--adapter syke --adapter espoo_wfs

# Verify the complete frozen OSM + SYKE + Espoo source-evidence bundle.
otaniemi-sources-all:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_SOURCE_RECIPE)

# Intentionally opt-in: contact the fixed SYKE and Espoo WFS endpoints.
otaniemi-sources-refresh:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_SOURCE_RECIPE) \
		--adapter syke --adapter espoo_wfs \
		--refresh

# Validate the bounded recipe and report source-specific coverage states; publish nothing.
otaniemi-sources-coverage:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_SOURCE_RECIPE) \
		--coverage-only

# Verify and republish the frozen NLS Elevation Model 2 m window. Elevation is
# retained as source/quality-control evidence and does not imply passability.
otaniemi-elevation:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_ELEVATION_RECIPE) \
		--adapter mml_elevation

# Intentionally opt-in: read the API key only in this shell, contact the fixed
# NLS WCS endpoint, and replace the frozen content-addressed elevation archive.
otaniemi-elevation-refresh:
	@set -e; \
	test -r .env || { echo "Missing local .env; copy .env.example and set MML_API_KEY"; exit 2; }; \
	set -a; . ./.env; set +a; \
	test -n "$${MML_API_KEY:-}" || { echo "MML_API_KEY is not configured in .env"; exit 2; }; \
	exec .venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_ELEVATION_RECIPE) \
		--adapter mml_elevation \
		--refresh

otaniemi-elevation-coverage:
	.venv/bin/python scripts/acquire_scenario_sources.py \
		--recipe $(OTANIEMI_ELEVATION_RECIPE) \
		--adapter mml_elevation \
		--coverage-only

# Derive exposure evidence from the latest verified base snapshot and frozen SYKE inputs.
otaniemi-flood:
	@base_snapshot="$$(.venv/bin/python -c 'import json; from pathlib import Path; print(json.loads(Path("$(OTANIEMI_BASE_OUTPUT)/latest.json").read_text())["snapshot_path"])')"; \
	.venv/bin/python scripts/build_flood_exposure.py \
		--base-network "$(OTANIEMI_BASE_OUTPUT)/$$base_snapshot/base-network.json" \
		--syke-pointer "$(OTANIEMI_SYKE_POINTER)" \
		--output-dir "$(OTANIEMI_FLOOD_OUTPUT)"

otaniemi-flood-validate:
	@base_snapshot="$$(.venv/bin/python -c 'import json; from pathlib import Path; print(json.loads(Path("$(OTANIEMI_BASE_OUTPUT)/latest.json").read_text())["snapshot_path"])')"; \
	.venv/bin/python scripts/build_flood_exposure.py \
		--base-network "$(OTANIEMI_BASE_OUTPUT)/$$base_snapshot/base-network.json" \
		--syke-pointer "$(OTANIEMI_SYKE_POINTER)" \
		--output-dir "$(OTANIEMI_FLOOD_OUTPUT)" \
		--validate-only

dev:
	@$(MAKE) --no-print-directory -j2 dev-api dev-web

dev-api:
	.venv/bin/python -m uvicorn services.solver.api:app --host 127.0.0.1 --port 8000 --reload

dev-web:
	npm --prefix apps/web run dev -- --host 127.0.0.1

test: test-python test-web

test-python:
	.venv/bin/pytest

test-web:
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run test

test-e2e:
	npm --prefix apps/web run test:e2e

build:
	npm --prefix apps/web run build

lint:
	.venv/bin/ruff check services scripts
	npm --prefix apps/web run lint
