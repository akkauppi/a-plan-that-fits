# Experiment 03 · equitable service coverage

## Research question

> Which candidate public facilities can host a hypothetical temporary neighbourhood-support
> service so that every included population cell is assigned within the stated connector-inclusive
> walking-distance
> and analytical-capacity limits?

This experiment is a deliberately bounded allocation study. It combines a frozen walking
network, resident-count grid cells and reviewed public-facility locations. It is intended to
explain what a constraint solver adds to familiar GIS service-area analysis.

The initial service is hypothetical. A selected facility is a **model site**, not a proposal,
reservation, suitability finding or statement that the service exists there. Its capacity is an
analyst-declared scenario value, not the observed capacity of the building or organisation.

## Why this is a distinct solver experiment

A conventional network solver can calculate the graph distance from each demand cell to each
candidate site. It can answer questions such as “which library is closest?” or “which cells are
within 1,200 metres of this school?” It does not by itself choose a combination of sites while
simultaneously enforcing a site budget, capacities, forced and prohibited locations, maximum
distance, and one complete assignment of every demand cell.

The constraint solver works over the finite relationships compiled by the network analysis. It
chooses sites and assignments together:

```text
open[site]                         Boolean: is this candidate selected?
assign[demand_cell, site]          Boolean: is this cell allocated to this site?
```

The frozen matrix records every reviewed cell–site pair for this small scenario. The model creates
one assignment Boolean per recorded pair, then the tracked walking-distance rule forces every
over-limit pair to `false`; missing, ineligible or unreachable relations cannot be selected.
Here, each distance explicitly equals the demand representative's straight-line snap connector,
plus the shortest walking-graph path, plus the site's straight-line snap connector. The connector
model is an analytical approximation, not a mapped entrance or accessibility claim.

## Hard constraints

For demand cells `d` and candidate sites `s`, the first vertical slice encodes:

```text
sum(open[s]) <= site_budget

for every demand cell d:
    sum(assign[d, s] for eligible s) = 1

for every assignment pair (d, s):
    assign[d, s] -> open[s]

for every site s:
    sum(population[d] * assign[d, s]) <= assumed_capacity[s] * capacity_multiplier

for every forced site s:
    open[s] = true

for every prohibited site s:
    open[s] = false
```

The equality in the second rule matters: each included cell is represented once, rather than
being double-counted by overlapping service areas. Population is allocated as a whole grid-cell
weight in this demonstrator; the model does not split one cell between multiple sites.

The maximum walking distance and capacity multiplier are scenario controls. Changing either
changes the active feasible assignment matrix or its capacity bounds and therefore changes the
question being proved.

## Explicit objective order

Assignments satisfying every hard constraint are ranked lexicographically:

1. minimise the number of selected sites;
2. minimise the worst assigned connector-inclusive walking distance;
3. minimise population-weighted total assigned distance;
4. minimise the spread between the most and least loaded selected sites.

Lexicographic order means a later objective never compensates for a worse earlier one. The
application reports the complete objective vector instead of presenting a blended “best city”
score. The load-spread term is a simple analytical balance measure, not a staffing, queueing or
service-quality model.

## Calculation and verification boundary

This experiment uses the two engines in a different sequence from the modal-filter and
resilient-access studies:

1. NetworkX reconstructs the frozen walking graph and compiles deterministic shortest-path
   components between each snapped demand/site node. It adds both projected straight-line snap
   connectors to the total and route geometry, retaining the component distances and exact
   ordered node/edge chain.
2. Z3 solves the resulting Boolean site-selection and assignment model.
3. A fresh verifier rebuilds the selected assignment outside Z3, audits each connector, exact
   graph chain, NetworkX shortest graph component, component sum and rendered route geometry,
   recomputes every site load, and checks the budget, forced/prohibited sites and analytical
   capacities.

There is no counterexample-guided path loop in this first slice because the bounded distance
matrix is complete and small enough to encode directly. Streaming progress remains
real: the browser receives matrix-compilation, feasible-assignment, objective and independent-
verification events. The distinction is pedagogically useful: counterexample refinement is a
technique for models where enumerating path conditions is impractical, not a ritual required by
Z3.

## Result states and proof language

The application may say:

> Under the frozen demand, candidate-site, walking-network, snap-connector, distance, capacity and budget
> assumptions, every included population cell has exactly one verified assignment to a selected
> site.

`verified_optimal` means the hard constraints hold, the returned lexicographic objective vector
is optimal for the encoded model, and the independent graph-and-arithmetic verification passed.
`verified_unsat` means no assignment satisfies the complete encoded hard constraints. Timeout,
cancellation, data errors and verification errors are indeterminate and never appear as UNSAT.

When possible, a tracked UNSAT core identifies the conflicting user-facing assumptions. A
geographic diagnostic can additionally identify cells with no candidate inside the distance
limit or a capacity shortfall. Suggested relaxations are shown as choices; the application does
not change assumptions automatically.

## What the experiment does not establish

The model does not prove:

- that population counts equal actual service demand;
- that every resident uses the snapped cell representative or the modelled walking route;
- that an included facility is available, accessible, suitable or legally usable;
- that the declared capacity reflects rooms, staff, opening hours, queues or service quality;
- that equal distance or load is the correct policy definition of equity;
- that the walking graph or source registers are complete and current;
- that a selected combination should be implemented.

Grid suppression and aggregation also matter. A cell represents a resident-count aggregate, not
individual people or addresses. The map must not imply household-level precision.
The straight snap connectors can cross a barrier or miss the usable facility entrance; they are
inspectable gap-filling geometry between source points and the abstract graph, not observed paths.

## Frozen evidence and reproducibility

The first slice uses real official metropolitan population-grid and Service Map evidence plus the
already frozen OpenStreetMap walking network around Otaniemi–Tapiola. Runtime solving is offline:
the browser and API read a checked derived scenario artifact rather than contacting a live data
service.

The checked scenario is `service-coverage-otaniemi-tapiola-v1`, content snapshot
`coverage-4e7e682613eb7d074b8a3341`, observed at `2026-09-01T10:10:33.425Z` over bbox
`[24.802, 60.172, 24.8425, 60.1912]`. It contains 33 published HSY 250 m cells
representing 8,554 included residents, ten reviewed Service Map venues, all 330
connector-inclusive cell/site relations, and a compact verification network of 3,207 nodes and
4,426 directed edges. The walking source is frozen OSM network snapshot
`base-c8dcbcfaca2b2c9498420681`.

The preprocessing command records the query bounds and parameters, retrieval timestamps, source
licences, response hashes, analysis/display coordinate systems, snapping and connector policy,
reviewed candidate categories, default analytical capacities and all derived routes. The content
fingerprint binds the complete top-level, solver, and browser payloads; offline validation also
requires their split files to match and checks every metadata-recorded byte size and SHA-256.
Refresh is an explicit networked operation; the ordinary rebuild validates and reproduces the
checked snapshot.

Source roles are kept separate:

- Helsinki Region Environmental Services / Helsinki Region Infoshare population grid supplies
  aggregate demand evidence;
- the Helsinki metropolitan Service Map supplies public-facility identities, names and locations;
- OpenStreetMap supplies the directed walking-network abstraction used for the graph component
  of distance.

The checked artifact and application attribution contain the exact editions, timestamps, licences
and source links. Source location does not imply candidate suitability, and candidate capacity is
stored separately as an analytical assumption.

The exact requests, response and feature timestamps, SHA-256 values, CRS handling, cell
suppression caution and site review are in the
[evidence note](service-coverage-data-notes.md). Machine-readable provenance is in the
[source manifest](../data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json)
and [derived metadata](../data/derived/service-coverage-otaniemi-tapiola-v1/metadata.json).
HSY and Service Map material is attributed under CC BY 4.0; OpenStreetMap is ODbL 1.0.

The default request uses an at-most-four site budget, 1,600 m connector-inclusive distance threshold,
capacity multiplier 1.0 and 30-second deadline. It is verified optimal with two selected sites;
all 33 assignments remain below the threshold, with 1,231.82 m worst distance and 757.83 m
population-weighted mean distance. The objective vector is `[2, 123182, 648245240, 58]`.
A budget of one is verified UNSAT because one declared
5,000-person site cannot accept 8,554 included people. At 1,000 m, a distinct sensitivity is
UNSAT because at least one cell has no admissible reviewed site. These are results under the
frozen model, not recommendations about the named facilities.

## Vertical-slice acceptance criteria

The first integrated slice is complete when it provides:

- a frozen, validated Otaniemi–Tapiola scenario with real population, facility and walking data;
- demand cells, candidate sites, walking routes and capacity state on the map;
- budget, distance, capacity-multiplier, force and prohibit controls;
- real streamed solving stages and distinct verified/UNSAT/indeterminate outcomes;
- independent verification of every assignment, route, load and selected site;
- at least one feasible default and a reproducible infeasible sensitivity;
- an inspectable human explanation of the logical variables and hard constraints;
- focused solver, API and browser tests plus desktop and tablet visual inspection.

## Deliberate next extensions

After the vertical slice, the most informative extension is not a larger site catalogue. It is a
**robust multi-scenario allocation**: choose one site portfolio once, then require a valid
assignment under several independently sourced conditions, such as normal operation, one selected
site being unavailable, and a flood/roadworks walking-network disruption. In model terms,
`open[site]` is shared across scenarios while `assign[cell, site, scenario]` may adapt. This would
connect Experiments 02 and 03 and create a genuinely coupled choice for which Z3 is more useful
than a sequence of independent nearest-facility maps.

Policy-sensitive population groups or explicit minimum provision by area are valuable after a
defensible normative grouping and source basis have been agreed. Split assignment, temporal
opening schedules and uncertain demand should remain explicit model extensions rather than being
smuggled into the current whole-cell, deterministic interpretation.

The solver core can exclude an earlier optimal structural answer, but equal-objective
enumeration is not yet exposed by the Experiment 03 browser or API. Adding that small,
inspectable comparison workflow remains a deliberate interface follow-up; it should not be
described as part of the current vertical slice.
