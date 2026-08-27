# Four Planters

Four Planters is an interactive urban-network solver for a deliberately scoped
question:

> Can a small number of modal filters prevent private-car through-routing across a
> neighbourhood while preserving local access, walking, cycling, public transport,
> and assumed emergency access?

It combines a frozen, real OpenStreetMap snapshot of Kallio–Alppiharju–western
Vallila with a React/MapLibre research interface and a FastAPI, Z3, and NetworkX
counterexample-guided solver.

## Current status

The complete vertical slice is implemented: frozen data pipeline, streaming solver
API, independent final verification, interactive map, alternatives, timeout and
cancellation states, explanatory UNSAT output, and desktop/tablet layouts. The portal
model keeps all 68 detected boundary-crossing records in 38 physically local
analytical clusters while exposing eight primary portals in the compact browser
selector. Four is an upper bound, not a required count; the audited default scenario
uses all four at its verified optimum. See [the release handoff](docs/reboot-handoff.md) for measured check results
and the exact distinction between completed evidence and release checks that should
be rerun after a change.

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
edges, 272 eligible modal-filter candidates, 68 boundary-crossing records in 38
analytical portal clusters, eight browser-selectable primary portals, 631 OSM
building footprints, 182 address clusters, and 678 protected map features. Portal
clusters use deterministic complete-link grouping on each boundary side with a 60 m
maximum diameter; every crossing belongs to exactly one cluster.

Candidate eligibility has two explicit anti-endpoint-bias controls. A 60 m
**analysis-boundary terminal zone** measures each physical-segment midpoint to the
study boundary in EPSG:3067. A second 120 m setback measures that same midpoint to
the nearest mapped crossing point belonging to any of the eight primary/selectable
portals—not to its display marker, not only to portals selected in the current
request, and not to all 38 analytical portals. Of 384 base-eligible local segments,
80 fall in the boundary band and 79 in a primary-portal approach zone; 47 overlap,
so the portal rule adds 32 exclusions and leaves 272 candidates. Both zones remain
ordinary open graph streets and are shown in the browser. They are analytical bias
controls, not public-transport protection or physical/legal siting judgements.

The audited defaults are Vilhonvuorenkuja ↔ Agricolankuja
(**Southern cross-neighbourhood permeability**) and Pälkäneentie ↔ Alppikatu
(**Western cross-neighbourhood permeability**). With four as the maximum, the
balanced optimum uses four filters outside both setback zones.

The source is OpenStreetMap data, © OpenStreetMap contributors, licensed under the
[Open Data Commons Open Database License](https://www.openstreetmap.org/copyright).
Attribution is permanently visible in the map and instrument footer. Detailed query,
checksum, policies, versions, and validation results are in
[`metadata.json`](data/derived/helsinki-kallio-vallila/metadata.json).

## Solver method

Each eligible physical street segment outside both analytical setback zones has a Boolean
`blocked[candidate_id]`. Z3
enforces the intervention budget, forced filters, open-street locks, discovered path
cuts, access corrections, and explicit lexicographic objectives. NetworkX then checks
the directed graph for surviving routes and address-cluster egress:

1. Z3 proposes an intervention set.
2. NetworkX finds real surviving portal routes in the frozen graph.
3. Those counterexamples become additional route-cut clauses.
4. A set that strands an address cluster is rejected with a safe corrective clause.
5. A candidate result is checked again on a fresh graph before it can be labelled
   verified.

The default secondary access objective is an inspectable exposure proxy: each
candidate is charged once for every address cluster whose deterministic baseline
shortest egress route uses that street segment. It steers the search away from
streets that support many baseline access routes, but it is not an exact detour
estimate and may count one cluster against several candidates. Exact directed
shortest-path detours are recomputed on the final filtered graph and reported as
post-solution verification metrics.

Timeout, cancellation, solver UNSAT, graph-unblockable routes, and verification/data
errors are separate machine-readable states. Equal-objective alternatives are
enumerated by fixing the objective vector and excluding earlier structural sets.
Tracked assumptions are translated into human-facing UNSAT explanations and suggested
relaxations; assumptions are never changed automatically.

See [architecture and proof boundary](docs/architecture.md), [API](docs/api.md), and
the [acceptance checklist](docs/acceptance-checklist.md).

## Interface

The offline MapLibre canvas renders the study boundary, real street hierarchy and
buildings, protected transit/major-road corridors, eight numbered primary portals, address
clusters, oriented cross-street candidate symbols, live counterexample routes,
selected/forced/locked filters, local access routes, and before/after directed
strong-connectivity regions (mutual private-car reachability).

The instrument includes a default budget of four, portal-pair selection, force/open
street constraints, emergency-permeability assumption, real SSE proof activity,
cancel/reset, alternatives and comparison, URL-serialized settings, responsive tablet
layout, visible focus states, and reduced-motion support. Solver time is adjustable
under **Access & solver settings** using 5, 10, 30, 60, or 120 seconds; 30 seconds is
the browser default and the selected value is included in the shareable URL. Reaching
that limit is reported as indeterminate/timeout, never as UNSAT.

## Scientific scope and limitations

The strongest intended claim is:

> Under the current graph, mode, candidate-intervention, and portal assumptions, no
> private-car route remains between the selected portal pairs.

It does not establish that through-traffic will disappear, predict redistribution,
approve an emergency-access treatment, guarantee completeness of OSM access tags,
prove physical or legal feasibility, or constitute a traffic plan. Building clusters
approximate local private-car access.

The frozen analytical graph is a directed private-car graph. Walking and cycling
remain passable by the **mode-permission semantics** of a selected filter; they are not
separately downloaded, routed, or independently proved in this version. Emergency
permeability is likewise an explicit removable or unlockable treatment assumption,
not an emergency-network or legal-compliance proof. Service access is not modelled;
the API rejects requests that try to enable it so an unsupported mode cannot appear
in a verified result.

The reproducible data command derives topology directly from the committed bounded
Overpass response. It preserves parallel ways and one-way direction, but this frozen
scenario is not an OSMnx-produced set of drive/walk/bike mode graphs. OSMnx is
available as an optional geospatial dependency and a future pipeline direction, not
the provenance of the current proof graph. The production Vite build also reports a
single large JavaScript-chunk advisory (about 1.33 MB before gzip, about 368 kB after
gzip); this is a load-performance improvement opportunity, not a build failure.

## Repository layout

```text
apps/web/               React, TypeScript, Vite, MapLibre, Vitest, Playwright
services/solver/        FastAPI, Z3/NetworkX engine, API and tests
scripts/build_scenario.py
data/source/            frozen compressed Overpass response and descriptor
data/derived/           browser GeoJSON, solver graph, metadata
docs/                   method, API, acceptance and reboot notes
```

## Release screenshot set

The passing desktop/tablet Playwright run produced the following committed review
artefacts:

| State | Desktop | Tablet |
| --- | --- | --- |
| Before solving | [before, desktop](docs/screenshots/four-planters-before-desktop.png) | [before, tablet](docs/screenshots/four-planters-before-tablet.png) |
| Verified solution | [verified, desktop](docs/screenshots/four-planters-verified-desktop.png) | [verified, tablet](docs/screenshots/four-planters-verified-tablet.png) |
| Alternative comparison | [compare, desktop](docs/screenshots/four-planters-compare-desktop.png) | [compare, tablet](docs/screenshots/four-planters-compare-tablet.png) |
| Infeasible assumptions | [UNSAT, desktop](docs/screenshots/four-planters-unsat-desktop.png) | [UNSAT, tablet](docs/screenshots/four-planters-unsat-tablet.png) |
