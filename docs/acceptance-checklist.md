# Four Planters acceptance checklist

This checklist is intentionally based on observable behaviour and independent graph
verification rather than a single expected intervention set.

## Data and provenance

- Frozen scenario identifies its OpenStreetMap snapshot, polygon, query, CRS, and ODbL licence.
- Street, building, protected-corridor, portal, candidate, and address-cluster references validate.
- Browser startup does not fetch live OSM data or require a tile service.
- The map keeps visible OpenStreetMap attribution.

## Solver proof obligations

- Selected filters are eligible, unique, and within budget.
- Forced filters are selected; locked-open and protected edges are not selected.
- Every requested portal pair is disconnected in a fresh private-car graph.
- Every included address cluster reaches at least one permitted portal.
- Walking and cycling remain unchanged by the private-car-only filter abstraction.
- Emergency permeability is asserted only when the removable/gated-filter assumption is enabled.
- A candidate result is never labelled final before independent NetworkX verification.
- Timeout, cancellation, UNSAT, unblockable routes, and verification errors are distinct outcomes.
- Repeated solves of the same state produce the same first solution and event order.

## Interface story

- Initial viewport explains the permeability question, shows four as the budget, and exposes one clear solve action.
- Boundary, hierarchy, buildings, protected corridors, portals, candidates, and the illustrative existing route are legible.
- Counterexample routes and model refinements appear as actual streamed solver events.
- Street inspection supports force-filter, lock-open, and return-to-neutral states.
- Portal pairs are selectable without relying on colour alone.
- Verified results expose local-access and portal-connectivity summaries.
- Another equal-objective solution can be requested and compared.
- Method and limitations use the scoped scientific claim and avoid traffic-forecast or legal-feasibility claims.
- Keyboard focus, reduced motion, desktop, and tablet layouts remain usable.

## Release checks

- Python tests and scenario invariants pass.
- Frontend unit tests, lint, typecheck, and production build pass.
- End-to-end main story and infeasible-state tests pass.
- Firefox console contains no material errors.
- Curated desktop and tablet screenshots are present under `docs/screenshots/`.
