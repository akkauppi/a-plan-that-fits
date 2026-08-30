# Solver API

All scenario coordinates exposed to the browser use WGS84 longitude/latitude. The
analytical graph is frozen with the scenario and may use a projected metric CRS.

## `GET /api/health`

Returns service state and the loaded snapshot identifier.

## `GET /api/scenario`

Returns the immutable browser scenario: metadata, bounding polygon, street and
building feature collections, protected corridors, portals, candidate cross-street
symbols, address clusters, default portal pairs, visible attribution, and the
GeoJSON terminal zone in which otherwise local street segments are ineligible under
the 60 m analysis-boundary setback rule. It also returns
`portal_approach_zones`, the boundary-clipped union of 120 m EPSG:3067 buffers around
the mapped crossing points of all eight primary/selectable portals. This second,
static candidate setback is independent of which pairs a request selects. Candidate
records expose both distances plus the nearest primary portal and source-crossing
IDs. These zones communicate analytical endpoint-bias assumptions, not protected
transport or site-feasibility findings.

## `POST /api/solve`

Accepts:

```json
{
  "scenario_id": "helsinki-kallio-vallila",
  "budget": 4,
  "required_portal_pairs": [{ "a": "p-east-01", "b": "p-south-04" }],
  "forced_interventions": [],
  "locked_open_streets": [],
  "emergency_permeable": true,
  "service_access_enabled": false,
  "objective_mode": "balanced",
  "timeout_seconds": 30
}
```

`timeout_seconds` is the total per-run solver deadline. The browser presents the
review-friendly presets 5, 10, 30, 60, and 120 seconds, defaults to 30 seconds, and
serializes a non-default selection as `timeout=` in the shareable URL. The API schema
accepts values from 0.01 through 120 seconds for diagnostic clients. Expiry produces
a terminal `timeout` result with an indeterminate explanation; it is never translated
to `verified_unsat`. An API caller that omits the field receives the service default
of 30 seconds; the browser always sends its explicit selection.

`service_access_enabled` is reserved for a future separately modelled service-access
graph. The current API accepts only `false`; requesting `true` returns HTTP 422 with
an explicit `service_access_enabled` validation error. This prevents an unsupported
mode assumption from appearing in a verified result.

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
the explicit objective vector, verification summaries for private-car portal pairs
and local private-car access, timing, iteration count, a human explanation, and the
snapshot ID. Walking and cycling are not separate verification graphs in this frozen
scenario: the intervention semantics simply do not apply private-car edge removals to
those modes. Emergency passage is likewise an explicit removable/unlockable-filter
assumption, not a computed route guarantee.
`objective_values.access_penalty` is the additive baseline-egress exposure proxy
documented in the frozen scenario metadata; it is not a distance. Exact post-solution
egress changes are returned separately in `local_detour_metrics` in metres.
Objective order is lexicographic rather than a hidden aggregate score:

- `balanced`: intervention count, weighted cost, access exposure, adjacency penalty;
- `access`: intervention count, access exposure, weighted cost, adjacency penalty;
- `fewest`: intervention count only.

The adjacency term discourages spatially concentrated filters. It is a layout proxy,
not an operational feasibility judgement.

A verified result also returns `baseline_components` and `filtered_components` as
GeoJSON line feature collections. Their metric is stated explicitly in
`private_car_connectivity.metric` as `directed_strongly_connected_components`, with
before/after component counts and related node summaries. Each component represents
mutual reachability while respecting one-way streets; it is not a traffic forecast.
`components` remains a compatibility alias for `filtered_components`.

## `POST /api/solutions/next`

Accepts the solve request plus the prior `solve_id`. It fixes that solve's objective
vector, excludes its structural intervention set, and streams the next equally good
solution when one exists.

## `POST /api/solve/cancel`

Accepts `{ "solve_id": "…" }`. Cancellation is cooperative and is reported as
`cancelled`, never as `verified_unsat`. A per-run cancellation event interrupts an
active Z3 check and is also observed at deterministic graph-analysis boundaries.

## `POST /api/solve/json`

A non-streaming diagnostic endpoint used by tests and command-line verification.
It has the same request and final-result shape as the streaming solve.
