# Four Planters

Four Planters is an interactive urban-network research instrument. It now contains
two related experiments: the completed Helsinki modal-filter baseline and an
Otaniemi access-resilience experiment that makes the role of a constraint solver
visible on a real, frozen geographic network. A presentation-ready **How solvers
differ** page now explains the division of labour between routing and constraint
solving for nontechnical colleagues. The primary question is:

> Under an explicit flood/roadworks availability scenario, which minimum
> corridor-scale continuity commitments let selected origins retain private-car
> access to at least one reviewed network exit?

The retained baseline asks:

> Can a small number of modal filters prevent private-car through-routing across a
> neighbourhood while preserving local access, walking, cycling, public transport,
> and assumed emergency access?

The browser opens the newer Otaniemi experiment first. It combines frozen
OpenStreetMap, Finnish Environment Institute (Syke), and City of Espoo evidence with
a React/MapLibre interface and a FastAPI, Z3, and NetworkX
counterexample-guided solver. The Kallio–Alppiharju–western Vallila planter solver
remains available from the experiment switcher as a deterministic baseline.

## Current status

Both end-to-end vertical slices are implemented. The Otaniemi workspace exposes the
source evidence, availability assumption, representative origins, reviewed network
exits, corridor-scale decision units, live candidate/counterexample/refinement
events, and fresh directed-graph verification. It also contains an inspectable
constraint workbench that translates map facts into Boolean variables and learned
frontier clauses for an audience familiar with GIS but new to constraint solvers.

The preserved Kallio solver still provides modal-filter locks, forced filters,
portal-pair editing, alternatives, comparison, timeout/cancellation, explanatory
UNSAT output, and desktop/tablet layouts. Four is an upper bound, not a required
count; its audited default scenario uses all four at its verified optimum. See
[the release handoff](docs/reboot-handoff.md) for its measured baseline evidence.

As of 2026-08-30, Four Planters is a **completed baseline rather than the primary
continuing research question**. Its engineering assets will be reused, but further
expansion of portal/filter experiments has diminishing scientific value because the
result is strongly controlled by boundary, portal, and candidate assumptions and is
often close to a small graph cut.

The accepted continuing direction is **resilient access under flooding and planned
street works**. The first real Otaniemi solver slice is now checked in beside the
baseline: typed location recipes, fixed-endpoint OSM/MML/Syke/Espoo adapters, frozen
source evidence, a directed walking/cycling/private-car base network, an
exposure-only coastal-flood overlay, a 2 m terrain-quality-control raster, municipal
address/building evidence, explicit private-car availability assumptions, and a
fresh-graph-verified access solver. See the
[foundation, method, and provenance](docs/resilient-access-foundation.md) and the
[project decision and roadmap](docs/project-status-and-roadmap.md).

A secondary evidence drawer exposes the bounded location-builder workflow: frozen
Otaniemi or a clickable Finland point/radius canvas with precise coordinate fields,
source-readiness preflight, background offline base-network build, real progress
history, cancellation, and an explicitly acknowledged live OSM refresh. This is not
yet a general analysis builder: a custom build publishes a validated base network,
but does not acquire the other evidence layers or replace the frozen Otaniemi graph
used by the resilience solver.

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

Recorded on the 2026-08-31 integration tree: 190 Python tests, 35 Vitest cases, and
all ten Playwright desktop/tablet stories passed; Ruff, ESLint, strict TypeScript,
the production build, and the frozen-data validators passed. Vite retains the
documented large MapLibre chunk advisory. See the
[acceptance evidence](docs/acceptance-checklist.md) for the scoped checklist.

The Otaniemi experiment has a complete offline evidence-replay path:

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
[Otaniemi experiment guide](docs/resilient-access-foundation.md).

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

## Otaniemi resilient-access experiment

The successor pilot uses a 2.743279 km² coastal core in Otaniemi, Espoo with a
separate 750 m network/source context. The frozen OpenStreetMap observation has base
timestamp `2026-08-30T09:57:36Z`; derived snapshot
`base-c8dcbcfaca2b2c9498420681` contains 18,710 nodes, 42,077 directed edges, and
21,526 physical segments. Of those, 8,048 physical segments participate in the
private-car graph used by the access experiment.

The application-level frozen identity is
`base-c8dcbcfaca2b2c9498420681+flood-bf45a84ac9ce456045f8932b+espoo-0c59d1ca21a9e918b058`.
At load time the service verifies declared byte sizes and SHA-256 hashes for the
base-network JSON, flood analysis and display GeoJSON, and both compressed and raw
Espoo address/building GML. The API exposes those component identities so changing
municipal evidence cannot silently retain the same advertised scenario identity.

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
892 source-network segments (11,265.132 m) intersect the 1/100 terrestrial zones and
1,608 (20,013.350 m) intersect the 1/1000 zones; 35 exposed segments in each scenario
have vertical-separation tags requiring review. The corresponding effective counts
in the private-car graph are 241 and 528. Source-exposure totals and car-availability
totals are deliberately shown separately.

The user must explicitly enable this stress-test rule:

```text
unavailable(edge) := declared_roadworks(edge)
                  OR (stress_rule_enabled AND exposed(edge, selected_return_period))
```

This is an analytical assumption, not a Syke or MML road-closure finding. MML terrain
is not sampled by, and never closes an edge in, the solver. User-clicked roadworks
are fixed unavailable private-car links for the current run; there is still no
claimed live Espoo closure feed or scheduling model.

City of Espoo address evidence contributes 297 points inside the core. These are
aggregated into 15 deterministic 500 m `EPSG:3067` representative cells and snapped
to the private-car graph, with a maximum observed snap of 58.48 m. The solver checks
the representatives, not 297 individually verified households. Four reviewed
outbound context endpoints are available: East · Kuusisaarentie,
South · Tapiolantie, West · Kalevalantie, and North · Kehä I. They are
network exits, not certified safe destinations. With several selected, each origin
needs to reach at least one of them (an OR requirement), not every exit.

The default teaching preset selects the Otaranta representative, the east
Kuusisaarentie exit, the 1/1000 exposure tier, the explicit closure stress rule, and
a budget of four continuity commitments. The deterministic verified optimum uses
three corridor zones, expands to 21 OSM physical fragments, has a 388 m aggregation
cost, and retains access with a mapped detour of +1,093 m. Some selected fragments
are mapped service/driveway links without restrictive OSM access tags, so this is
also a useful source-quality warning rather than evidence of legal public access.

The **all-cell sensitivity** preset applies the same east exit requirement to all 15
representatives. Under the frozen 1/1000 assumptions, a budget of four is verified
UNSAT; five continuity commitments are needed. That result is intentionally
presented as sensitivity to origins, gateway, aggregation, and availability policy,
not as a general resilience judgement about Otaniemi.

The base graph prevents a generic OSM `access=*` value from promoting an
otherwise inappropriate highway/mode combination, and excludes 949 unreferenced
nodes (947 OSM nodes and two derived boundary nodes). Its Boolean permission abstraction
still flattens `access=destination` and `access=delivery` to “permitted” on an
otherwise eligible way. Those purpose restrictions must be contextualized as local
versus through movement before the graph supports an operational access conclusion.

## Solver method

The Otaniemi experiment separates geographic evidence, a deliberately chosen
availability policy, solver decisions, and graph verification. Each eligible
contiguous exposure zone has a Boolean `passable[decision_group_id]`. A group joins
adjacent exposed OSM fragments with the same normalized street name; unnamed
fragments use OSM way/highway continuity. The budget counts these visible analytical
zones, while the secondary cost is their rounded total mapped length in metres.
Neither unit is a construction design or cost estimate.

Z3 begins with the budget and any graph-derived clauses learned so far; reachability
is not naïvely encoded as every possible path. NetworkX acts as a domain verifier:

1. Z3 proposes which continuity-zone variables are true.
2. NetworkX applies fixed works and the explicit flood stress rule, then reintroduces
   only the physical segments belonging to selected zones.
3. If an origin is stranded, NetworkX draws a least-disrupted diagnostic route for
   the map and calculates the directed reachable frontier of eligible zones.
4. The frontier becomes a necessary clause such as
   `passable[zone_a] OR passable[zone_b]`; Z3 solves the stronger model.
5. Once all selected origins reach at least one selected gateway, a freshly built
   NetworkX graph repeats the availability and reachability checks before the
   result receives a verified label.

The diagnostic route is explanatory and is not itself the learned clause. Timeout,
cancellation, data error, and verified infeasibility remain distinct. The teaching
preset happens to expose three successive singleton frontiers, so each learned clause
forces one zone. It clearly demonstrates the CEGIS protocol but is not evidence that
Z3 outperforms a shortest-path or cut algorithm on this instance; the solver becomes
more consequential with alternative multi-zone frontiers, cross-scenario budgets,
and roadworks scheduling.

The completed Kallio baseline uses the same pattern for a different decision. Each
eligible physical street segment outside both analytical setback zones has a Boolean
`blocked[candidate_id]`. Z3 enforces the intervention budget, forced filters,
open-street locks, discovered path cuts, access corrections, and explicit
lexicographic objectives. NetworkX checks the directed graph for surviving routes
and address-cluster egress:

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

The primary offline MapLibre canvas renders the Otaniemi core and context, actual
street hierarchy and municipal buildings, clipped flood-intersection geometry,
effective unavailable private-car links, 15 representative origin cells, four
reviewed exits, diagnostic counterexample routes, selected continuity zones, and the
verified retained-access route. The map timeline can revisit each real streamed
solver event, making the candidate, stranded-origin witness, learned frontier, and
fresh verification visually inspectable.

The adjacent constraint workbench is a staged translation rather than a black box:
**map facts → decision variables → hard constraints → domain graph check →
checked result**. It shows actual selected variables and frontier clause IDs and also
relates the pattern to evacuation, facility continuity, habitat links, winter
maintenance, utility isolation, and time-window roadworks.

The separate **How solvers differ** page is designed for explanation rather than
operation. It contrasts a route solver's fixed-network question with Z3's
many-combinations question, diagrams their counterexample-guided hand-off, narrates
the measured Otaniemi teaching trace, and states the proof boundary in plain language.

The preserved Kallio map renders the study boundary, real street hierarchy and
buildings, protected transit/major-road corridors, eight numbered primary portals,
address clusters, oriented cross-street candidate symbols, live counterexample
routes, selected/forced/locked filters, local access routes, and before/after
directed strong-connectivity regions (mutual private-car reachability).

The instrument includes a default budget of four, portal-pair selection, force/open
street constraints, emergency-permeability assumption, real SSE proof activity,
cancel/reset, alternatives and comparison, URL-serialized settings, responsive tablet
layout, visible focus states, and reduced-motion support. Solver time is adjustable
under **Access & solver settings** using 5, 10, 30, 60, or 120 seconds; 30 seconds is
the browser default and the selected value is included in the shareable URL. Reaching
that limit is reported as indeterminate/timeout, never as UNSAT.

## Scientific scope and limitations

The strongest Otaniemi claim is:

> Under the frozen directed private-car graph, selected representative origins,
> reviewed outbound network exits, declared roadworks, and the explicitly enabled
> flood-exposure-as-unavailable stress rule, the reported access relations were
> recomputed on a fresh directed graph.

It does not establish that the Syke polygons close a road, that any selected zone is
open or protectable, that a gateway is safe, that an OSM service road is publicly or
legally usable, or that 297 individual addresses retain access. It does not model
flood hydraulics, water depth at carriageway elevation, capacity, travel time,
traffic redistribution, emergency response, or operational feasibility. A selected
continuity commitment is a minimum dependency of this abstraction, not a proposed
project.

The strongest intended claim for the Kallio baseline remains:

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

The reproducible data commands derive topology directly from committed bounded
Overpass responses. They preserve parallel ways and one-way direction, but these
frozen scenarios are not OSMnx-produced sets of drive/walk/bike mode graphs. OSMnx remains
an optional geospatial dependency. The production Vite build also reports a large
JavaScript-chunk advisory; this is a load-performance improvement opportunity, not a
build failure.

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

The committed desktop/tablet review artefacts include the primary resilience story,
its solver explanation, the location/evidence workflow, and the preserved baseline:

| State | Desktop | Tablet |
| --- | --- | --- |
| Otaniemi before solving | [desktop](docs/screenshots/four-planters-resilience-before-desktop.png) | [tablet](docs/screenshots/four-planters-resilience-before-tablet.png) |
| Otaniemi graph refinement | [desktop](docs/screenshots/four-planters-resilience-refinement-desktop.png) | [tablet](docs/screenshots/four-planters-resilience-refinement-tablet.png) |
| Otaniemi verified result | [desktop](docs/screenshots/four-planters-resilience-verified-desktop.png) | [tablet](docs/screenshots/four-planters-resilience-verified-tablet.png) |
| Constraint workbench | [desktop](docs/screenshots/four-planters-constraint-workbench-desktop.png) | [tablet](docs/screenshots/four-planters-constraint-workbench-tablet.png) |
| Route solver vs Z3 guide | [desktop](docs/screenshots/four-planters-solver-comparison-desktop.png) | [tablet](docs/screenshots/four-planters-solver-comparison-tablet.png) |
| Otaniemi source/evidence builder | [desktop](docs/screenshots/four-planters-builder-otaniemi-desktop.png) | [tablet](docs/screenshots/four-planters-builder-otaniemi-tablet.png) |
| Custom point/radius selection | [location, desktop](docs/screenshots/four-planters-builder-location-desktop.png) | [location, tablet](docs/screenshots/four-planters-builder-location-tablet.png) |
| Kallio baseline before | [desktop](docs/screenshots/four-planters-before-desktop.png) | [tablet](docs/screenshots/four-planters-before-tablet.png) |
| Kallio verified | [desktop](docs/screenshots/four-planters-verified-desktop.png) | [tablet](docs/screenshots/four-planters-verified-tablet.png) |
| Kallio alternative comparison | [desktop](docs/screenshots/four-planters-compare-desktop.png) | [tablet](docs/screenshots/four-planters-compare-tablet.png) |
| Kallio infeasible | [desktop](docs/screenshots/four-planters-unsat-desktop.png) | [tablet](docs/screenshots/four-planters-unsat-tablet.png) |
