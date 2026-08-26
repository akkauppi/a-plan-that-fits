SHELL := /bin/bash

.PHONY: setup data data-refresh data-validate dev dev-api dev-web test test-python test-web test-e2e build lint

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
