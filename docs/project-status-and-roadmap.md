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

This document records a direction, not completed functionality. The current browser
still opens the frozen Kallio–Vallila Four Planters scenario.

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

The intended workflow is:

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

A possible future command is:

```bash
python scripts/build_scenario.py \
  --place "Otaniemi, Espoo" \
  --polygon scenario-area.geojson \
  --sources osm,mml,espoo,syke \
  --scenario-type resilient-access
```

The flags are a proposed interface, not currently implemented. The service-facing
equivalent should use a small asynchronous API rather than holding one HTTP request
open for downloads and preprocessing:

```text
POST /api/scenarios/build
GET  /api/scenarios/build/{job_id}/events
POST /api/scenarios/build/{job_id}/cancel
GET  /api/scenarios/{scenario_id}
```

Area, feature-count, duration, and download limits are required. Arbitrary unbounded
remote queries must not be exposed through the public browser.

Version 1 is explicitly limited to Finland and uses `EPSG:3067`; Espoo-only adapters
are enabled only when the requested polygon lies within their documented coverage.
The builder must reject unsupported polygons with a coverage explanation. Supporting
another country would require a new CRS/source profile, not silent fallback data.

### Current constraints to remove

The present code is intentionally single-scenario and must not be mistaken for the
proposed builder:

- `scripts/build_scenario.py` currently hard-codes the Kallio–Vallila bbox, paths,
  name, source archive, portal defaults, and scenario ID;
- its command line supports refresh/rebuild/validation, not a place, polygon, or
  versioned scenario recipe;
- `services/solver/scenario.py` resolves one fixed derived dataset;
- `services/solver/api.py` loads one scenario and solver into memory at startup;
- browser product text, Helsinki status labels, attribution, and intervention
  vocabulary assume Four Planters.

Generalization should replace these assumptions through typed configuration and
source adapters while keeping the existing fixture byte-reproducible. It should not
begin as a broad rewrite that makes the verified baseline untestable.

## Candidate data-source stack

Each source remains an adapter with explicit precedence and conflict reporting. No
source should silently overwrite another.

| Source | Proposed role | Current evidence and caution |
| --- | --- | --- |
| OpenStreetMap | Routable street/path semantics, one-way and access tags, names, initial topology | Keep the ODbL snapshot model. Municipal layers may provide different geometry or fields; they must not automatically replace OSM topology without geometry/schema validation and field-specific precedence. |
| [National Land Survey of Finland (MML/NLS) Elevation model 2 m](https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/elevation-model-2-m) | Ground elevation, low-point inspection, profiles, and hazard-layer quality checks | Open 2 m raster in `EPSG:3067` with N2000 heights under CC BY 4.0. Elevation alone is not a flood model. Record quality class and delivery date. |
| [MML/NLS Topographic Database](https://www.maanmittauslaitos.fi/en/geopackage) | National fallback for roads, buildings, waterways, and land features | Open GeoPackage/custom-area data may complement OSM. A reconciliation policy and per-feature provenance are required. |
| [City of Espoo open geographic data](https://www.espoo.fi/en/open-data-of-the-geographic-information-unit) | Street areas, buildings, cycling routes, water features, and selected municipal context | Espoo publishes WFS layers including weekly street areas and buildings. Confirm reuse and redistribution terms per feature type before ingestion; capture the schema, update timestamp, and applicable licence in every snapshot. |
| [Finnish Environment Institute (Syke) web map services](https://www.syke.fi/en/environmental-data/open-web-services/web-map-services) | Published flood-hazard, inundation, and risk scenarios | Prefer sourced hazard polygons/rasters over a home-made sea-level threshold. Check Otaniemi coverage and scenario semantics. Syke requires a unique application identifier for long-term or intensive OGC API Features, WFS, or WCS use. |
| Espoo street-works or temporary-traffic-arrangement data | Actual works, closure windows, affected modes, and temporary routes | A suitable open machine-readable operational feed has not yet been confirmed. Audit the city map/service and terms. Until then, accept a versioned GeoJSON/CSV works scenario and label it user-supplied. |

The City of Espoo's
[temporary traffic-arrangement guidance](https://www.espoo.fi/en/temporary-traffic-arrangements)
confirms that works planning must account for multiple travel modes and accessibility.
That is useful policy context, but it is not itself an operational closure dataset or
a substitute for municipal approval.

Before distributing a combined snapshot, document licence compatibility and the
resulting attribution/database-distribution obligations for ODbL OpenStreetMap data,
CC BY MML data, each Espoo layer, and each Syke layer. Store source geometries and
lineage separately enough to audit that decision.

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

### 1. Generalize without breaking the baseline

- introduce a versioned scenario recipe and source-adapter contract;
- separate generic graph, scenario, action, objective, and verification concepts
  from planter/portal vocabulary;
- retain Four Planters unchanged as an end-to-end fixture;
- add source precedence, field lineage, and licence manifests.

### 2. Build scenarios from a selected location

- add place search, map-point/radius selection, polygon drawing/editing, and
  area/data-coverage feedback;
- implement asynchronous build progress, cancellation, cache reuse, and clear source
  errors;
- create and freeze the first Otaniemi base-network snapshot;
- keep all ordinary solves offline and reproducible.

### 3. Establish the flood experiment

- ingest MML elevation and Syke flood scenarios for the selected polygon;
- classify edge availability by sourced scenario, with inspectable intersection
  geometry and thresholds;
- define origins, safe destinations, critical sites, and service requirements;
- report vulnerability first, before adding intervention decisions;
- then add only defensible upgrade or temporary-link candidates.

### 4. Add roadworks and time

- define a documented works import format before depending on a live municipal feed;
- model fixed and flexible work windows and affected modes;
- verify access in every time bucket;
- produce conflict explanations such as which simultaneous closures strand which
  origins and which schedule relaxation repairs the conflict.

### 5. Combine and evaluate

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

1. Define the generic scenario recipe and source-adapter interfaces on paper and in
   typed schemas.
2. Audit a candidate Otaniemi polygon against OSM, Espoo WFS, MML elevation, and Syke
   flood coverage.
3. Decide field-specific precedence, licence compatibility, output obligations, and
   attribution for overlapping sources.
4. Prototype a bounded command-line Otaniemi build before creating the browser
   location picker.
5. Freeze and validate the resulting base snapshot.
6. Implement vulnerability-only flood reachability before optimization.
7. Specify the works GeoJSON/CSV interchange and find one documented case.

No application rename or destructive migration is required for these tasks. The new
experiment should earn its own product identity after the data audit and first
verified result.
