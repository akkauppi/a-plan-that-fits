# Geospatial Constraint Lab: reboot handoff

> The Kallio experiment was originally released under the Four Planters name and
> entered completed-baseline status on 2026-08-30. This file preserves that
> reproducible release evidence while also recording the current three-experiment
> Geospatial Constraint Lab handoff. Shared work should follow the
> [project history and roadmap](project-status-and-roadmap.md) without weakening any
> frozen experiment's regression contract.

- **Final baseline evidence:** 2026-08-28
- **Lifecycle decision recorded:** 2026-08-30
- **Flood-resilient-access vertical slice:** 2026-08-31
- **Equitable-service-coverage vertical slice:** 2026-09-03

This file began as the reboot note and now records the reproducible release state.
The frozen source snapshot is unchanged; the portal model, access objective,
independent verifier, timeout controls, and release interface have been corrected
since the initial checkpoint.

## Current lab state

The browser presents three equal experiments under the Geospatial Constraint Lab
umbrella:

1. modal-filter placement on the frozen Kallio private-car graph;
2. flood/roadworks access resilience on the frozen Otaniemi graph; and
3. capacitated public-service allocation on the frozen Otaniemi–Tapiola walking
   graph.

The first two alter network availability and use counterexample-guided graph
refinement. The third compiles its complete 33 × 10 network-distance relation first
and lets Z3 choose sites and assignments directly. All distinguish verified
feasibility, verified infeasibility, and indeterminate outcomes, and all keep source
facts separate from analytical assumptions.

## Kallio baseline implementation

- A React/MapLibre browser instrument with real frozen Helsinki streets, buildings,
  protected features, boundary portals, address clusters, oriented candidate filters,
  live counterexample routes, local-access inspection, and before/after connectivity.
- A FastAPI SSE service using Z3 for intervention choices and NetworkX for fresh-graph
  final verification.
- Budget, portal-pair, force-filter, lock-open, objective-mode, emergency-assumption,
  cancellation, reset, equal-objective alternative, comparison, and shareable URL
  controls.
- Adjustable browser deadlines of 5, 10, 30, 60, and 120 seconds, with 30 seconds as
  the default. Timeout is an indeterminate terminal state and is never reported as
  UNSAT.
- Distinct verified-optimal, verified-UNSAT, timeout, cancelled, unblockable-route,
  and data/verification-error outcomes.

The audited default two-pair Helsinki request has a verified optimum using four
filters under a maximum budget of four. The budget is an upper bound, not an
exact-count requirement. A feasible result reaches a verified label only after a
fresh NetworkX graph confirms the requested private-car disconnections and local
address-cluster egress. Verified UNSAT instead relies on Z3 over sound learned route
clauses and hard constraints, or on a specific unblockable graph-verifier finding.

## Kallio frozen scenario and portal semantics

The study bbox is `[24.9435, 60.1854, 24.9635, 60.1962]`, about 1.33 km² across
Kallio, Alppiharju, and western Vallila. The OpenStreetMap base timestamp is
`2026-08-25T22:24:24Z`; the frozen snapshot ID is
`osm-20260825T222424Z-d8c48f77151b`.

The derived dataset contains:

```text
1,342 analytical nodes
2,408 directed private-car edges
272 eligible modal-filter candidates
384 base-eligible local segments before analytical setbacks
80 otherwise eligible segments excluded by the analysis-boundary terminal zone
79 otherwise eligible segments excluded by primary-portal approach zones
47 segments shared by both setbacks / 32 additional portal-approach exclusions
68 retained boundary-crossing records
38 analytical portal clusters / 8 browser primary portals
182 address clusters / 631 building footprints
678 protected display features
```

Portal clustering is deterministic contiguous complete-link grouping within each
boundary side, with a hard 60 m maximum diameter. Every crossing belongs to exactly
one cluster and keeps its OSM way/node, road-class, direction, point, and cluster
provenance. The browser exposes two named, spatially distributed primary clusters per
side. A selected pair quantifies over every member node in both clusters, while local
access may terminate at any of the 38 analytical portals.

Candidates use a 60 m projected analysis-boundary setback measured from each
physical-segment midpoint in EPSG:3067. A static second rule excludes a base-eligible
midpoint within 120 m of the nearest actual crossing point belonging to any of the
eight primary/selectable portals. It uses neither the portal marker nor only the
currently selected pairs, and it does not use all 38 analytical portals. Primary
selection is computed before this approach rule, so the exclusion cannot move its
own source portals. Segments in either zone remain open and ineligible for
intervention; they are not classified as protected transit. The unioned approach
zones and their source IDs are exported for browser inspection.

The explicit audited defaults are Vilhonvuorenkuja ↔ Agricolankuja
(southern cross-neighbourhood permeability) and Pälkäneentie ↔ Alppikatu (western
cross-neighbourhood permeability). The budget-four optimum uses four filters outside
both zones. These setbacks reduce terminal-capping solutions, but they are analytical
bias controls rather than physical or legal siting rules.

## Kallio objectives and connectivity semantics

The objectives are lexicographic and returned explicitly:

- balanced: intervention count, weighted cost, baseline-egress exposure, adjacency;
- access: intervention count, baseline-egress exposure, weighted cost, adjacency;
- fewest: intervention count only.

Baseline-egress exposure counts address clusters whose one deterministic baseline
directed shortest route to a permitted portal uses a candidate. A cluster already at
a portal has zero-length egress and contributes no exposure. The additive value is a
search proxy—not predicted traffic and not exact detour. The verifier separately
recomputes actual post-solution shortest-egress distance changes.

Before/after regions are directed strongly connected components: each region is a
maximal node set with mutual private-car reachability while respecting one-way
streets. They are a topology view, not traffic volumes or displacement estimates.

## Kallio proof and data boundaries

The frozen graph is derived directly from a committed, bounded Overpass response by
the custom deterministic topology pipeline in `scripts/build_scenario.py`. It
preserves parallel ways and one-way directions, but it is not an OSMnx-produced set
of drive, walking, cycling, and emergency graphs.

Walking and cycling passability are mode-permission semantics: a selected private-car
filter does not remove their access. Emergency passage is an explicit assumption for
a removable, gated, or otherwise permeable treatment. Those modes are not separately
routed or independently proved here. Service access is unsupported and requests that
enable it are rejected with HTTP 422. Protected tram/public-transport geometry is a
conservative OSM-tag abstraction, not a complete operations model.

## Kallio recorded evidence

For the 2026-08-28 dual-setback revision, deterministic preprocessing and strict
geometry/reference reconstruction passed twice in 4.27–4.32 seconds per rebuild.
The four derived-file hashes were unchanged across rebuilds. The targeted Helsinki
invariant ran two identical balanced solves, independently verified the exact-four
result and local access, and passed in 3.93 seconds. The final working-tree checks
recorded:

```text
scenario preprocessing validation: passed
portal/access provenance validation: passed
Python solver/API/invariant suite: 30 tests passed in 7.21 seconds
frontend unit regression: 24 tests passed
TypeScript strict typecheck: passed
frontend ESLint: passed
Python Ruff: passed
production Vite build: passed with large-chunk advisory
Playwright desktop/tablet main story: 8 tests passed in 1.4 minutes
desktop 1440 × 900 browser audit: no material console/layout/a11y errors
tablet 820 × 1180 browser audit: no material console/layout/a11y errors
```

```bash
make data-validate
make lint
make test
make build
make test-e2e
```

Vite's passing production build currently emits one large JavaScript-chunk advisory
(approximately 1.33 MB before gzip and 368 kB after gzip). This is a known startup
performance limitation; code-splitting MapLibre and secondary panels is the most
direct remedy.

## Experiment 03 frozen handoff

The service-coverage scenario is
`service-coverage-otaniemi-tapiola-v1`, snapshot
`coverage-4e7e682613eb7d074b8a3341`, observed at
`2026-09-01T10:10:33.425Z`. Its bbox is
`[24.802, 60.172, 24.8425, 60.1912]`. The checked artifact contains:

```text
33 published HSY 250 m population cells / 8,554 included residents
10 reviewed Helsinki metropolitan Service Map venues
330 connector-inclusive demand/site distances and route geometries
3,207 compact verification nodes / 4,426 directed edges
15,315 walking-network display features
```

The population WFS response is timestamped `2026-09-01T09:18:48.333Z`;
all selected features report source update `2026-08-05Z`. The ten candidate units
are frozen from their exact Service Map endpoints. HSY and Service Map are CC BY 4.0;
the reused OSM walking snapshot `base-c8dcbcfaca2b2c9498420681` is ODbL 1.0.
Exact endpoints, timestamps, checksums, CRS handling, privacy cautions, and reviewed
IDs are in the [evidence note](service-coverage-data-notes.md) and
[source manifest](../data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json).

Each distance is demand-point straight-line snap connector + directed graph shortest
path + site-point straight-line snap connector. Both connectors are disclosed analytical
approximations, and each record retains its component distances and ordered graph chain
for fresh verification.

The default request is at most four sites, 1,600 m, capacity multiplier 1.0, and a
30-second deadline. It is verified optimal with Haukilahden lukio and Tapiolan
nuorisotila selected, all 33 cells assigned, 1,231.82 m worst distance, 757.83 m
population-weighted mean distance, loads 4,248/4,306, and objective vector
`[2, 123182, 648245240, 58]`. The names are a
reproducibility observation, not a recommendation. Budget one is verified UNSAT
because a single declared 5,000-person site cannot serve 8,554 included people; a
1,000 m threshold produces a separate geographic coverage-gap UNSAT. Timeout is
indeterminate.

The 5,000-person capacity is an analytical teaching assumption, not a Service Map
fact or operational capacity. Each HSY cell is an indivisible aggregate represented
by one snapped point; suppressed population is not imputed. Verification proves the
encoded assignment on the frozen walking graph, not facility suitability,
accessibility for every resident, demand, staffing, availability, legal use, service
quality, or equity. The [method note](service-coverage-foundation.md) records the
full model and proof boundary.

The highest-value next extension is robust multi-scenario allocation: choose one
`open[site]` portfolio while allowing assignments to adapt under normal,
one-site-outage, and source-grounded flood/roadworks walking-network conditions.
This connects the second and third experiments and creates a genuinely coupled
portfolio decision without changing the frozen baseline.

## Run locally

```bash
make setup
make data-validate
make service-coverage-validate
make dev
```

Open <http://127.0.0.1:5173>. The API listens on
<http://127.0.0.1:8000>. Ordinary startup and `make data` use the committed archive
without contacting OSM. Only the explicit `make data-refresh` command calls Overpass
and replaces the source snapshot.

Service-coverage replay is also offline by default:

```bash
make service-coverage          # deterministic rebuild from committed evidence
make service-coverage-validate # sources/files, normalized IDs, graph and 330 routes
make service-coverage-test     # frozen-evidence and tamper-regression tests
```

The 2026-09-03 handoff rerun reproduced byte-identical published JSON on two consecutive
offline builds, passed offline validation, and passed the focused frozen-evidence and
pipeline tamper-regression tests. Use the final integrated acceptance run for combined
solver, API, frontend, and browser counts.

Only `make service-coverage-refresh` contacts HSY WFS and the ten exact Service Map
unit endpoints. Treat it as an intentional source update that changes the frozen
snapshot, never as a startup step.

## Release screenshots

The passing Playwright run wrote all eight committed captures below:

| State | Desktop | Tablet |
| --- | --- | --- |
| Before | [desktop](screenshots/four-planters-before-desktop.png) | [tablet](screenshots/four-planters-before-tablet.png) |
| Verified | [desktop](screenshots/four-planters-verified-desktop.png) | [tablet](screenshots/four-planters-verified-tablet.png) |
| Compare | [desktop](screenshots/four-planters-compare-desktop.png) | [tablet](screenshots/four-planters-compare-tablet.png) |
| UNSAT | [desktop](screenshots/four-planters-unsat-desktop.png) | [tablet](screenshots/four-planters-unsat-tablet.png) |

Experiment 03 review captures are:

| State | Desktop | Tablet |
| --- | --- | --- |
| Before | [desktop](screenshots/geospatial-constraint-lab-service-coverage-before-desktop.png) | [tablet](screenshots/geospatial-constraint-lab-service-coverage-before-tablet.png) |
| Verified | [desktop](screenshots/geospatial-constraint-lab-service-coverage-verified-desktop.png) | [tablet](screenshots/geospatial-constraint-lab-service-coverage-verified-tablet.png) |
| UNSAT | [desktop](screenshots/geospatial-constraint-lab-service-coverage-unsat-desktop.png) | [tablet](screenshots/geospatial-constraint-lab-service-coverage-unsat-tablet.png) |

## Git metadata in this environment

The execution environment injects `/home/antti/zroad/.git` as an empty read-only
mount. The repository therefore uses `/home/antti/zroad/.git-local` as its Git
directory and the workspace as its work tree:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline -1
```

If the injected mount disappears, initialize a normal writable `.git` directory or
move the local metadata into place before switching to ordinary Git commands.
