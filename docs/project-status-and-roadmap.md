# Project decision: conclude Four Planters and pursue resilient access

- **Status:** accepted
- **Decision date:** 2026-08-30
- **Four Planters baseline:** commit `52fb267`
- **Provisional successor:** Resilient Access

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

The first default study area will move to **Otaniemi, Espoo**, subject to a data and
network audit. Otaniemi is a deliberately coastal candidate, but its actual hazard
exposure must be established from sourced flood layers rather than inferred from its
name, shoreline, or elevation alone.

The application should also stop treating one checked-in polygon as its only entry
point. A user should be able to select or draw a study area, inspect data coverage,
and ask the backend to build a reproducible network scenario for that location.

This decision is now partly implemented. A separate Otaniemi foundation provides
typed location recipes, fixed-endpoint OSM/Syke/Espoo adapters, real frozen source
responses, a directed multi-mode OSM network, an exposure-only coastal-flood
overlay, and a strict frozen roadworks interchange. The current planter map and Z3
solver still open the frozen Kallio–Vallila scenario; Otaniemi is not yet a
resilient-access solve. See the
[foundation architecture and provenance](resilient-access-foundation.md).

The browser now exposes this boundary honestly: a user can select the frozen pilot
or click/enter a bounded point and radius, inspect verified local source state,
rebuild a base snapshot asynchronously, and see the verified Otaniemi exposure
totals. It does not yet turn those totals into unavailable roads or a resilience
claim.

## Implemented foundation status

The recipe, audit, bounded CLI prototype, and frozen base-network tasks are complete
at command-line/data-contract level without changing the Kallio fixture. The
field-specific reconciliation and downstream combined-distribution review are only
partly complete:

- the `finland-resilient-access-v1` recipe accepts bounded point/radius or simple
  polygon cores and records a distinct network-context buffer in `EPSG:3067`;
- OSM, Syke sea-flood, and six City of Espoo WFS layers have independently
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
- a flood builder derives segment exposure and vertical-review flags without
  inferring closure, passability, or safety; frozen exposure snapshot
  `flood-bf45a84ac9ce456045f8932b` records 892 exposed segments at 1/100 and
  1,608 at 1/1000;
- roadworks can be validated only as an explicit user-supplied frozen GeoJSON with
  affected modes and restriction semantics; no live Espoo operational feed is
  claimed.

MML elevation and topographic adapters are not implemented because programmatic
access needs an operator API key. Origins, reviewed safe destinations, flood-to-edge
availability policy, works-to-edge matching, vulnerability verification,
optimization, and browser integration with the resilient-access solver remain
future work. Espoo evidence remains separate rather than reconciled into OSM, so a
field-by-field precedence policy and the final combined-database distribution
obligations must be decided before that join.

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

The first version should answer connectivity and travel-time questions, not claim to
perform hydraulic simulation, predict road capacity, or approve temporary traffic
arrangements.

## Otaniemi pilot

Otaniemi is the proposed default, not a hard-coded permanent boundary. The final
pilot polygon should be selected after inspecting:

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
preflight/acquisition, the OSM base build, and the Syke exposure derivation. Its
exact offline path is:

```bash
make otaniemi-sources
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

### Current constraints to remove

The original planter runtime is intentionally single-scenario and must not be
mistaken for the new build foundation:

- `scripts/build_scenario.py` still hard-codes the Kallio–Vallila bbox, paths,
  name, source archive, portal defaults, and scenario ID;
- the new recipe/base/source/flood commands exist beside it, but they do not emit a
  Four Planters solver graph or a complete resilient-access scenario;
- `services/solver/scenario.py` resolves one fixed derived dataset;
- `services/solver/api.py` loads one scenario and solver into memory at startup;
- browser product text, Helsinki status labels, attribution, and intervention
  vocabulary still assume Four Planters outside the separate study-area builder.

Generalization should replace these assumptions through typed configuration and
source adapters while keeping the existing fixture byte-reproducible. It should not
begin as a broad rewrite that makes the verified baseline untestable.

## Candidate data-source stack

Each source remains an adapter with explicit precedence and conflict reporting. No
source should silently overwrite another.

| Source | Role | Current implementation and caution |
| --- | --- | --- |
| OpenStreetMap | Routable street/path semantics, one-way and access tags, names, initial topology | Implemented and frozen for Otaniemi. The v1 graph records private-car, walking, and cycling permissions and retains vertical tags, but not turn restrictions, conditional access, barriers, emergency, transit, or service semantics. Generic access no longer promotes an inappropriate highway/mode, but `destination` and `delivery` are still flattened to Boolean permission and must be contextualized before through-routing. Municipal layers do not silently replace its topology. |
| [National Land Survey of Finland (MML/NLS) Elevation model 2 m](https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/elevation-model-2-m) | Ground elevation, low-point inspection, profiles, and hazard-layer quality checks | Not implemented: programmatic access needs `MML_API_KEY`. Open 2 m raster in `EPSG:3067` with N2000 heights under CC BY 4.0. Elevation alone is not a flood model. |
| [MML/NLS Topographic Database](https://www.maanmittauslaitos.fi/en/geopackage) | National fallback for roads, buildings, waterways, and land features | Open GeoPackage/custom-area data may complement OSM. A reconciliation policy and per-feature provenance are required. |
| [City of Espoo open geographic data](https://www.espoo.fi/en/open-data-of-the-geographic-information-unit) | Street areas, buildings, cycling routes, water features, and selected municipal context | Six WFS layers are implemented as exact frozen GML responses with CC BY 4.0 provenance. The snapshot is enrichment evidence only; source timestamps are response times and coverage remains `unknown`. |
| [Finnish Environment Institute (Syke) web map services](https://www.syke.fi/en/environmental-data/open-web-services/web-map-services) | Published flood-hazard, inundation, and risk scenarios | The 1/100 and 1/1000 sea-flood layers are frozen and intersected with the base graph as exposure evidence. Passability is not inferred. Syke requires a unique application identifier for long-term or intensive WFS use. |
| Espoo street-works or temporary-traffic-arrangement data | Actual works, closure windows, affected modes, and temporary routes | No suitable open operational feed is confirmed. A strict versioned GeoJSON contract is implemented for user-supplied frozen scenarios, but matching and temporal analysis are not. |

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

The typed recipe, adapter, metadata, and lineage seam is implemented. Generic
solver actions, objectives, and verification remain to be extracted only when the
first vulnerability question requires them. Field-specific reconciliation is also
deferred because Espoo evidence has not yet been joined to OSM.

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
and loading a built graph into an analysis runtime remain.

### 3. Establish the flood experiment — exposure foundation only

- ingest MML elevation and Syke flood scenarios for the selected polygon;
- classify edge availability by sourced scenario, with inspectable intersection
  geometry and thresholds;
- define origins, safe destinations, critical sites, and service requirements;
- report vulnerability first, before adding intervention decisions;
- then add only defensible upgrade or temporary-link candidates.

The two audited Syke scenarios are frozen and their horizontal intersections with
the OSM segments are derived. This stops before availability: MML elevation,
vertical review, thresholds, origins, destinations, and vulnerability reachability
are not complete.

### 4. Add roadworks and time — interchange only

- define a documented works import format before depending on a live municipal feed;
- model fixed and flexible work windows and affected modes;
- verify access in every time bucket;
- produce conflict explanations such as which simultaneous closures strand which
  origins and which schedule relaxation repairs the conflict.

The frozen GeoJSON interchange and schedule validation are implemented. Network
matching, time buckets, conflict analysis, and an adequate real works case remain.

### 5. Combine and evaluate — not started

- solve flood scenarios with concurrent fixed or scheduled works;
- compare against shortest-path, minimum-cut, and appropriate CP-SAT/MIP baselines;
- measure sensitivity to boundary, destination, hazard, impedance, and source choices;
- test with domain reviewers before presenting the output as planning support.

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

1. Inspect the real exposure overlay, resolve bridge/tunnel/layer cases, and define
   one conservative, sourced flood-to-edge-availability policy without presenting it
   as physical truth.
2. Select and document origin clusters, reviewed safe destinations outside the
   enabled hazard, supported modes, and initial distance/time service thresholds.
3. Implement a fresh-graph vulnerability verifier for every origin, mode, and flood
   scenario; report retained access, stranded origins, worst detours, and exact
   counterexample routes before adding decisions.
4. Join Espoo buildings/addresses as provenance-preserving origin evidence and use
   municipal street/cycling layers for discrepancy review, not silent topology
   replacement.
5. Complete the browser path from a successfully built snapshot to an inspectable
   exposure/vulnerability map. Keep an immutable artifact selector so a later live
   refresh cannot silently change an open analysis.
6. Obtain `MML_API_KEY`, implement the exact elevation-window adapter, and use the
   raster for vertical/low-point QA rather than home-made flood extents.
7. Find and freeze one documented works case with explicit closure semantics, then
   match it to the graph with reviewable confidence and test a first temporal
   interaction.

No application rename or destructive migration is required for these tasks. The new
experiment should earn its own product identity after the data audit and first
verified result.
