# Release handoff — 2026-08-26

This file began as the reboot note and now records the reproducible release state.
The frozen source snapshot is unchanged; the portal model, access objective,
independent verifier, timeout controls, and release interface have been corrected
since the initial checkpoint.

## What is implemented

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

The default budget-four, two-pair Helsinki request has a verified optimum using three
filters. A result reaches a verified label only after a fresh NetworkX graph confirms
the requested private-car disconnections and local address-cluster egress.

## Frozen scenario and portal semantics

The study bbox is `[24.9435, 60.1854, 24.9635, 60.1962]`, about 1.33 km² across
Kallio, Alppiharju, and western Vallila. The OpenStreetMap base timestamp is
`2026-08-25T22:24:24Z`; the frozen snapshot ID is
`osm-20260825T222424Z-d8c48f77151b`.

The derived dataset contains:

```text
1,342 analytical nodes
2,408 directed private-car edges
384 eligible modal-filter candidates
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

## Objectives and connectivity semantics

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

## Proof and data boundaries

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

## Recorded evidence

The final 2026-08-27 release checks recorded:

```text
scenario preprocessing validation: passed
portal/access provenance validation: passed
Python solver/API/invariant suite: 29 tests passed in 19.31 seconds
frontend unit regression: 22 tests passed
TypeScript strict typecheck: passed
frontend ESLint: passed
Python Ruff: passed
production Vite build: passed with large-chunk advisory
Playwright desktop/tablet main story: 8 tests passed in 2.2 minutes
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

## Run locally

```bash
make setup
make data-validate
make dev
```

Open <http://127.0.0.1:5173>. The API listens on
<http://127.0.0.1:8000>. Ordinary startup and `make data` use the committed archive
without contacting OSM. Only the explicit `make data-refresh` command calls Overpass
and replaces the source snapshot.

## Release screenshots

The passing Playwright run wrote all eight committed captures below:

| State | Desktop | Tablet |
| --- | --- | --- |
| Before | [desktop](screenshots/four-planters-before-desktop.png) | [tablet](screenshots/four-planters-before-tablet.png) |
| Verified | [desktop](screenshots/four-planters-verified-desktop.png) | [tablet](screenshots/four-planters-verified-tablet.png) |
| Compare | [desktop](screenshots/four-planters-compare-desktop.png) | [tablet](screenshots/four-planters-compare-tablet.png) |
| UNSAT | [desktop](screenshots/four-planters-unsat-desktop.png) | [tablet](screenshots/four-planters-unsat-tablet.png) |

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
