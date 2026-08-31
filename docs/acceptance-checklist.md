# Four Planters acceptance checklist

This checklist is intentionally based on observable behaviour and independent graph
verification rather than a single expected intervention set.

Four Planters entered completed-baseline status on 2026-08-30. This checklist remains
its regression contract while generic infrastructure is extracted for the
[resilient-access successor](project-status-and-roadmap.md).

## Data and provenance

- Frozen scenario identifies its OpenStreetMap snapshot, polygon, query, CRS, and ODbL licence.
- Street, building, protected-corridor, portal, candidate, and address-cluster references validate.
- All 68 retained boundary crossings belong exactly once to one of 38 analytical
  portal clusters; no cluster exceeds the configured 60 m diameter.
- The browser exposes exactly eight primary portals, two per boundary side, while
  local-access verification can use every analytical portal.
- Candidate display points are at least 60 m from the projected analysis boundary;
  the 80 otherwise eligible physical segments in the terminal zone remain ineligible
  open streets and are not mislabelled as protected transport infrastructure.
- Candidate display points are also at least 120 m from the nearest mapped crossing
  point of any of the eight primary portals. That portal-approach rule excludes 79
  base-eligible segments, overlaps the boundary rule for 47, adds 32 exclusions, and
  leaves 272 candidates. Its source portal/crossing IDs and unioned GeoJSON zones
  reconstruct successfully from EPSG:3067 provenance.
- Both setback classes are analytical bias controls, not transport protection or
  physical/legal siting rules.
- The audited defaults are Vilhonvuorenkuja ↔ Agricolankuja and Pälkäneentie ↔
  Alppikatu. Preprocessing checks that the deterministic shortest route in each
  direction contains a candidate; the frozen-scenario solver invariant separately
  establishes exact-four feasibility and independent final verification.
- Browser startup does not fetch live OSM data or require a tile service.
- The map keeps visible OpenStreetMap attribution.
- Provenance states that the frozen graph is derived directly from the committed
  bounded Overpass response with custom deterministic topology; it does not describe
  the scenario as an OSMnx-produced family of mode graphs.

## Solver proof obligations

- Selected filters are eligible, unique, and within budget.
- Budget is an upper bound rather than a requirement to select exactly that many filters.
- Forced filters are selected; locked-open and protected edges are not selected.
- Every requested portal pair is disconnected in a fresh private-car graph.
- Every included address cluster reaches at least one permitted portal.
- Walking and cycling remain unchanged by the private-car-only filter abstraction;
  the interface does not present that permission semantic as a separate graph proof.
- Emergency permeability is asserted only when the removable/gated-filter assumption
  is enabled and is not described as a routed or legal-compliance proof.
- Unsupported service access is rejected at request validation rather than silently
  included in a verified result.
- A candidate result is never labelled final before independent NetworkX verification.
- Timeout, cancellation, UNSAT, unblockable routes, and verification errors are distinct outcomes.
- Repeated solves of the same state produce the same first solution and event order.
- Objective values expose the selected lexicographic order, including the baseline
  egress-exposure proxy and separately recomputed post-solution detour metrics.

## Interface story

- Initial viewport presents the Otaniemi resilient-access question, source state,
  research sequence, and a clear route to the preserved Kallio baseline.
- The frozen Otaniemi preset reports the MML 2 m raster as archived/offline and
  explicitly labels elevation and flood exposure as evidence rather than closure,
  passability, or safety.
- After switching to Kallio, the baseline explains the permeability question, shows
  four as the budget, and exposes one clear solve action.
- Boundary, hierarchy, buildings, protected corridors, portals, candidates, and the illustrative existing route are legible.
- Counterexample routes and model refinements appear as actual streamed solver events.
- Solver timeout is selectable at 5, 10, 30, 60, or 120 seconds; 30 seconds is the
  browser default, the choice survives a shared URL, and timeout is never styled or
  worded as UNSAT.
- Street inspection supports force-filter, lock-open, and return-to-neutral states.
- Portal pairs are selectable without relying on colour alone.
- Verified results expose local-access and portal-connectivity summaries.
- Before/after overlays use separately returned baseline and filtered directed strong
  components, with mutual private-car reachability explained in the interface.
- Another equal-objective solution can be requested and compared.
- Method and limitations use the scoped scientific claim and avoid traffic-forecast or legal-feasibility claims.
- Keyboard focus, reduced motion, desktop, and tablet layouts remain usable.

## Otaniemi resilience obligations

- Runtime references resolve to exact base snapshot
  `base-c8dcbcfaca2b2c9498420681` and flood snapshot
  `flood-bf45a84ac9ce456045f8932b`; ordinary startup and solving remain offline.
- The interface distinguishes 892/1,608 source-exposed segments from the 241/528
  effective private-car exposure segments at 1/100 and 1/1000.
- Blue source geometry is the actual clipped line/polygon intersection. Full dashed
  links mean unavailable under the enabled analytical rule; exposure is never
  silently labelled a Syke road-closure finding.
- MML elevation remains separately attributed terrain/QC evidence and is never used
  to close or reopen a graph link.
- All 15 representatives derive deterministically from 297 Espoo address points in
  500 m `EPSG:3067` cells, lie inside the core, resolve to private-car nodes, and
  have finite snap distances no greater than 60 m. The result does not claim that
  297 individual addresses were verified.
- East Kuusisaarentie, south Tapiolantie, west Kalevalantie, and north Kehä I resolve
  to the exact reviewed outbound nodes. They are described as graph exits, not
  certified safe destinations; each origin must reach at least one selected exit.
- The explicit unavailable-link rule is exactly declared roadworks OR (enabled
  stress assumption AND exposure at the selected tier). Disabling the flood rule
  yields no flood decisions or selected flood links.
- Continuity groups are disjoint, map-visible aggregations of effective unavailable
  private-car fragments. Declared works never become group members. Budgets count
  groups, objectives report rounded mapped-length cost, and results also report the
  exact expanded fragment count.
- Candidate, stranded-origin diagnostic route, directed reachable frontier, learned
  clause, and final graph check are streamed and can be revisited on the map. The
  interface distinguishes the diagnostic route from the frontier clause.
- Z3 variables use `passable[decision_group_id]`. NetworkX checks the reachability
  requirement and compiles each violation into a sound at-least-one frontier clause;
  a fresh directed graph verifies every final access relation.
- The default Otaranta→east, 1/1000 teaching preset verifies three zones, 21 OSM
  fragments, aggregation-length cost 388 m, and +1,093 m mapped detour. The UI warns
  when the dependency uses mapped service/driveway links.
- The all-cell/east sensitivity request is verified UNSAT at budget four and needs
  five groups. Timeout, cancellation, and data error remain non-UNSAT states.
- Documentation and the constraint workbench disclose that the teaching run learns
  three singleton frontiers. It demonstrates the CEGIS protocol, not a comparative
  Z3 performance advantage.
- A custom-location builder job publishes only a base-network artifact. It does not
  silently acquire missing evidence, select exits, or replace the frozen graph in
  the access runtime.
- Desktop and tablet screenshots cover before, refinement, verified, constraint
  workbench, and route-solver-versus-Z3 guide states with visible source attribution.

## Release checks and evidence

Current combined regression evidence, rerun on 2026-08-31 after the Otaniemi
resilience solver, visual workbench, and frozen MML integration:

- all 190 Python tests passed, including the credential/redirect, canonical archive,
  offline replay, integrity, scenario-builder, generic resilience solver,
  Otaniemi API/graph invariants, and Helsinki invariant cases;
- Kallio preprocessing, Otaniemi base-network, flood-exposure, and MML elevation
  validators passed, and `make otaniemi-offline` reproduced the checked snapshot IDs;
- Python Ruff, frontend lint and strict typecheck passed, all 35 Vitest cases passed,
  and the production build passed with only the documented MapLibre chunk advisory;
- all ten Playwright desktop/tablet stories passed, including the Otaniemi access
  map, streamed refinement, verified result, constraint explanation, and preserved
  Kallio solver states; the source/custom-location drawer remains covered by three
  frontend component cases and its earlier committed browser captures;
- the full browser stories reported no console/page errors and regenerated the
  desktop/tablet screenshot set, which was visually inspected for the resilience
  map hierarchy, live diagnostic route, continuity-zone result, constraint
  workbench, attribution, and responsive stacking.

Historical Four Planters baseline release evidence from 2026-08-28:

- deterministic preprocessing validation passed with 1,342 nodes, 2,408 directed
  edges, 272 candidates, 38 analytical portals, 68 crossing records, 182 address
  clusters, and validated baseline-egress provenance;
- the complete 30-test solver/API/frozen-scenario suite passed in 7.21 seconds;
- frontend lint, strict typecheck, all 24 unit tests, and the production build passed;
- all eight Playwright desktop/tablet stories passed in 1.4 minutes, covering solve
  refinement, alternatives, street locking, verified UNSAT, timeout, cancellation,
  and the regenerated release screenshots;
- desktop (1,440 × 900) and tablet (820 × 1,180) browser audits reported no material
  console, network, overflow, or accessibility errors.

The release handoff records the output from all of the following on the final working
tree:

- Python tests and scenario invariants pass.
- Frontend unit tests, lint, typecheck, and production build pass.
- End-to-end main story and infeasible-state tests pass.
- Firefox console contains no material errors.
- Curated desktop and tablet screenshots are present under `docs/screenshots/` for
  resilience [before](screenshots/four-planters-resilience-before-desktop.png),
  [refinement](screenshots/four-planters-resilience-refinement-desktop.png),
  [verified](screenshots/four-planters-resilience-verified-desktop.png), and the
  [constraint workbench](screenshots/four-planters-constraint-workbench-desktop.png),
  the [route solver vs Z3 guide](screenshots/four-planters-solver-comparison-desktop.png),
  and the preserved Kallio before/verified/comparison/UNSAT states, with corresponding
  tablet files. These are committed release evidence and are regenerated by the
  Playwright main-story run.
- The passing production build may retain Vite's large-chunk advisory; record it as a
  known load-performance limitation rather than treating it as a failed build.
