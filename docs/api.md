# Solver API

All scenario coordinates exposed to the browser use WGS84 longitude/latitude. The
analytical graph is frozen with the scenario and may use a projected metric CRS.

## `GET /api/health`

Returns service state and the loaded snapshot identifier.

## `GET /api/scenario`

Returns the immutable browser scenario: metadata, bounding polygon, street and
building feature collections, protected corridors, portals, candidate cross-street
symbols, address clusters, default portal pairs, and visible attribution.

## `POST /api/solve`

Accepts:

```json
{
  "scenario_id": "vallila-kallio-2026-08",
  "budget": 4,
  "required_portal_pairs": [{ "a": "portal-n", "b": "portal-s" }],
  "forced_interventions": [],
  "locked_open_streets": [],
  "emergency_permeable": true,
  "objective_mode": "balanced",
  "timeout_seconds": 10
}
```

The response is `text/event-stream`. Each `solve_event` data object has a `type`
and monotonically increasing sequence number. Progress types include `started`,
`candidate_found`, `counterexample_found`, `refining`, and
`candidate_rejected`. Terminal types are deliberately separate:

- `verified_optimal`
- `verified_unsat`
- `timeout`
- `cancelled`
- `data_error`

The stream ends with `complete`, whose `result` includes selected candidate IDs,
the explicit objective vector, verification summaries for portal pairs and local
access, timing, iteration count, a human explanation, and the snapshot ID.

## `POST /api/solutions/next`

Accepts the solve request plus the prior `solve_id`. It fixes that solve's objective
vector, excludes its structural intervention set, and streams the next equally good
solution when one exists.

## `POST /api/solve/cancel`

Accepts `{ "solve_id": "…" }`. Cancellation is cooperative and is reported as
`cancelled`, never as `verified_unsat`.

## `POST /api/solve/json`

A non-streaming diagnostic endpoint used by tests and command-line verification.
It has the same request and final-result shape as the streaming solve.
