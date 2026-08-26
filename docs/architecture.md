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
and the application. Its two products serve different purposes:

- `scenario.json` contains simplified WGS84 GeoJSON and display metadata.
- `solver.json` contains stable nodes, directed edges, candidate groups, portals,
  address clusters, and analysis metadata.

Keeping display geometry separate lets the browser remain responsive without
changing the graph on which the proof is based. The files are committed so ordinary
application startup makes no external geodata request.

## Constraint and verification loop

Each eligible physical street location has one Boolean `blocked[candidate_id]`.
Candidates group reciprocal directed OSM edges so one modal filter affects both
private-car directions without changing walking, cycling, or emergency graphs.

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
also remain separate from UNSAT.

## Objectives and alternatives

Objectives are lexicographic and inspectable: intervention count, weighted physical
cost, access impact, and spatial concentration. After the first optimum is verified,
the service fixes its objective vector and adds a structural blocking clause before
asking for another equal-quality intervention set.

## Scientific scope

The result establishes only this network statement:

> Under the frozen graph, mode, candidate-intervention, and portal assumptions, no
> private-car route remains between the selected portal pairs.

It is not a traffic forecast, a displacement analysis, an engineering feasibility
assessment, an emergency-services approval, or an operational traffic plan.
