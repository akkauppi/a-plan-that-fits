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

As of 2026-08-30, Four Planters is a **completed baseline rather than the primary
continuing research question**. Its engineering assets will be reused, but further
expansion of portal/filter experiments has diminishing scientific value because the
result is strongly controlled by boundary, portal, and candidate assumptions and is
often close to a small graph cut.

The accepted next direction is a location-driven **resilient-access** experiment
combining sourced flood scenarios with planned street works. Its first real,
reproducible Otaniemi foundation is now checked in beside the baseline: typed
location recipes, fixed-endpoint OSM/MML/Syke/Espoo adapters, frozen source evidence,
a directed walking/cycling/private-car base network, an exposure-only coastal-flood
overlay, a 2 m terrain-quality-control raster, and a strict interchange for frozen
user-supplied roadworks. See the
[foundation and provenance](docs/resilient-access-foundation.md) and the
[project decision and roadmap](docs/project-status-and-roadmap.md).

The separation remains important. The browser now opens the **Otaniemi
resilient-access research workspace first**, while the verified Kallio planter map
and solver remain available from the experiment switcher as the completed baseline.
The Otaniemi artifacts do not yet define safe destinations, convert flood exposure or
terrain height to road closure, perform resilient-access routing, or enter the Z3
model.

A dedicated Otaniemi workspace exposes the first bounded builder workflow: frozen
Otaniemi or a clickable Finland point/radius canvas with precise coordinate fields,
source-readiness preflight, background offline base-network build, real progress
history, cancellation, and an explicitly acknowledged live OSM refresh. The preset
also surfaces the independently verified MML elevation archive and 1/100 and 1/1000
flood-exposure counts, without turning terrain or exposure into road closure.
Building a snapshot never replaces the Kallio solver graph.

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

The Otaniemi foundation also has a complete offline replay path:

```bash
make otaniemi-offline          # verify sources, rebuild base network, derive exposure
make otaniemi-elevation        # verify/replay the frozen MML elevation window
make otaniemi-base-validate
make otaniemi-flood-validate
```

Its network and source refreshes are intentionally separate opt-in commands:

```bash
make otaniemi-base-refresh       # contacts Overpass
make otaniemi-sources-refresh    # contacts Syke and Espoo WFS
make otaniemi-elevation-refresh  # reads MML_API_KEY from local .env; contacts MML WCS
```

Normal startup, solving, `make data`, and every non-refresh Otaniemi command remain
offline. Copy `.env.example` to the Git-ignored `.env` and set the key only when an
explicit MML refresh is intended; credentials are neither needed nor read during
offline replay. Exact CLI forms and artifact paths are documented in the
[Otaniemi foundation guide](docs/resilient-access-foundation.md).

Refreshing the source snapshot is intentional and networked:

```bash
make data-refresh
```

That command contacts Overpass, archives the raw bounded response with a checksum,
and replaces the derived snapshot. Normal startup and `make data` remain offline.

## Completed Four Planters reference scenario

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

## Otaniemi resilient-access foundation

The successor pilot uses a 2.743279 km² coastal core in Otaniemi, Espoo with a
separate 750 m network/source context. The frozen OpenStreetMap observation has base
timestamp `2026-08-30T09:57:36Z`; the compact derived snapshot
`base-c8dcbcfaca2b2c9498420681` contains 18,710 nodes, 42,077 directed edges, and
21,526 physical display segments.

The checked source evidence also contains the published Syke 1/100 and 1/1000
sea-flood layers (archived features report a `muutospvm` change date of 2025-11-18;
3,288 buffered-query features), six City of Espoo WFS layers (35,471 buffered-query
features), and a separately archived National Land Survey of Finland Elevation Model
2 m window. The MML WCS 2.0.1 response is a 1,616 × 1,734 ASCII grid in `EPSG:3067`
with 2,802,144 valid values, no NoData cells, and an observed N2000 (`EPSG:3900`)
range of −2.266 to 30.116 m. It was acquired at
`2026-08-30T20:23:48.749054Z` for the snapped context bbox
`[377872, 6671958, 381104, 6675426]` and is replayed from a checksummed gzip archive.

Those totals and ranges are source observations, not graph counts or proof of
complete spatial coverage. The Espoo response timestamps are not dataset edition
dates. OSM is ODbL 1.0; the checked MML, Syke, and Espoo material is CC BY 4.0 with
source-specific attribution. Elevation is retained only for terrain and vertical
quality review: it does not establish flooding, closure, passability, or route
safety.

The flood derivation records horizontal segment/polygon exposure, published depth
class, source lineage, and bridge/tunnel/layer review flags. It deliberately does
not infer passability or safety. In snapshot `flood-bf45a84ac9ce456045f8932b`,
892 segments (11,265.132 m) intersect the 1/100 terrestrial zones and 1,608 segments
(20,013.350 m) intersect the 1/1000 zones; 35 exposed segments in each scenario have
vertical-separation tags requiring review. The municipal roadworks gap also remains
explicit: there is no claimed live Espoo closure feed, only a validated frozen-input
contract that requires declared modes and restriction semantics.

The base graph now prevents a generic OSM `access=*` value from promoting an
otherwise inappropriate highway/mode combination, and excludes 949 unreferenced
nodes (947 OSM nodes and two derived boundary nodes). Its Boolean permission abstraction
still flattens `access=destination` and `access=delivery` to “permitted” on an
otherwise eligible way. Those purpose restrictions must be contextualized as local
versus through movement before the graph supports any through-routing conclusion.

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
the [acceptance checklist](docs/acceptance-checklist.md). The project conclusion and
successor plan are in the [status and roadmap](docs/project-status-and-roadmap.md).

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
scenario is not an OSMnx-produced set of drive/walk/bike mode graphs. OSMnx remains
an optional geospatial dependency; the successor instead requires explicit,
separately attributed source adapters described in the roadmap. The production Vite
build also reports a single large JavaScript-chunk advisory (about 1.33 MB before
gzip and about 368 kB after gzip); this is a load-performance improvement opportunity,
not a build failure.

## Repository layout

```text
apps/web/               React, TypeScript, Vite, MapLibre, Vitest, Playwright
services/solver/        FastAPI, Z3/NetworkX engine, API and tests
services/scenario_builder/
                        typed recipes, fixed source adapters and derived builders
scripts/build_scenario.py
scripts/build_base_network.py
scripts/acquire_scenario_sources.py
scripts/build_flood_exposure.py
data/source/            frozen compressed Overpass response and descriptor
data/recipes/           versioned resilient-access build recipes
data/derived/           legacy scenario plus immutable Otaniemi snapshots
docs/                   method, API, acceptance and reboot notes
```

## Release screenshot set

The passing desktop/tablet Playwright run produced the following committed review
artefacts:

| State | Desktop | Tablet |
| --- | --- | --- |
| Otaniemi-first sources and exposure workspace | [builder, desktop](docs/screenshots/four-planters-builder-otaniemi-desktop.png) | [builder, tablet](docs/screenshots/four-planters-builder-otaniemi-tablet.png) |
| Custom point/radius selection | [location, desktop](docs/screenshots/four-planters-builder-location-desktop.png) | [location, tablet](docs/screenshots/four-planters-builder-location-tablet.png) |
| Before solving | [before, desktop](docs/screenshots/four-planters-before-desktop.png) | [before, tablet](docs/screenshots/four-planters-before-tablet.png) |
| Verified solution | [verified, desktop](docs/screenshots/four-planters-verified-desktop.png) | [verified, tablet](docs/screenshots/four-planters-verified-tablet.png) |
| Alternative comparison | [compare, desktop](docs/screenshots/four-planters-compare-desktop.png) | [compare, tablet](docs/screenshots/four-planters-compare-tablet.png) |
| Infeasible assumptions | [UNSAT, desktop](docs/screenshots/four-planters-unsat-desktop.png) | [UNSAT, tablet](docs/screenshots/four-planters-unsat-tablet.png) |
