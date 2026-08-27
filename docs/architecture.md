# Architecture and proof boundary

Four Planters is a deliberately small two-process monorepo:

```text
browser (React + MapLibre) ── HTTP/SSE ── FastAPI
                                      ├── Z3 decision model
                                      ├── NetworkX verifier
                                      └── frozen scenario JSON
```

The browser is a research instrument and renderer. It never decides that a result
is valid. FastAPI loads the frozen analytical graph once, and every final result is
checked against a fresh graph copy before it is assigned a verified state.

## Frozen scenario

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

Keeping display geometry separate lets the browser remain responsive without
changing the graph on which the proof is based. The files are committed so ordinary
application startup makes no external geodata request.

Boundary crossings are clustered independently on each side using deterministic
contiguous complete-link grouping with a 60 m maximum diameter. Every retained
private-car crossing record belongs to exactly one cluster. Two spatially distributed,
named local clusters per side are marked primary for browser editing; all analytical
clusters remain permitted local-access exits in solver verification. A selected
portal-pair requirement quantifies over every graph node in each selected cluster.

## Constraint and verification loop

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

The result establishes only this network statement:

> Under the frozen graph, mode, candidate-intervention, and portal assumptions, no
> private-car route remains between the selected portal pairs.

It is not a traffic forecast, a displacement analysis, an engineering feasibility
assessment, an emergency-services approval, or an operational traffic plan.

## Known implementation limits

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
