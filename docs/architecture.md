# Architecture and proof boundary

> **Lifecycle note:** this document describes both the completed Four Planters
> baseline and the first implemented Otaniemi resilience slice. The continuing
> direction and remaining generalization boundary are recorded in the
> [project status and roadmap](project-status-and-roadmap.md).

Four Planters is a deliberately small two-process monorepo:

```text
browser (React + MapLibre) ── HTTP/SSE ── FastAPI
                                      ├── Kallio filter model
                                      ├── Otaniemi access model
                                      ├── Z3 decisions + NetworkX checks
                                      └── frozen scenario evidence
```

The browser is a research instrument and renderer. It never decides that a result
is valid. FastAPI loads the frozen analytical graphs once, and every final result is
checked against a fresh graph copy before it is assigned a verified state.

## Otaniemi resilience runtime

The primary workspace is assembled offline from exact frozen artifacts:

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

## Kallio frozen scenario

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

## Known implementation limits

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
