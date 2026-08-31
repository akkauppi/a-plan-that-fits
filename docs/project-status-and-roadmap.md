# Project decision: conclude Four Planters and pursue resilient access

- **Status:** accepted
- **Decision date:** 2026-08-30
- **First successor vertical slice:** 2026-08-31
- **Four Planters baseline:** commit `52fb267`
- **Successor direction:** Resilient Access

## Decision

Four Planters is complete as a small, reproducible research demonstrator. The
modal-filter experiment will remain a maintained baseline and regression fixture,
but it will not be expanded as the primary research question without new evidence
that changes its scientific value.

The next experiment will study **access resilience under flooding and planned street
works**. These are two instances of the same network-availability problem:

- flooding makes edges unavailable in one or more externally defined hazard
  scenarios;
- roadworks make edges unavailable or mode-restricted during selected time windows,
  with some timing choices under the planner's control.

The successor workspace now defaults to **Otaniemi, Espoo** after a bounded data and
network audit. Otaniemi is deliberately coastal, but its actual hazard exposure is
established from sourced flood layers rather than inferred from its name, shoreline,
or elevation alone.

The application should also stop treating one checked-in polygon as its only entry
point. A user should be able to select or draw a study area, inspect data coverage,
and ask the backend to build a reproducible network scenario for that location.

This decision now has a complete first vertical slice. The Otaniemi experiment
provides typed location recipes, fixed-endpoint OSM/MML/Syke/Espoo adapters, real
frozen source responses, a directed multi-mode OSM network, terrain-quality-control
evidence, an exposure-only coastal-flood overlay, Espoo-derived representative
origins, reviewed outbound graph endpoints, an explicit private-car availability
stress rule, a streaming counterexample-guided solver, and fresh graph verification.
The browser opens this workspace first; the frozen Kallio–Vallila planter map and
solver remain available as the completed baseline. See the
[experiment method and provenance](resilient-access-foundation.md).

The browser exposes the important boundary honestly. The Syke polygons are source
exposure evidence until a user explicitly enables the binary
exposure-as-unavailable rule; MML elevation is never used to close a road. A selected
continuity zone is a minimum dependency under that rule, not a finding that its links
are open, safe, legal, or practically protectable.

## Implemented successor status

The recipe, audit, bounded CLI prototype, frozen network, access solver, and primary
browser story are complete without changing the Kallio fixture. Field-specific
reconciliation and downstream combined-distribution review remain partly complete:

- the `finland-resilient-access-v1` recipe accepts bounded point/radius or simple
  polygon cores and records a distinct network-context buffer in `EPSG:3067`;
- OSM, MML Elevation Model 2 m, Syke sea-flood, and six City of Espoo WFS layers
  have independently
  validated, offline-by-default adapters with fixed endpoints, checksummed raw
  archives, licences, CRS, query, and time records; the derived OSM graph additionally
  records source-field lineage;
- the audited 2.743279 km² Otaniemi polygon and its 750 m context are frozen in
  versioned recipes;
- base snapshot `base-c8dcbcfaca2b2c9498420681` contains 18,710 nodes, 42,077
  directed edges, and 21,526 physical segments from the OSM base timestamp
  `2026-08-30T09:57:36Z`;
- the Syke 1/100 and 1/1000 and Espoo source responses are frozen and replayable;
  their bundle explicitly remains source evidence, not a derived or safe scenario;
- the separate MML WCS 2.0.1 archive contains a validated 1,616 × 1,734 native 2 m
  ASCII grid: 2,802,144 N2000 values, no NoData cells, and an observed range of
  −2.266 to 30.116 m; it remains terrain/QC evidence only;
- a flood builder derives segment exposure and vertical-review flags without
  inferring closure, passability, or safety; frozen exposure snapshot
  `flood-bf45a84ac9ce456045f8932b` records 892 exposed segments at 1/100 and
  1,608 at 1/1000;
- 241 and 528 of those source-exposed fragments, respectively, participate in the
  private-car graph; the interface distinguishes the source count from the effective
  car-unavailability count;
- 297 frozen Espoo address points inside the core are aggregated into 15 deterministic
  500 m representative cells; 1,189 municipal buildings provide map context;
- four exact reviewed outbound graph nodes represent east Kuusisaarentie, south
  Tapiolantie, west Kalevalantie, and north Kehä I; they are not certified safe
  destinations;
- Z3 chooses map-visible contiguous exposure zones under an explicit budget while
  NetworkX discovers directed stranded-origin frontiers, streams diagnostic routes,
  and independently verifies the final graph;
- user-clicked roadworks participate as fixed unavailable segment IDs, while the
  stricter frozen GeoJSON interchange remains available for future import/matching;
  no live Espoo operational feed is claimed.

The default teaching preset (Otaranta to east Kuusisaarentie, 1/1000 stress rule,
budget four) is verified optimal with three continuity-zone commitments, 21 expanded
OSM fragments, 388 m aggregation cost, and +1,093 m mapped detour. The stricter
all-cell/east-exit sensitivity is verified UNSAT at budget four and needs five
commitments. The teaching trace has three singleton frontiers, so it explains the
CEGIS handshake clearly but does not yet demonstrate a difficult combinatorial
solver advantage.

The application now includes a dedicated **How solvers differ** explanation page
for nontechnical colleagues. Its visual comparison separates fixed-network routing
from Z3's search over constrained decision combinations, then shows why the
counterexample-guided experiment uses both. It reuses the measured default trace and
states explicitly that a checked model answer is neither a forecast nor field
approval.

The MML elevation adapter is frozen and replayable without credentials; only an
explicit refresh reads `MML_API_KEY` from local ignored `.env`. The MML Topographic
Database adapter is not implemented. Certified/purpose-reviewed destinations,
works-to-edge import matching, temporal scheduling, multi-scenario optimization,
mode-specific impedance, and vertical road review remain future work. Espoo
evidence remains separately attributed rather than silently replacing OSM topology,
so a field-by-field precedence policy and final combined-database distribution
obligations must be decided before any deeper join.

## Why the original experiment stops here

Four Planters successfully demonstrates frozen geodata, graph construction,
constraint solving, streamed counterexamples, independent verification,
alternatives, and understandable infeasibility. Its scientific ceiling is lower
than its engineering quality, however:

- portal placement and candidate eligibility strongly determine the result;
- the core intervention choice is often close to a small minimum-cut or hitting-set
  problem, so the richer solver machinery is only lightly exercised;
- binary connectivity does not predict traffic, redistribution, safety, emissions,
  physical feasibility, or legal acceptability;
- local access is topological and does not by itself establish acceptable travel
  time, redundancy, or service quality;
- enlarging the map or adding portal pairs would add computation without
  necessarily creating a stronger research result.

Further visual polish or candidate-rule tuning would therefore have diminishing
research value. Necessary maintenance and reusable infrastructure improvements are
still in scope.

## What should be retained

The reusable contribution is a general pattern:

> Choose discrete spatial actions subject to global network requirements, find
> counterexamples in the real graph, and independently verify the final claim.

The successor should retain:

- deterministic source snapshots, checksums, licences, coordinate systems, and
  stable identifiers;
- separate analytical and display geometries;
- the directed graph and explicit mode-permission semantics, adding separately
  constructed mode graphs only where sources and validation support them;
- Z3 decisions combined with NetworkX counterexample discovery;
- explicit lexicographic objectives instead of a hidden aggregate score;
- streamed candidate, counterexample, refinement, and verification events;
- alternatives with the same objective vector;
- tracked assumptions and human-readable UNSAT explanations;
- timeout, cancellation, data error, and verified infeasibility as distinct states;
- fresh-graph final verification before any result receives a verified label.

The Four Planters scenario should remain in the repository as a deterministic
fixture while scenario construction and solver concepts are extracted from its
portal/filter-specific vocabulary.

## Successor research question

The initial question is:

> Across the selected flood and planned-works scenarios, can every included origin
> retain acceptable access to at least one safe destination by each required mode?
> If not, what minimum set of upgrades, temporary connections, work-schedule
> changes, or other explicitly modelled actions restores access?

Here, a **safe destination** means a destination designated by the scenario recipe
and outside the enabled source hazard layer under stated assumptions. It is not a
certified shelter, guaranteed refuge, or independently approved emergency facility.

The current Otaniemi slice deliberately stops short of that term: it uses four
reviewed outbound graph endpoints and labels them network exits, not safe
destinations. The access requirement is OR-shaped—each origin reaches at least one
selected endpoint.

Flooding and roadworks should share one edge-availability abstraction:

```text
available(edge, scenario, time, mode)
  = base_permission(edge, mode)
  ∧ (
      (not hazard_disabled(edge, scenario, mode)
       ∧ not works_closed(edge, time, mode))
      ∨ restored_by_explicit_action(edge, scenario, time, mode)
    )
```

The notation is explanatory rather than executable logic. A restoration action may
repair a scenario closure; it may not silently grant a mode that the base graph
forbids. A new temporary link is a separately declared candidate edge rather than an
implicit restoration of arbitrary nearby edges.

The first implemented version answers directed connectivity and reports mapped
distance/detour. It does not yet have credible travel-time impedance and must not
claim to perform hydraulic simulation, predict road capacity, or approve temporary
traffic arrangements.

## Otaniemi pilot

Otaniemi is the successor-workspace default, not a hard-coded permanent boundary.
The checked pilot polygon was selected after inspecting:

- coastline, low terrain, and the coverage of published flood-hazard scenarios;
- the directed street, walking, cycling, and emergency-relevant networks;
- bridges, underpasses, tunnels, campus paths, and limited-access links;
- building/address origins and candidate safe destinations;
- public-transport corridors and infrastructure that must remain protected;
- graph size and the number of meaningful alternative access routes.

The pilot should include enough inland context that the solver cannot “succeed” by
placing the study boundary immediately beside the vulnerable area. Boundary and
destination sensitivity must be reported, not hidden.

## Location-driven scenario builder

The intended end-state workflow is:

1. The user searches for a place or clicks a map location, then chooses a bounded
   point-and-radius area or draws and adjusts a polygon.
2. The browser reports area, expected graph size, supported data sources, and any
   coverage warnings before starting acquisition.
3. The backend accepts a versioned scenario recipe and builds it asynchronously.
4. Source adapters download only the requested area and record response timestamps,
   query parameters, licences, checksums, and failures.
5. Data is normalized to ETRS89 / TM35FIN (`EPSG:3067`) for metric analysis, with
   original source identifiers retained.
6. The builder constructs mode graphs, snaps origins and destinations, intersects
   hazards and works with edges, validates references, and creates browser geometry.
7. A content-addressed snapshot is frozen and cached. Solving uses that snapshot and
   never depends on upstream services being available.
8. The browser opens the scenario only after validation succeeds, and distinguishes
   incomplete coverage from a valid empty result.

The current bounded command-line foundation implements recipe validation, source
preflight/acquisition, the OSM base build, and the Syke exposure derivation. The
frozen Otaniemi artifacts are then loaded by the resilience runtime. Its exact
offline reconstruction path is:

```bash
make otaniemi-sources
make otaniemi-elevation
make otaniemi-base
make otaniemi-flood
```

Only explicit refresh targets contact remote endpoints. Recipe parameters cannot
substitute arbitrary URLs. Raw source archives and derived snapshots are
content-addressed; selection-specific bundle manifests and latest pointers advance
atomically on explicit refresh. Offline replay validates the selected current
archives and outputs. See the
[foundation guide](resilient-access-foundation.md) for the full CLI and source
identities.

The service-facing location workflow uses a bounded asynchronous job rather than
holding one request open for downloads and preprocessing. It presently constructs a
base-network snapshot; hazard, municipal-context, and resilient-access analysis
jobs still need to be added to that workflow:

```text
GET  /api/scenario-builder/catalog
POST /api/scenario-builder/preflight
POST /api/scenario-builder/jobs
GET  /api/scenario-builder/jobs/{job_id}
GET  /api/scenario-builder/jobs/{job_id}/events?after=N
POST /api/scenario-builder/jobs/{job_id}/cancel
```

Area, feature-count, duration, and download limits are required. Arbitrary unbounded
remote queries must not be exposed through the public browser. Jobs are offline by
default; a live OSM refresh requires the exact explicit acknowledgement
`confirm_live_source_refresh: "REFRESH_OSM"`.

Version 1 is explicitly limited to Finland and uses `EPSG:3067`; Espoo-only adapters
are enabled only when the requested polygon lies within their documented coverage.
The builder must reject unsupported polygons with a coverage explanation. Supporting
another country would require a new CRS/source profile, not silent fallback data.

### Current generalization constraints to remove

The two frozen runtimes must not be mistaken for a general scenario factory:

- `scripts/build_scenario.py` still hard-codes the Kallio–Vallila bbox, paths,
  name, source archive, portal defaults, and scenario ID;
- the new recipe/base/source/flood commands exist beside it; the Otaniemi runtime
  currently assembles its analysis contract from those exact latest frozen artifacts
  rather than a general published scenario package;
- `services/solver/scenario.py` resolves one fixed derived dataset;
- `services/solver/otaniemi_resilience.py` resolves one fixed Otaniemi evidence set;
- the Kallio baseline still uses planter/portal vocabulary by design, while the
  Otaniemi workspace uses origin/gateway/continuity vocabulary;
- a custom builder job publishes only a base-network artifact and cannot yet load it
  into the resilience runtime or acquire the matching hazard and municipal evidence.

Generalization should replace these assumptions through typed configuration and
source adapters while keeping the existing fixture byte-reproducible. It should not
begin as a broad rewrite that makes the verified baseline untestable.

## Candidate data-source stack

Each source remains an adapter with explicit precedence and conflict reporting. No
source should silently overwrite another.

| Source | Role | Current implementation and caution |
| --- | --- | --- |
| OpenStreetMap | Routable street/path semantics, one-way and access tags, names, initial topology | Implemented and frozen for Otaniemi. The v1 graph records private-car, walking, and cycling permissions and retains vertical tags, but not turn restrictions, conditional access, barriers, emergency, transit, or service semantics. Generic access no longer promotes an inappropriate highway/mode, but `destination` and `delivery` are still flattened to Boolean permission and must be contextualized before through-routing. Municipal layers do not silently replace its topology. |
| [National Land Survey of Finland (MML/NLS) Elevation model 2 m](https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/elevation-model-2-m) | Ground elevation, low-point inspection, profiles, and hazard-layer quality checks | Implemented as a fixed WCS 2.0.1 `korkeusmalli_2m` adapter and frozen separately under `data/recipes/espoo-otaniemi-coastal-elevation-v1.json`. The query bbox `[377872, 6671958, 381104, 6675426]` in `EPSG:3067` produced 2,802,144 valid 2 m N2000 cells under CC BY 4.0. Offline replay needs no credential; explicit refresh reads `MML_API_KEY` locally. Elevation alone is not a flood model or passability rule. |
| [MML/NLS Topographic Database](https://www.maanmittauslaitos.fi/en/geopackage) | National fallback for roads, buildings, waterways, and land features | Open GeoPackage/custom-area data may complement OSM. A reconciliation policy and per-feature provenance are required. |
| [City of Espoo open geographic data](https://www.espoo.fi/en/open-data-of-the-geographic-information-unit) | Street areas, buildings, addresses, cycling routes, water features, and selected municipal context | Six WFS layers are implemented as exact frozen GML responses with CC BY 4.0 provenance. Buildings are rendered and 297 in-core address points form 15 representative cells; source timestamps are response times and coverage remains `unknown`. Municipal evidence does not overwrite OSM topology. |
| [Finnish Environment Institute (Syke) web map services](https://www.syke.fi/en/environmental-data/open-web-services/web-map-services) | Published flood-hazard, inundation, and risk scenarios | The 1/100 and 1/1000 sea-flood layers are frozen and intersected with the base graph as exposure evidence. The runtime may treat exposure as unavailable only under a separate explicit user stress rule; the source never asserts passability. Syke requires a unique application identifier for long-term or intensive WFS use. |
| Espoo street-works or temporary-traffic-arrangement data | Actual works, closure windows, affected modes, and temporary routes | No suitable open operational feed is confirmed. A strict versioned GeoJSON contract exists, and exact user-clicked graph IDs can act as fixed closures, but imported matching and temporal analysis are not implemented. |

The City of Espoo's
[temporary traffic-arrangement guidance](https://www.espoo.fi/en/temporary-traffic-arrangements)
confirms that works planning must account for multiple travel modes and accessibility.
That is useful policy context, but it is not itself an operational closure dataset or
a substitute for municipal approval.

The checked OSM–Syke exposure overlay keeps both inputs, licences, attribution, and
lineage separately identifiable. Before distributing a future field-reconciled
database that joins OSM with MML or Espoo attributes, complete a specific review of
licence compatibility and the resulting ODbL/CC BY database-distribution obligations.

## Proposed analytical model

### Inputs

- one immutable base network snapshot;
- walking, cycling, private-car, public-transport-relevant, and emergency-relevant
  permissions where the data supports them;
- origins such as address/building clusters and user-selected critical sites;
- destinations such as safe exits, shelters, hospitals, emergency depots, or
  user-defined service locations;
- one or more flood scenarios with source-specific probability or descriptive labels;
- planned works with time windows, affected edges, affected modes, and fixed or
  schedulable dates;
- candidate upgrades and temporary treatments, each with explicit eligibility
  assumptions;
- user-selected service thresholds and solver deadline.

### Hard constraints

- every included origin reaches at least one permitted safe destination in each
  enabled scenario/time bucket;
- critical origins may require two sufficiently independent routes where this is
  explicitly requested and defined;
- maximum detour or travel-time thresholds are enforced only for modes with credible
  impedance data;
- protected infrastructure and fixed work windows remain fixed;
- action budgets, incompatibilities, lead times, and construction sequencing hold;
- mode permissions are never inferred from the visual treatment alone.

### Decisions

- which candidate links to upgrade or protect;
- where a candidate temporary link or controlled passage is deployed under its
  stated eligibility assumptions;
- which flexible works occupy each time bucket;
- which permitted diversion or reversible arrangement is active;
- which demand/service assumptions are relaxed only when the user explicitly asks
  for a relaxation solve.

### Objectives

After enforcing every hard requirement as a feasibility constraint, minimize the
following documented objectives lexicographically:

1. permanent intervention cost;
2. temporary measures and work rescheduling;
3. worst-case access time or detour;
4. the number of materially affected origins;
5. plan fragmentation, preferring simple and legible actions.

The UI must expose the objective vector and distinguish physical cost, scheduling
disruption, and access quality.

### Verification

For every scenario and time bucket, an independent verifier using a fresh graph plus
the encoded plan constraints must check:

- destination reachability for every included origin and mode;
- travel time/distance and threshold compliance;
- route independence where requested;
- selected actions, protected links, work windows, and budget compliance;
- the worst scenario and the exact counterexample route or stranded origin.

The strongest initial claim should be:

> Under the frozen network, source hazard layers, works schedule, mode permissions,
> destinations, candidate actions, and service thresholds, every included origin
> retains the verified access reported for each analysed scenario and time bucket.

It must not claim to predict flood hydraulics, guarantee road capacity, certify
emergency response times, approve a works plan, or establish the feasibility of an
intervention that has not been independently assessed.

## Delivery sequence

### 1. Generalize without breaking the baseline — contract foundation complete

- introduce a versioned scenario recipe and source-adapter contract;
- separate generic graph, scenario, action, objective, and verification concepts
  from planter/portal vocabulary;
- retain Four Planters unchanged as an end-to-end fixture;
- add source precedence, field lineage, and licence manifests.

The typed recipe, adapter, metadata, and lineage seam is implemented. The first
generic availability, continuity-decision, access-analysis, and fresh-verification
objects now support the Otaniemi question. Field-specific reconciliation is still
deferred because municipal evidence has not been allowed to silently overwrite OSM.

### 2. Build scenarios from a selected location — partial

- add place search, map-point/radius selection, polygon drawing/editing, and
  area/data-coverage feedback;
- implement asynchronous build progress, cancellation, cache reuse, and clear source
  errors;
- create and freeze the first Otaniemi base-network snapshot;
- keep all ordinary solves offline and reproducible.

The Otaniemi snapshot and bounded offline/refresh job path exist. The first browser
control supports the frozen pilot and a clickable bounded Finland point/radius
recipe with preflight, progress, cancellation, explicit refresh confirmation, and a
verified exposure summary. The picker deliberately uses an offline coordinate
canvas rather than a live tile dependency. Place search, polygon drawing/editing,
automated acquisition/derivation of all non-OSM inputs, origin/gateway review, and
loading a built graph into the analysis runtime remain.

### 3. Establish the flood experiment — first solver slice complete

- ingest MML elevation and Syke flood scenarios for the selected polygon;
- classify edge availability by sourced scenario, with inspectable intersection
  geometry and thresholds;
- define origins, safe destinations, critical sites, and service requirements;
- report vulnerability first, before adding intervention decisions;
- then add only defensible upgrade or temporary-link candidates.

The two audited Syke scenarios are frozen and their horizontal intersections with
the OSM segments are derived. The exact MML elevation window is also frozen for
terrain/vertical QA. The first deliberately conservative availability experiment is
implemented: 15 Espoo-address representatives, four reviewed outbound graph exits,
an explicit exposure-as-unavailable toggle, corridor-scale Boolean continuity
commitments, streamed CEGIS events, and fresh directed-graph verification. It stops
before hydraulic passability, certified destinations, road-elevation review,
travel-time thresholds, or independently routed non-car modes.

### 4. Add roadworks and time — fixed map closures plus interchange

- define a documented works import format before depending on a live municipal feed;
- model fixed and flexible work windows and affected modes;
- verify access in every time bucket;
- produce conflict explanations such as which simultaneous closures strand which
  origins and which schedule relaxation repairs the conflict.

The frozen GeoJSON interchange and schedule validation are implemented. The browser
can also declare exact displayed graph segments as fixed private-car works closures;
they combine with the enabled flood rule and are excluded from solver decisions.
Imported-geometry matching, time buckets, flexible scheduling, conflict analysis,
and an adequate documented works case remain.

### 5. Combine and evaluate — initial spatial interaction only

- solve flood scenarios with concurrent fixed or scheduled works;
- compare against shortest-path, minimum-cut, and appropriate CP-SAT/MIP baselines;
- measure sensitivity to boundary, destination, hazard, impedance, and source choices;
- test with domain reviewers before presenting the output as planning support.

The binary flood-plus-user-clicked-fixed-works combination now runs end to end. It
does not yet contain time, flexible choices, mode-specific effects, baseline
comparisons, or practitioner review, so it does not satisfy the research
continuation criteria below.

## Research continuation criteria

The successor warrants continued study only if the pilot demonstrates more than a
relabelled minimum cut. Before a research claim, require:

- at least one meaningful multi-scenario or temporal interaction;
- a result that changes under a documented policy constraint, not an arbitrary UI
  setting;
- independent baselines and reproducible performance measurements;
- sensitivity analysis for data and boundary assumptions;
- a credible real or documented roadworks case;
- feedback from at least one relevant domain practitioner;
- an explanation that helps a user understand or repair an infeasible request.

If suitable flood coverage, roadworks data, or defensible actions are unavailable,
the project should report that limitation and stop rather than replace them with
fabricated operational data.

## Immediate next tasks

1. Find and freeze one documented works case with explicit mode, direction, and time
   semantics; match it to graph links with reviewable confidence.
2. Add time buckets and let Z3 choose among genuinely flexible work windows while
   requiring access in every enabled flood/work combination. This is the most
   valuable next extension because it creates coupled choices beyond singleton cuts.
3. Add purpose-reviewed destinations and sensitivity views for exit choice, origin
   grid, study context, flood tier, and the exposure-as-unavailable rule.
4. Inspect bridge/tunnel/layer cases and sample MML terrain only for reviewable
   vertical/low-point QA, keeping Syke as the published hazard source and never
   deriving a home-made flood extent.
5. Compare the resulting temporal model with shortest-path, minimum-cut, and an
   appropriate scheduling baseline; report when Z3 adds value and when it does not.
6. Complete custom-location promotion: acquire/validate every required source,
   review origins and exits, derive exposure, and select an immutable artifact before
   loading a new graph into the resilience runtime.
7. Seek practitioner review before giving the experiment a planning-support product
   identity.

No application rename or destructive migration is required. The new experiment
should earn its own product identity only after a real temporal works case,
sensitivity evidence, and practitioner review.
