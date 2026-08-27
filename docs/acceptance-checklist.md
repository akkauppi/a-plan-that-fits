# Four Planters acceptance checklist

This checklist is intentionally based on observable behaviour and independent graph
verification rather than a single expected intervention set.

## Data and provenance

- Frozen scenario identifies its OpenStreetMap snapshot, polygon, query, CRS, and ODbL licence.
- Street, building, protected-corridor, portal, candidate, and address-cluster references validate.
- All 68 retained boundary crossings belong exactly once to one of 38 analytical
  portal clusters; no cluster exceeds the configured 60 m diameter.
- The browser exposes exactly eight primary portals, two per boundary side, while
  local-access verification can use every analytical portal.
- Browser startup does not fetch live OSM data or require a tile service.
- The map keeps visible OpenStreetMap attribution.
- Provenance states that the frozen graph is derived directly from the committed
  bounded Overpass response with custom deterministic topology; it does not describe
  the scenario as an OSMnx-produced family of mode graphs.

## Solver proof obligations

- Selected filters are eligible, unique, and within budget.
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

- Initial viewport explains the permeability question, shows four as the budget, and exposes one clear solve action.
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

## Release checks and evidence

The most recent targeted checks recorded during the 2026-08-26 release pass are:

- deterministic preprocessing validation passed with 1,342 nodes, 2,408 directed
  edges, 384 candidates, 38 analytical portals, 68 crossing records, 182 address
  clusters, and validated baseline-egress provenance;
- 28 non-Helsinki solver/API tests passed after the independent-verifier,
  deterministic-selector, route-antichain, service-validation, and cancellable-Z3
  work; the repeated frozen-Helsinki invariant/determinism test also passed in 18.7
  seconds;
- frontend lint, strict typecheck, the 15-test unit run, and the production build
  passed after the timeout/browser accessibility audit;
- desktop (1,440 × 900) and tablet (820 × 1,180) browser audits reported no material
  console, network, overflow, or accessibility errors.

Those are checkpoint facts, not permission to skip the final commands after later
source or data changes. A release handoff should record the output from all of the
following on one final working tree:

- Python tests and scenario invariants pass.
- Frontend unit tests, lint, typecheck, and production build pass.
- End-to-end main story and infeasible-state tests pass.
- Firefox console contains no material errors.
- Curated desktop and tablet screenshots are present under `docs/screenshots/` for
  [before](screenshots/four-planters-before-desktop.png),
  [verified](screenshots/four-planters-verified-desktop.png),
  [comparison](screenshots/four-planters-compare-desktop.png), and
  [UNSAT](screenshots/four-planters-unsat-desktop.png), with corresponding `-tablet`
  files. These are expected capture paths, not an assertion that the files have
  already been generated.
- The passing production build may retain Vite's large-chunk advisory; record it as a
  known load-performance limitation rather than treating it as a failed build.
