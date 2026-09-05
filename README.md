# Geospatial Constraint Lab

Geospatial Constraint Lab is a collection of interactive research experiments about
using constraint solving with real geographic networks. Each experiment turns map
features and policy assumptions into explicit decisions and requirements. Z3 searches
the permitted combinations; NetworkX tests the resulting network and returns concrete
counterexamples when a proposal fails. Before a feasible answer is called verified,
its requested connectivity is repeated on a fresh graph. Verified infeasibility has a
different certificate: Z3 proves the active hard constraints and accumulated sound
graph-derived clauses inconsistent, or the graph checker finds a required cut with no
eligible decision.

The browser presents three experiments as equal examples of that method:

| Experiment | Question | Decision |
| --- | --- | --- |
| **Modal-filter placement · Kallio** | Can a small number of filters stop selected private-car through-routes while retaining local access and stated mode assumptions? | Which eligible street segments receive a modal filter? |
| **Flood-resilient access · Otaniemi** | Under an explicit flood/roadworks availability scenario, which minimum corridor commitments let selected origins retain access to a reviewed network exit? | Which unavailable corridor zones must remain passable? |
| **Equitable service coverage · Otaniemi–Tapiola** | Which reviewed public-facility sites can host a hypothetical temporary service so every included population cell has one assignment within stated distance and capacity assumptions? | Which sites open, and which site serves each demand cell? |

No experiment is the product's master case. Together they show how the same
constraint-and-verification pattern can support different geospatial questions. The
presentation-ready **How solvers differ** page explains the division of labour
between routing and constraint solving for colleagues who know GIS but not Z3.

All three use real, frozen source evidence, a React/MapLibre interface, and a FastAPI,
Z3, and NetworkX analytical service. Kallio uses OpenStreetMap; flood-resilient
Otaniemi combines OpenStreetMap, Finnish Environment Institute (Syke), National Land
Survey of Finland (MML), and City of Espoo evidence. Service coverage combines the
frozen OSM walking graph with HSY's 2025 population grid and exact Helsinki
metropolitan Service Map unit records. The service experiment compiles its complete
finite distance matrix before solving instead of using counterexample refinement.

## Shared vocabulary

- A **scenario assumption** is a declared rule that translates source evidence or a
  user choice into model state. For example, the Otaniemi stress rule may treat a
  flood-exposed private-car link as unavailable. It is an input to the experiment,
  not a finding that the road is actually closed or unsafe.
- A **decision variable** is a named Boolean choice Z3 may set while satisfying the
  hard constraints. In Kallio, `blocked[candidate_id]` selects a modal-filter
  location. In flood-resilient Otaniemi, `passable[group_id]` selects a continuity
  commitment. In service coverage, `open[site_id]` selects sites and
  `assign[cell_id, site_id]` gives every included cell exactly one selected site.
- A **continuity commitment** is one Boolean decision grouping connected exposed OSM
  fragments using normalized street-name continuity, or OSM way/highway continuity
  where a fragment is unnamed. Selecting it restores only those grouped fragments
  removed by the enabled flood-exposure assumption; declared fixed roadworks are
  excluded from the groups and can never be overridden. The budget counts the
  Boolean group once, while the result separately reports every expanded physical
  fragment. A selected group belongs to the returned optimum under this encoded
  model, but it may be replaceable in an equally good alternative. Selection is
  never a finding that the corridor is physically safe, legally available,
  operable, funded, or practically protectable.
- A **counterexample** is a concrete NetworkX witness that a proposed assignment
  fails the geographic requirement: for example, a surviving through-route or a
  stranded origin. Its mapped route explains the failure but is not automatically a
  solver constraint.
- A **learned frontier clause** is a necessary logical alternative derived from the
  directed reachable frontier of a failed proposal, such as
  `passable[a] OR passable[b]`. Adding that clause prevents Z3 from repeating a whole
  class of failures; the displayed diagnostic route and the learned clause are
  deliberately kept distinct. In the modal-filter experiment, the corresponding
  lesson is a **path-cut clause**: at least one eligible filter on a surviving
  portal-to-portal route must be selected. Frontier clauses preserve an access path;
  path-cut clauses break a through-path.
- An **analytical capacity** is a declared scenario limit used by the assignment
  model. Experiment 03's value of 5,000 people per candidate is intentionally not a
  measured occupancy, throughput, staffing level, or Service Map fact. It lets the
  interface demonstrate budget/capacity conflicts without fabricating operational
  evidence.
- **Verified feasible** means the selected assignment satisfied the encoded
  constraints and a fresh independent verifier repeated the requested graph and
  arithmetic checks. **Verified UNSAT** means Z3 found no assignment for
  the active hard constraints plus sound graph-derived necessary clauses; a required
  graph cut with no eligible decision is reported as a distinct verifier finding.
  Neither is a forecast about the real city. **Indeterminate** covers timeout,
  cancellation, and data or verification errors, and is never shown as UNSAT.

The [resilient-access methodology](docs/resilient-access-foundation.md#constraint-solver-and-visual-refinement)
documents the full counterexample-guided loop, map artefacts, objectives, proof
boundary, and measured Otaniemi teaching trace. The
[service-coverage method](docs/service-coverage-foundation.md) explains why the
third experiment uses a directly encoded assignment matrix, and its
[evidence note](docs/service-coverage-data-notes.md) records exact source requests,
hashes, counts, CRS transformations, and privacy limitations.

## Current status

All three end-to-end vertical slices are implemented. The flood-resilient Otaniemi
workspace exposes the
source evidence, availability assumption, representative origins, reviewed network
exits, corridor-scale decision units, live candidate/counterexample/refinement
events, and fresh directed-graph verification. It also contains an inspectable
constraint workbench that translates map facts into Boolean variables and learned
frontier clauses for an audience familiar with GIS but new to constraint solvers.

The Kallio modal-filter solver provides locks, forced filters,
portal-pair editing, alternatives, comparison, timeout/cancellation, explanatory
UNSAT output, and desktop/tablet layouts. Four is an upper bound, not a required
count; its audited default scenario uses all four at its verified optimum. See
[the release handoff](docs/reboot-handoff.md) for its measured baseline evidence.

The modal-filter experiment reached a completed research baseline on 2026-08-30.
Further expansion of that particular portal/filter formulation has diminishing
scientific value because the result is strongly controlled by boundary, portal, and
candidate assumptions and is often close to a small graph cut. It nevertheless
remains a first-class experiment, reproducible demonstration, and regression fixture.

The flood-resilient-access experiment extends the shared method into flooding and
planned street works. Its first Otaniemi solver slice includes typed location recipes,
fixed-endpoint OSM/MML/Syke/Espoo adapters, frozen
source evidence, a directed walking/cycling/private-car base network, an
exposure-only coastal-flood overlay, a 2 m terrain-quality-control raster, municipal
address/building evidence, explicit private-car availability assumptions, and a
fresh-graph-verified access solver. See the
[foundation, method, and provenance](docs/resilient-access-foundation.md) and the
[project decision and roadmap](docs/project-status-and-roadmap.md).

The equitable-service-coverage experiment extends the laboratory from changing a
network to choosing facilities and assignments over one. Its frozen
Otaniemi–Tapiola artifact contains 33 published HSY 250 m cells representing 8,554
included residents, ten reviewed Service Map venues, and all 330 demand/site
routes. Each stored total includes a straight-line representative-point snap connector,
the shortest-path length on the frozen OSM walking graph, and a straight-line site
connector. Z3 jointly selects sites and assigns
each whole cell under site-budget, maximum-distance, declared-capacity, force, and
prohibit constraints; a fresh NetworkX check audits both connectors, the exact graph
edge chain, its shortest-path component, each total, and every load. The
default at-most-four request is verified optimal with two selected sites. A
budget-one sensitivity is verified UNSAT because one declared 5,000-person site
cannot accept 8,554 included people. Capacity is a visible analytical assumption,
not a source fact or operational claim. Frozen snapshot
`coverage-4e7e682613eb7d074b8a3341` and its source chain are documented in the
[service-coverage evidence note](docs/service-coverage-data-notes.md).

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
make service-coverage-validate # validate Experiment 03 sources, files, IDs, and routes
make test          # Python plus frontend unit/lint/type checks
make build         # production browser build
make test-e2e      # Playwright desktop and tablet story
make lint
```

Recorded on the 2026-08-31 integration tree: 191 Python tests, 46 Vitest cases, and
all twelve Playwright desktop/tablet stories passed; Ruff, ESLint, strict TypeScript,
the production build, and the frozen-data validators passed. Vite retains the
documented large MapLibre chunk advisory. See the
[acceptance evidence](docs/acceptance-checklist.md) for the scoped checklist.
Experiment 03 subsequently added focused frozen-evidence and tamper-regression tests;
its combined solver, API, and all-suite counts should be read from the final integration
run rather than inferred from the historical totals.

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

The Otaniemi–Tapiola service-coverage slice also has an offline deterministic replay:

```bash
make service-coverage           # rebuild from committed HSY, Service Map, and OSM evidence
make service-coverage-validate  # validate source/published hashes, IDs, matrix, and 330 routes
make service-coverage-test      # frozen-evidence, connector, and tamper-regression checks
```

Only `make service-coverage-refresh` contacts HSY WFS and the ten exact Service Map
unit endpoints. It updates the source manifest and creates a new content-derived
snapshot; it is never run by startup, solving, tests, or the offline targets.

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

## Experiment · Modal-filter placement in Kallio

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

## Experiment · Flood-resilient access in Otaniemi

This experiment uses a 2.743279 km² coastal core in Otaniemi, Espoo with a
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

## Experiment · Equitable service coverage in Otaniemi–Tapiola

The third experiment uses the WGS84 study polygon recorded in
[`service-coverage-otaniemi-tapiola-v1.json`](data/recipes/service-coverage-otaniemi-tapiola-v1.json),
with bbox `[24.802, 60.172, 24.8425, 60.1912]`. Frozen snapshot
`coverage-4e7e682613eb7d074b8a3341` has observation timestamp
`2026-09-01T10:10:33.425Z` and combines:

- 33 published 2025 HSY 250 m population cells, totalling 8,554 included residents;
- ten individually archived, reviewed Helsinki metropolitan Service Map units;
- OSM walking-network snapshot `base-c8dcbcfaca2b2c9498420681`;
- 330 deterministic, connector-inclusive demand/site distances and mapped routes; and
- a compact verification graph with 3,207 nodes and 4,426 directed edges.

HSY's source response was timestamped `2026-09-01T09:18:48.333Z`; every
population feature reports source update `2026-08-05Z`. The Service Map records
were acquired from their exact unit endpoints on 1 September 2026. HSY and Service
Map are CC BY 4.0; OSM is ODbL 1.0. Exact endpoints, query parameters, byte sizes,
SHA-256 values, CRS handling, site IDs, and suppression cautions are in the
[`source-manifest.json`](data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json)
and [evidence note](docs/service-coverage-data-notes.md).

Every candidate receives the same declared 5,000-person assignment bound. That
number is a scenario input for explaining capacity constraints—not a facility
occupancy, current service capacity, staffing estimate, or source attribute. Each
published grid cell is indivisible in this first model and is represented by one
snapped interior point. Privacy-suppressed demand is not imputed.

With at most four sites, a 1,600 m connector-inclusive walking-distance limit,
multiplier 1.0, and a
30-second deadline, the recorded default is verified optimal with two selected
sites, Haukilahden lukio and Tapiolan nuorisotila. Those names are a reproducibility
observation, not a recommendation. All 33 assignments were checked against the
compact walking graph and both analytical snap connectors; the worst route is 1,231.82 m
and the population-weighted mean is 757.83 m. With a site budget of one, Z3 returns
verified UNSAT: maximum
declared capacity is 5,000 against 8,554 included people. A 1,000 m sensitivity
instead exposes a mapped geographic coverage gap. Timeout remains indeterminate in
both cases.

The strongest permitted claim is:

> Under the frozen demand, candidate-site, walking-network, snap-connector, distance, declared
> capacity, and budget assumptions, every included published population cell has
> exactly one verified assignment to a selected site.

It is not an equity finding or service plan. It does not establish complete
population, household-level accessibility, real service demand, facility
availability, accessible entrances, opening hours, queues, staffing, legal use, or
operational capacity.

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
2. NetworkX applies fixed works and the explicit flood stress rule, then restores
   only selected fragments removed by the flood assumption. Fixed roadworks remain
   unavailable and are never restored by a continuity variable.
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

The Kallio modal-filter experiment uses the same pattern for a different decision. Each
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

Service coverage intentionally uses a different division of labour. NetworkX first
compiles the complete 33 × 10 walking-distance relation. Z3 then assigns Boolean
`open[site]` and `assign[cell,site]` variables with exactly-one, implication,
distance, capacity, budget, force, and prohibit constraints. It minimizes site
count, worst distance, population-weighted distance, and selected-site load
imbalance lexicographically. Because the bounded matrix is complete, this slice does
not use counterexample-guided path discovery. A fresh verifier nevertheless checks
every chosen graph route, site load, eligibility rule, and budget before returning
`verified_optimal`. This distinction is part of the lesson: constraint solving does
not require CEGIS when GIS can compile the relevant finite relationship directly.

Timeout, cancellation, solver UNSAT, graph-unblockable routes, and verification/data
errors are separate machine-readable states. The Kallio API enumerates equal-objective
alternatives by fixing the objective vector and excluding earlier structural sets.
Experiment 03's solver core has the corresponding enumeration primitive, but its v1
browser and API do not yet expose a “next solution” workflow.
Tracked assumptions are translated into human-facing UNSAT explanations and suggested
relaxations; assumptions are never changed automatically.

See [architecture and proof boundary](docs/architecture.md), [API](docs/api.md), and
the [acceptance checklist](docs/acceptance-checklist.md). The project conclusion and
research history and next steps are in the
[status and roadmap](docs/project-status-and-roadmap.md).

## Interface

The Otaniemi MapLibre canvas renders the core and context, actual
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

The Kallio modal-filter map renders the study boundary, real street hierarchy and
buildings, protected transit/major-road corridors, eight numbered primary portals,
address clusters, oriented cross-street candidate symbols, live counterexample
routes, selected/forced/locked filters, local access routes, and before/after
directed strong-connectivity regions (mutual private-car reachability).

The service-coverage canvas renders the actual walking graph, HSY grid polygons
weighted by included population, ten reviewed facilities, assignment routes,
selected-site load/capacity state, and the worst-distance or uncovered-cell witness.
Its instrument exposes site budget, distance, declared-capacity multiplier,
force/prohibit controls, real solver stages, reset/cancel, and distinct
optimal/UNSAT/indeterminate summaries. The map is the principal result: a user can
inspect which whole cells are assigned where and see the network route behind the
reported distance, including the two straight-line snap connectors.

The instrument includes a default budget of four, portal-pair selection, force/open
street constraints, emergency-permeability assumption, real SSE proof activity,
cancel/reset, alternatives and comparison, URL-serialized settings, responsive tablet
layout, visible focus states, and reduced-motion support. Solver time is adjustable
under **Access & solver settings** using 5, 10, 30, 60, or 120 seconds; 30 seconds is
the browser default and the selected value is included in the shareable URL. Reaching
that limit is reported as indeterminate/timeout, never as UNSAT.

## Scientific scope and limitations

The strongest service-coverage claim is:

> Under the frozen demand, candidate-site, walking-network, snap-connector, distance, declared
> capacity, and budget assumptions, every included published population cell has
> exactly one verified assignment to a selected site.

It does not establish that the HSY count is current service demand, that a grid-cell
representative describes every resident's walk, or that a Service Map venue is
available, accessible, suitable, staffed, legally usable, or able to serve the
declared load. The 5,000-person limit is an analytical capacity, not a source fact.
The words “equitable service coverage” name the research question; the current
distance-and-load objectives are not a policy definition or finding of equity.
The connector segments join each published representative point and Service Map
coordinate to its nearest graph node as projected straight lines. They are an explicit
analytical approximation, not evidence of an entrance, footpath, crossing, or
universally accessible connection.

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
continuity commitment belongs only to the returned optimum under this encoded graph
and its assumptions; it may be replaceable in an equally good alternative. It is not
a proposed project or a finding that the expanded fragments are safe, legal,
operable, protectable, or funded.

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
scripts/build_service_coverage_scenario.py
                        offline-by-default service evidence compiler/validator
data/source/            frozen OSM, HSY, Service Map, Syke, MML and Espoo evidence
data/recipes/           versioned resilient-access and service-coverage recipes
data/derived/           immutable Kallio, Otaniemi and Otaniemi–Tapiola snapshots
docs/                   method, API, acceptance and reboot notes
```

## Release screenshot set

The committed review artefacts cover the shared experiment index, vocabulary, all
three experiments, their solver explanations, and the location/evidence workflow.
Earlier experiment screenshots retain the historical `four-planters-*`
prefix to avoid breaking existing references:

| State | Desktop | Tablet |
| --- | --- | --- |
| Shared experiment index | [desktop](docs/screenshots/geospatial-constraint-lab-overview-desktop.png) | [tablet](docs/screenshots/geospatial-constraint-lab-overview-tablet.png) |
| Shared model vocabulary | [desktop](docs/screenshots/geospatial-constraint-lab-concepts-desktop.png) | [tablet](docs/screenshots/geospatial-constraint-lab-concepts-tablet.png) |
| Service coverage before solving | [desktop](docs/screenshots/geospatial-constraint-lab-service-coverage-before-desktop.png) | [tablet](docs/screenshots/geospatial-constraint-lab-service-coverage-before-tablet.png) |
| Service coverage verified result | [desktop](docs/screenshots/geospatial-constraint-lab-service-coverage-verified-desktop.png) | [tablet](docs/screenshots/geospatial-constraint-lab-service-coverage-verified-tablet.png) |
| Service coverage infeasible sensitivity | [desktop](docs/screenshots/geospatial-constraint-lab-service-coverage-unsat-desktop.png) | [tablet](docs/screenshots/geospatial-constraint-lab-service-coverage-unsat-tablet.png) |
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
