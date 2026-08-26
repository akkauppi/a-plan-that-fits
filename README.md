# Four Planters

Four Planters is an interactive urban-network solver for a deliberately scoped
question:

> Can a small number of modal filters prevent private-car through-routing across a
> neighbourhood while preserving local access, walking, cycling, public transport,
> and assumed emergency access?

It combines a frozen, real OpenStreetMap snapshot of Kallio–Alppiharju–western
Vallila with a React/MapLibre research interface and a FastAPI, Z3, and NetworkX
counterexample-guided solver.

## Current reboot status

The vertical slice, frozen data pipeline, solver/API, and interface are implemented.
Synthetic solver/API tests and frontend checks pass. One integration issue remains:
after the visually necessary change from 40 individual boundary markers to eight
analytical boundary-crossing groups, the default Helsinki solve still reaches its
timeout. See [the reboot handoff](docs/reboot-handoff.md) for exact evidence and the
next step. This checkout should therefore be treated as an honest work-in-progress,
not as the finished operational demonstrator.

## Run locally

Requirements: Python 3.11+, Node.js 20+, npm, and a browser.

```bash
make setup
make data-validate
make dev
```

Then open <http://127.0.0.1:5173>. `make dev` starts the API on port 8000 and Vite
on port 5173. The ordinary application makes no live OSM or basemap request.

Useful commands:

```bash
make data          # deterministic rebuild from the checked-in compressed OSM response
make test          # Python plus frontend unit/lint/type checks
make build         # production browser build
make test-e2e      # Playwright desktop and tablet story
make lint
```

Refreshing the source snapshot is intentional and networked:

```bash
make data-refresh
```

That command contacts Overpass, archives the raw bounded response with a checksum,
and replaces the derived snapshot. Normal startup and `make data` remain offline.

## Frozen Helsinki scenario

- Study polygon/bbox (WGS84): `[24.9435, 60.1854, 24.9635, 60.1962]`
- Approximate area: 1.33 km²
- Neighbourhoods: Kallio, Alppiharju, and western Vallila, Helsinki
- OSM base timestamp: `2026-08-25T22:24:24Z`
- Acquisition timestamp: `2026-08-25T23:01:58Z`
- Snapshot ID: `osm-20260825T222424Z-d8c48f77151b`
- Analysis CRS: ETRS89 / TM35FIN (`EPSG:3067`)
- Display CRS: WGS84 (`EPSG:4326`)

Current derived contents are 1,342 analytical nodes, 2,408 directed private-car
edges, 384 eligible modal-filter candidates, eight boundary-crossing portal groups,
631 OSM building footprints, 182 address clusters, and 678 protected map features.

The source is OpenStreetMap data, © OpenStreetMap contributors, licensed under the
[Open Data Commons Open Database License](https://www.openstreetmap.org/copyright).
Attribution is permanently visible in the map and instrument footer. Detailed query,
checksum, policies, versions, and validation results are in
[`metadata.json`](data/derived/helsinki-kallio-vallila/metadata.json).

## Solver method

Each eligible physical street segment has a Boolean `blocked[candidate_id]`. Z3
enforces the intervention budget, forced filters, open-street locks, discovered path
cuts, access corrections, and explicit lexicographic objectives. NetworkX then checks
the directed graph for surviving routes and address-cluster egress:

1. Z3 proposes an intervention set.
2. NetworkX finds real surviving portal routes in the frozen graph.
3. Those counterexamples become additional route-cut clauses.
4. A set that strands an address cluster is rejected with a safe corrective clause.
5. A candidate result is checked again on a fresh graph before it can be labelled
   verified.

Timeout, cancellation, solver UNSAT, graph-unblockable routes, and verification/data
errors are separate machine-readable states. Equal-objective alternatives are
enumerated by fixing the objective vector and excluding earlier structural sets.
Tracked assumptions are translated into human-facing UNSAT explanations and suggested
relaxations; assumptions are never changed automatically.

See [architecture and proof boundary](docs/architecture.md), [API](docs/api.md), and
the [acceptance checklist](docs/acceptance-checklist.md).

## Interface

The offline MapLibre canvas renders the study boundary, real street hierarchy and
buildings, protected transit/major-road corridors, numbered portal groups, address
clusters, oriented cross-street candidate symbols, live counterexample routes,
selected/forced/locked filters, local access routes, and before/after components.

The instrument includes a default budget of four, portal-pair selection, force/open
street constraints, emergency-permeability assumption, real SSE proof activity,
cancel/reset, alternatives and comparison, URL-serialized settings, responsive tablet
layout, visible focus states, and reduced-motion support.

## Scientific scope and limitations

The strongest intended claim is:

> Under the current graph, mode, candidate-intervention, and portal assumptions, no
> private-car route remains between the selected portal pairs.

It does not establish that through-traffic will disappear, predict redistribution,
approve an emergency-access treatment, guarantee completeness of OSM access tags,
prove physical or legal feasibility, or constitute a traffic plan. Building clusters
approximate local private-car access. Walking and cycling remain unchanged by the
mode-specific filter abstraction. Emergency permeability is asserted only for a
removable or unlockable treatment—not for a literal fixed planter.

## Repository layout

```text
apps/web/               React, TypeScript, Vite, MapLibre, Vitest, Playwright
services/solver/        FastAPI, Z3/NetworkX engine, API and tests
scripts/build_scenario.py
data/source/            frozen compressed Overpass response and descriptor
data/derived/           browser GeoJSON, solver graph, metadata
docs/                   method, API, acceptance and reboot notes
```

The current review screenshot, showing the eight-portal layout but the pre-fix timeout
state, is at
[review-pre-optimization-timeout.png](docs/screenshots/review-pre-optimization-timeout.png).
It is evidence from iteration, not a representative final product image.
