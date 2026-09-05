# Architecture and proof boundary

> **Scope note:** this document describes three equal laboratory experiments:
> Kallio modal-filter placement, Otaniemi flood-resilient access, and
> Otaniemi–Tapiola equitable service coverage. Their research history and remaining generalization
> boundary are recorded in the
> [project status and roadmap](project-status-and-roadmap.md).

Geospatial Constraint Lab is a deliberately small two-process monorepo:

```text
browser (React + MapLibre) ── HTTP/SSE ── FastAPI
                                      ├── Kallio filter model
                                      ├── Otaniemi access model
                                      ├── Otaniemi–Tapiola allocation model
                                      ├── Z3 decisions + NetworkX checks
                                      └── frozen scenario evidence
```

The browser is a research instrument and renderer. It never decides that a result
is valid. FastAPI loads the frozen analytical graphs and distance evidence once.
Every feasible final result is reconstructed outside its optimizing model before it
receives a verified state. Verified infeasibility follows a separate proof path: Z3
establishes inconsistency over the active hard constraints and, for the two
connectivity experiments, accumulated sound graph-derived necessary clauses; a
connectivity graph checker can also identify a required cut with no eligible
decision.

## Experiment: Otaniemi–Tapiola compiled service allocation

Experiment 03 intentionally uses a different Z3/NetworkX division from both
counterexample-guided connectivity experiments. Its checked frozen snapshot is
`coverage-4e7e682613eb7d074b8a3341`:

```text
33 HSY 250 m population cells / 8,554 included residents
  + 10 reviewed Service Map facilities
  + OSM walking snapshot base-c8dcbcfaca2b2c9498420681
  ── NetworkX preprocessing ──> 330 directed connector + shortest-path + connector routes
                              + compact 3,207-node / 4,426-edge verification graph
  ── Z3 runtime ─────────────> selected sites + one assignment per cell
```

The derived artifact has separate `browser` and `solver` documents. The browser
document contains simplified linework, cell polygons, facility points and
attribution. The solver document contains stable demand/site IDs, graph-node snaps,
the complete distance matrix, per-route connector and network components, ordered
node/edge chains, route features, capacities, and the compact directed walking graph.
Ordinary startup reads this artifact offline.

Every matrix total is `demand_connector_m + network_distance_m +
site_connector_m`. The graph component is a directed NetworkX shortest path. The
connectors are EPSG:3067 straight-line segments between each source coordinate and
its snapped graph node; they are a visible analytical approximation, not mapped
entrances, crossings, or accessibility evidence.

Each reviewed site has a Boolean `open[site]`. Every cell/site relation has a
Boolean `assign[cell,site]`; relations beyond the active connector-inclusive distance threshold
are constrained false. The hard model requires exactly one assignment per included
cell, `assign[cell,site] -> open[site]`, an upper bound on active sites, site
eligibility, force/ban choices, and:

```text
sum(population[cell] * assign[cell, site])
    <= floor(declared_capacity[site] * capacity_multiplier)
```

The current 5,000-person values are explicitly analyst-declared sensitivity inputs.
Service Map supplies identities and locations, not capacity. The model does not
represent staff, rooms, queues, opening hours, accessibility, actual demand, or
facility permission.

### Direct solve and lexicographic proof

There is no path-refinement loop in this experiment. NetworkX can compile all 330
relevant network relationships in advance, so Z3 receives the complete bounded
allocation problem directly:

1. An ordinary `Solver` checks feasibility under named assumption literals. If it
   is UNSAT, those literals produce a user-facing core without involving an
   optimization result.
2. Only after feasibility is established are the tracked assumptions asserted as
   ordinary facts. Sound redundant consequences—aggregate capacity bounds and
   per-cell candidate coverage—tighten propagation but do not change the feasible
   assignments.
3. Finite-domain Z3 checks prove the minimum site count and then the minimum worst
   connector-inclusive walking distance. Once the latter is fixed, assignments beyond that proved
   bound are explicitly pruned.
4. A lexicographic `Optimize` check minimizes population-weighted total distance
   and then selected-site load spread under the two earlier equalities.
5. The resulting model is serialized in stable ID order and passed to a separate
   verifier. Repeated fixed-scenario tests check deterministic reproduction; no
   extra non-scientific tie objective is added to the four published priorities.

This staged implementation is semantically the same four-objective lexicographic
model: each objective is fixed before a later priority may improve. The propagation
bounds are consequences of the active exact-assignment, distance and capacity rules,
and are introduced only after the tracked feasibility check so they cannot obscure
an UNSAT core.

The independent verifier does not trust the optimizer's result object. It checks
every selected ID and assignment against the frozen matrix, recomputes all loads,
capacities, force/ban choices, budget use and objective values, then audits each
stored snap distance, ordered node/edge chain, edge-length sum, NetworkX shortest
graph component, three-component total, and connector-inclusive GeoJSON geometry.
A matrix/graph disagreement, missing route, broken chain, connector mismatch, or
arithmetic mismatch is a data or verification error. Only complete agreement becomes
`verified_optimal`.

The evidence compiler also treats packaging integrity as part of reproducibility.
It derives the snapshot ID from normalized content after replacing the top-level,
solver, and browser snapshot IDs with `pending`. Offline validation requires all
three IDs to equal that recomputed fingerprint, requires split `solver.json` and
`browser.json` to match their copies in `scenario.json`, and verifies every
metadata-recorded file size and SHA-256.

District IDs are retained in assignment summaries so geographic outcomes can be
inspected. They are not a fairness constraint in version 1. Likewise, minimizing
worst distance and load spread are transparent analytical priorities, not a claim
that they constitute the correct policy definition of equity.

### Why this is not CEGIS

Kallio cannot cheaply encode every possible forbidden route, and Otaniemi learns
directed access frontiers as disruption choices change. Those experiments therefore
alternate a Z3 proposal with a NetworkX counterexample. Service allocation instead
starts from a finite complete cell/site distance relation, so direct one-hot
assignment constraints are smaller and clearer than inventing counterexamples.
Using direct compilation here is an architectural choice, not a weaker substitute:
the final route evidence is still checked independently.

The distinction is central to the laboratory's teaching purpose:

```text
large or changing family of graph paths  -> propose, check, learn a clause (CEGIS)
small complete GIS relation              -> compile once, solve directly, verify afresh
```

## Experiment: Otaniemi resilience runtime

The Otaniemi workspace is assembled offline from exact frozen artifacts:

```text
OSM base-c8dcbcfaca2b2c9498420681
  + Syke flood-bf45a84ac9ce456045f8932b
  + Espoo espoo-0c59d1ca21a9e918b058 address/building evidence
  + reviewed gateway node IDs
  + explicit user availability settings
  ──> otaniemi-access-v1
```

The runtime verifies every declared artifact hash before publishing the composite
scenario ID. Its `snapshot_components` bind the analytical JSON, flood display
geometry, Espoo manifest, compressed archives, raw GML, and address aggregation/snap
recipe. This prevents a pointer or municipal archive change from masquerading as
the same browser scenario.

The 2.743279 km² core has a separate 750 m graph/source context. The base snapshot
contains 18,710 nodes, 42,077 directed edges, and 21,526 physical segments; 8,048
physical segments participate in the private-car graph. The flood snapshot records
892/1,608 source-exposed segments at the 1/100 and 1/1000 tiers. Only 241/528 are
effective private-car exposure links. Keeping both count families prevents source
geometry from being confused with a mode-specific closure set.

Espoo's 297 address points inside the core are aggregated into 15 deterministic
500 m metric cells, then snapped to graph nodes. The runtime checks those
representatives rather than claiming address-by-address coverage. Four manually
reviewed outbound context nodes provide named graph exits at Kuusisaarentie,
Tapiolantie, Kalevalantie, and Kehä I. They are OR destinations—an origin reaches at
least one selected exit—and are not certified safe locations.

Source exposure becomes unavailable only through an explicit stress assumption:

```text
unavailable(e) := declared_works(e)
               OR (stress_assumption_enabled AND exposed(e, tier))
```

MML elevation is separately attributed terrain/QC evidence and is not an operand in
this expression. User-clicked roadworks are exact fixed physical-segment IDs, never
solver-selected recovery actions.

### Otaniemi CEGIS loop

Connected source-exposed OSM fragments are grouped into map-visible continuity
zones by normalized street name, or by OSM way/highway identity for unnamed links.
Each group has a Boolean `passable[group_id]`. Z3 minimizes, lexicographically, the
number of selected groups and their rounded total mapped length, with stable IDs as
the deterministic tie-break. The returned result expands every group to exact
physical segment IDs so the budget, aggregation, map, and verifier can be audited.
The budget counts one selected Boolean group even when it expands to several OSM
fragments. A group can restore only links removed by the flood-exposure assumption;
fixed roadworks are excluded before grouping and remain unavailable. Selection means
the group belongs to the returned optimum in this encoded model, though it may be
replaceable in an equally good alternative. It does not mean that its fragments are
safe, legal, operable, protectable, or funded.

Reachability itself is a domain-graph requirement, not an eagerly enumerated Z3 path
formula:

1. Z3 proposes a passable-group assignment satisfying the budget and learned cuts.
2. NetworkX constructs the directed effective graph and checks each representative
   against its permitted exit set.
3. A stranded representative produces two different artifacts: a least-disrupted
   diagnostic route for visual explanation and the eligible group IDs on the
   directed reachable frontier.
4. Only the frontier becomes a sound clause such as
   `passable[a] OR passable[b]`; the diagnostic route is not a constraint.
5. Z3 solves the strengthened model. Once all requirements pass, a fresh NetworkX
   graph reconstructs availability and repeats every directed reachability check.

The resulting access-frontier clause asks the model to restore at least one
`passable[...]` group at a stranded origin's reachable boundary. The Kallio loop
learns the converse kind of graph constraint: a path-cut clause asks the model to
block at least one eligible `blocked[...]` candidate on a surviving forbidden route.
The former preserves a required connection; the latter severs a prohibited one.

The default Otaranta→Kuusisaarentie, 1/1000, budget-four teaching case learns three
singleton frontier clauses and returns three zones / 21 physical fragments / 388 m
aggregation cost / +1,093 m mapped detour. Singleton cuts make the protocol legible
but exercise little combinatorial search, so this case is not a solver-performance
claim. The all-15-representative sensitivity is verified UNSAT at budget four and
requires five groups.

The browser exposes the same sequence as a map and a constraint workbench:
map evidence → Boolean variables → budget/learned clauses → NetworkX domain check
→ fresh checked result. This is designed to explain why a constraint solver is
useful without pretending that GIS layers arrive as Boolean facts automatically.

## Experiment: Kallio modal-filter frozen scenario

`scripts/build_scenario.py` is the provenance-preserving boundary between live OSM
and the application. The refresh path downloads a bounded Overpass response directly,
archives it with its timestamp and checksum, and the offline rebuild deterministically
derives the private-car topology from that archive. It collapses OSM shape points
between intersections, way endpoints, and boundary crossings while preserving
parallel ways and one-way directions. This committed scenario is **not** produced by
OSMnx network-mode downloads and does not contain separate OSMnx walking, cycling, or
emergency graphs. Its two products serve different purposes:

- `scenario.json` contains simplified WGS84 GeoJSON, display metadata, and the eight
  primary portals exposed by the compact selector.
- `solver.json` contains stable nodes, directed edges, candidate groups, all 38
  analytical portals, all 68 source crossing records, address clusters, and analysis
  metadata.

Candidate generation applies two projected midpoint setbacks. The first is 60 m from
the analysis boundary. The second is 120 m from the nearest actual crossing point
belonging to any of the static eight primary/selectable portals. Both use Euclidean
EPSG:3067 distance from the physical-segment midpoint used as the candidate display
point. The second rule does not use portal display markers, does not change with the
currently requested pairs, and does not include the other 30 analytical portals.
Primary portals are selected from pre-setback base eligibility before either portal
approach exclusion is applied; portal adjacency is refreshed from final candidates.

Otherwise eligible local segments inside either zone remain ordinary open graph
edges but receive no intervention variable. They are **ineligible**, not protected
transit infrastructure. The browser exports the boundary band and the unioned,
boundary-clipped primary-portal approach zones as inspectable GeoJSON. Edge, street,
and candidate records retain the rounded distances, metric identifier, nearest
primary portal ID, and nearest source-crossing ID. These are reproducible analytical
bias controls, not physical or legal siting rules.

Keeping display geometry separate lets the browser remain responsive without
changing the graph on which the proof is based. The files are committed so ordinary
application startup makes no external geodata request.

Boundary crossings are clustered independently on each side using deterministic
contiguous complete-link grouping with a 60 m maximum diameter. Every retained
private-car crossing record belongs to exactly one cluster. Two spatially distributed,
named local clusters per side are marked primary for browser editing; all analytical
clusters remain permitted local-access exits in solver verification. A selected
portal-pair requirement quantifies over every graph node in each selected cluster.
The two defaults are explicit scenario-specific pairs after both setback controls:
east-south Vilhonvuorenkuja ↔ south-west Agricolankuja
(southern cross-neighbourhood permeability) and north-west Pälkäneentie ↔
west-south Alppikatu (western cross-neighbourhood permeability). The labels avoid
claiming these adjacent-side pairs are north–south or east–west cuts. Preprocessing
requires a candidate-bearing deterministic shortest route in each direction; the
frozen-scenario solver invariant separately establishes exact-four feasibility and
independent final verification. The intervention budget is an upper bound; the
default maximum is four.

## Kallio constraint and verification loop

Each eligible physical street location has one Boolean `blocked[candidate_id]`.
Candidates group reciprocal directed OSM edges so one modal filter affects both
private-car directions. Walking and cycling are not separate verification graphs in
the frozen scenario; the abstraction defines the filter as passable for those modes.
Emergency passage is an explicit removable/unlockable-filter assumption, not a
computed emergency-network proof. Service access is not implemented, and a request
to enable it is rejected rather than silently treated as verified.

The initial Z3 model contains the budget, forced and locked choices, and explicit
objective terms. It does not enumerate every possible route. Instead:

1. Z3 proposes a candidate set.
2. NetworkX removes those candidates from a private-car graph copy.
3. A surviving requested portal connection becomes a counterexample path.
4. The solver adds a clause requiring at least one eligible candidate on that path.
5. A candidate that strands an address cluster is rejected with a safe no-good.
6. The process repeats until every selected portal pair is disconnected and every
   address cluster reaches a permitted portal.
7. The final set is independently verified once more on a fresh graph.

An iteration with a surviving path but no eligible edge is a graph-verifier finding
(`unblockable protected corridor`), not a generic Z3 core. Timeout and cancellation
also remain separate from UNSAT. The browser exposes 5, 10, 30, 60, and 120 second
deadlines (30 seconds by default); the chosen value applies to the actual run and is
serialized in scenario URLs.

## Objectives and alternatives

Objectives are lexicographic and inspectable. In balanced mode they are intervention
count, weighted physical cost, baseline-egress exposure, then spatial concentration.
The exposure term is a deterministic proxy: a candidate receives one unit for each
address cluster whose one baseline directed shortest route to any permitted portal
uses that segment; distance ties are resolved by stable edge IDs. Because the term is
additive, one cluster may contribute to several candidates. It is neither predicted
traffic nor exact post-filter detour. After a complete intervention set is applied,
the graph verifier separately recomputes and reports actual shortest-egress distance
changes. After the first optimum is verified, the service fixes its objective vector
and adds a structural blocking clause before asking for another equal-quality
intervention set.

Access mode swaps the two secondary terms: intervention count, baseline-egress
exposure, weighted cost, then spatial concentration. Fewest mode minimizes only the
number of interventions. These priorities are returned as explicit objective values;
there is no composite “optimal city” score.

## Before/after connectivity view

Verified results include separate baseline and filtered GeoJSON collections for the
private-car graph's **directed strongly connected components**. A component is a
maximal node set in which every node can reach every other node while respecting
one-way streets. Open one-way links between components remain visible but are marked
as inter-component links rather than coloured as members of a mutual-reachability
region. This is a topological comparison, not a traffic-volume or redistribution
estimate.

## Scientific scope

The Otaniemi result establishes only this network statement:

> Under the frozen directed private-car graph, selected representative origins,
> reviewed outbound graph exits, declared roadworks, and the explicitly enabled
> flood-exposure-as-unavailable rule, the reported access relations were recomputed
> on a fresh directed graph.

It does not establish physical flood closure, safe destinations, individual-address
access, capacity, public/legal access over a service road, or feasibility of a
selected continuity treatment.

The Kallio result establishes only this network statement:

> Under the frozen graph, mode, candidate-intervention, and portal assumptions, no
> private-car route remains between the selected portal pairs.

It is not a traffic forecast, a displacement analysis, an engineering feasibility
assessment, an emergency-services approval, or an operational traffic plan.

The service-coverage result establishes only this allocation statement:

> Under the frozen 33-cell demand, reviewed candidate-site, directed walking-network,
> straight snap-connector, distance-threshold, analyst-declared capacity, and user policy assumptions, every
> included cell has exactly one freshly verified assignment to a selected site.

It is not evidence of individual access, actual service demand, facility availability
or suitability, operating capacity, staffing, policy equity, funding, or an
implementation recommendation.

## Known implementation limits

- Service coverage assigns each aggregate 250 m population cell as one indivisible
  unit from its snapped representative node. It does not model within-cell variation,
  suppressed individuals, split demand, travel time, opening schedules, or queues.
- Its straight snap connectors can cross unmapped barriers or miss the actual usable
  facility entrance; the route is an analytical network approximation, not a
  pedestrian-accessibility audit.
- Its 5,000-person site capacities are declared scenario values. District bands are
  descriptive reporting groups, not official boundaries or hard equity constraints.
  Equal-objective service alternatives are supported by the core but not yet exposed
  through the Experiment 03 API or browser.
- Otaniemi models a binary private-car connectivity stress test. It does not model
  water depth at carriageway elevation, hydraulic behaviour, capacity, travel time,
  independently routed other modes, or emergency response.
- The Otaniemi decision groups are analytical aggregations of contiguous OSM
  fragments. Their rounded mapped length is a transparent secondary cost, not a
  construction cost. Some selected default links are tagged `highway=service`, so
  OSM access completeness and field/legal review materially affect interpretation.
- The current Otaniemi teaching case learns singleton frontier clauses. It explains
  Z3/NetworkX refinement but does not demonstrate an advantage over a specialized
  shortest-path or cut algorithm.
- Custom location builds stop at a frozen base network. They do not yet acquire and
  reconcile all hazard/municipal evidence, review origins/exits, or activate the
  built graph in the resilience runtime.
- User-clicked roadworks are fixed link IDs. Imported-works conflation, time buckets,
  and flexible scheduling are not implemented.
- The proof graph is the custom deterministic private-car topology derived from the
  frozen Overpass response, not a family of independently constructed OSMnx mode
  graphs.
- Walking and cycling continuity are mode-permission semantics: selected car filters
  do not remove their access. Emergency passage is an explicit treatment assumption.
  None of the three is an independently routed proof in this release.
- Service access has no graph or verifier; requests enabling it fail validation.
- Protected transit geometry is based on confidently mapped OSM tags and nearby tram
  infrastructure, not a complete public-transport operations model.
- The browser production build passes, but Vite reports one large bundle-chunk
  advisory. Code-splitting MapLibre and secondary panels is a performance extension.
