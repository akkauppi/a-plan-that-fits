# HTTP API

All scenario coordinates exposed to the browser use WGS84 longitude/latitude. The
analytical graph is frozen with the scenario and may use a projected metric CRS.

## `GET /api/health`

Returns the legacy top-level service state and Kallio snapshot identifier. The
top-level `ready` field retains its original meaning—whether the modal-filter
scenario is available—so existing clients remain compatible.

The additive `experiments` object reports the three runtimes independently:

```json
{
  "status": "ok",
  "ready": true,
  "service": "geospatial-constraint-lab",
  "scenario_id": "helsinki-kallio-vallila",
  "snapshot_id": "…",
  "experiments": {
    "modal_filter": {
      "status": "ready",
      "ready": true,
      "scenario_id": "helsinki-kallio-vallila",
      "snapshot_id": "…"
    },
    "resilient_access": {
      "status": "ready",
      "ready": true,
      "scenario_id": "otaniemi-access-v1",
      "snapshot_id": "…"
    },
    "service_coverage": {
      "status": "ready",
      "ready": true,
      "scenario_id": "service-coverage-otaniemi-tapiola-v1",
      "snapshot_id": "coverage-4e7e682613eb7d074b8a3341"
    }
  }
}
```

Normal server startup validates and warms each frozen experiment before reporting
it as ready. A failed optional experiment reports `status: "data_error"`,
`ready: false`, and an error string in its own entry without disabling a healthy
experiment. Before lifespan validation, an entry may say `not_checked`; this is
never presented as ready.

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

## Otaniemi resilient-access API

These endpoints operate on the frozen `otaniemi-access-v1` evidence package. They do
not infer that source exposure closes a road and do not consume MML terrain in the
availability model.

### `GET /api/resilience/scenario`

Returns the immutable browser payload for snapshot
`base-c8dcbcfaca2b2c9498420681+flood-bf45a84ac9ce456045f8932b+espoo-0c59d1ca21a9e918b058`,
including:

- the core and 750 m network-context boundaries;
- 8,048 private-car physical-segment display features and 1,189 Espoo buildings;
- clipped 1/100 and 1/1000 Syke exposure intersections;
- 15 representative 500 m cells derived from 297 in-core Espoo address points;
- four reviewed outbound graph endpoints;
- map-visible continuity groups for each return period;
- a precomputed default disruption analysis, teaching/all-cell presets, defaults,
  source counts, effective private-car counts, attribution, and claim semantics.
- `snapshot_components` with checked base/flood artifact hashes and the exact Espoo
  manifest, address, building, query, compressed-archive, and raw-content identities.

The four endpoint groups are an OR set for each origin: access to at least one
selected destination is required. They are not certified safe destinations.

### `POST /api/resilience/solve`

Accepts:

```json
{
  "scenario_id": "otaniemi-access-v1",
  "flood_return_period_years": 1000,
  "treat_flood_exposure_as_unavailable": true,
  "roadworks_segment_ids": [],
  "origin_ids": ["origin-88bb182e9f"],
  "gateway_group_ids": ["gateway-east-kuusisaarentie"],
  "analytical_repair_budget": 4,
  "timeout_seconds": 30
}
```

`treat_flood_exposure_as_unavailable` is the explicit binary stress assumption. If
false, source exposure remains visible evidence but creates no flood decision
variables or unavailable links. `roadworks_segment_ids` are exact private-car
physical links treated as fixed unavailable; they are removed from eligible
continuity groups and no solver choice can restore them. Each continuity commitment
is one Boolean `passable[group_id]` grouping connected exposed fragments by normalized
street name, or by OSM way/highway continuity when unnamed. Selecting one restores
only its flood-assumption removals. The budget counts that group once; the result
separately expands it to exact OSM physical-fragment IDs. The API accepts budgets
0–16 and deadlines 1–120 seconds. That
deadline spans initial disruption analysis, graph construction and route searches,
every Z3 check, refinement, and fresh verification.

The response is `text/event-stream`. Events expose real analysis state:

- `started`: the availability scenario was compiled;
- `candidate_found`: Z3 proposed selected decision and expanded segment IDs;
- `counterexample_found`: NetworkX found a stranded origin, a map-ready diagnostic
  route, the directed reachable region, and frontier decision IDs;
- `verified_optimal`, `verified_unsat`, `timeout`, `cancelled`, or `data_error`: the
  distinct terminal state;
- the terminal event carries the complete `result`.

The public event's `route`/`witness_segment_ids` are diagnostic visual evidence. The
sound learned constraint is represented separately by `frontier_decision_ids`,
`learned_clause_ids`, and `constraint_expression`. For example, a frontier becomes
`passable[zone_a] ∨ passable[zone_b]`; the diagnostic route is not inserted into
Z3 as a path clause. This access-frontier clause requires at least one alternative
to preserve a connection. By contrast, the modal-filter solver learns a path-cut
clause over `blocked[...]` candidates on a surviving portal route, requiring at
least one choice to sever that prohibited connection.

A verified-optimal result includes grouped and expanded selections, the explicit
objective values, the baseline and post-commitment access analyses, mapped routes and
detours, the learned constraint model, iteration count/time, and
`verification.method: "fresh_networkx_directed_graph"`. The default teaching result
is three groups, 21 expanded fragments, aggregation-length cost 388, and +1,093 m
mapped detour. These are model outputs, not project cost, road safety, capacity, or
legal-access findings. A selected group belongs to the returned optimum only in the
encoded model and may be replaceable in an equally good alternative; it does not
establish physical safety, legal availability, operability, protection, or funding.

A verified-UNSAT result means no assignment within the encoded continuity-group
budget satisfies all learned necessary access-frontier clauses, or that a stranded
frontier has no eligible group. Timeout and cancellation make no infeasibility claim.

### `POST /api/resilience/solve/cancel`

Accepts `{ "solve_id": "…" }`. Cancellation is cooperative across Z3 and graph
boundaries and returns HTTP 202 when the live solve ID is known. A cancelled stream
terminates as `cancelled`, never `verified_unsat`.

## Otaniemi–Tapiola equitable service-coverage API

These endpoints operate on frozen scenario
`service-coverage-otaniemi-tapiola-v1`, snapshot
`coverage-4e7e682613eb7d074b8a3341`. The checked solver artifact contains 33
published HSY population cells representing 8,554 residents, ten reviewed Service
Map facilities, 330 connector-inclusive walking-distance relations, and a compact 3,207-node / 4,426-edge
directed walking graph. The browser payload is stored separately from the solver
graph and matrix.

Facility identity and location come from Service Map, but the current
5,000-person capacity attached to every candidate is an **analyst-declared
sensitivity value**. It is not source data, observed throughput, room capacity,
staffing, accessibility, availability, or a recommendation to use that facility.

### `GET /api/service-coverage/scenario`

Returns the immutable browser payload: study bounds, frozen walking-network
linework, HSY cell polygons and representative points, reviewed candidate sites,
defaults, source attribution, methodology text, and snapshot identity. It does not
return a live service-area query and makes no source request at runtime.

### `POST /api/service-coverage/solve`

Accepts:

```json
{
  "scenario_id": "service-coverage-otaniemi-tapiola-v1",
  "site_budget": 4,
  "max_distance_m": 1600,
  "capacity_multiplier": 1,
  "forced_site_ids": [],
  "banned_site_ids": [],
  "timeout_seconds": 30
}
```

`site_budget` is an upper bound on active sites. `max_distance_m` is compared with
the frozen total `demand_connector_m + network_distance_m + site_connector_m`, not
with the graph component alone, a pure Euclidean point-to-point distance, or travel
time. `network_distance_m` is a directed shortest-path length. The two snap
connectors are projected straight-line approximations between source coordinates
and graph nodes; they are not sourced entrances or accessibility evidence. Each
included population cell is indivisible and must be assigned to exactly
one active, eligible site. A forced site must be active; a banned site must be
inactive. Duplicate IDs, an ID in both lists, or an unknown scenario are rejected
or returned as scoped data errors rather than silently repaired.

The effective capacity is:

```text
floor(analyst_declared_capacity[site] * capacity_multiplier)
```

The API accepts budgets 0–32, distance limits 100–5,000 m, capacity multipliers
0.1–4.0, and deadlines 0.01–120 seconds. The checked browser defaults are four
sites, 1,600 m, 1.0× capacity, and 30 seconds.

The response is `text/event-stream`. It exposes the real direct-solve phases:

- `started`: the API has accepted the request and loaded frozen evidence;
- `matrix_compiled`: Boolean `open[site]` and `assign[cell,site]` variables and
  named hard constraints have been constructed;
- `feasible_assignment`: Z3 has found a witness satisfying every active hard
  constraint, but optimality and fresh verification are not yet claimed;
- `objective_improved`: one lexicographic objective value has been proved and a
  map-ready current assignment is included;
- `fresh_verification`: the selected assignment has passed the independent
  matrix, graph, capacity, eligibility, force/ban, budget, and objective checks;
- `unsat_core`: tracked assumptions are inconsistent and the event carries the
  translated core and, where applicable, a demand-cell witness;
- `verified_optimal`, `verified_unsat`, `timeout`, `cancelled`, or `data_error`:
  the terminal event, whose `result` contains the complete result object.

Unlike the Kallio endpoint, the service-coverage terminal event is named directly
after its result state rather than `complete`. Callers should use `result.status`
as the authoritative terminal state in either convention. Intermediate feasible
assignments must never be displayed as final answers.

The four objective priorities are explicit and lexicographic:

1. selected-site count;
2. worst assigned walking distance;
3. population-weighted total assigned distance;
4. the population-load spread between the most and least loaded selected sites.

The compatibility field `objective_values.population_weighted_distance_m` contains
the weighted **total** in person-metres. The unambiguous aliases
`population_weighted_total_distance_person_m` and
`population_weighted_mean_distance_m` are returned alongside it. A later objective
can never compensate for a worse earlier objective.

A verified-optimal result contains:

- `selected_site_ids` and one `assignment` for every included cell;
- the cell and site IDs, cell population, connector-inclusive total distance, its
  demand/network/site component distances, and frozen route GeoJSON for each
  assignment;
- declared/effective capacity, assigned population, assigned-cell count, and
  utilisation for every site;
- both the exact integer `objective_vector` and human-unit `objective_values`;
- independent-verification booleans and detailed connector, node/edge-chain,
  shortest-path, geometry, component-sum, and graph checks;
- district summaries for inspection only—version 1 has no district hard rule;
- the named `constraint_model`, request assumptions, event history, timing, and
  snapshot IDs.

`verified_unsat` means the tracked exact-assignment, distance, site-budget,
capacity, force, and ban constraints have no joint assignment. Diagnostics
distinguish cases such as an uncovered demand cell and insufficient declared
capacity under the budget, and suggest explicit relaxations. A 30-second timeout
means the optimality or feasibility proof did not finish; it makes no infeasibility
claim. A disagreement between Z3 output, the frozen matrix, and fresh NetworkX
verification is `data_error`, not a partially verified solution.

The core supports excluding an earlier selected-site set while fixing the complete
objective vector, but equal-objective alternative enumeration is not yet a public
Experiment 03 endpoint.

### `POST /api/service-coverage/solve/cancel`

Accepts `{ "solve_id": "…" }`. Cancellation is cooperative during Z3 and fresh
NetworkX verification and returns HTTP 202 for a known active solve. The terminal
state is `cancelled`, never `verified_unsat`; an unknown or completed ID returns
HTTP 404.

## Resilient-access scenario-builder API

These endpoints publish verified **base-network artifacts** beside the two loaded
scenarios. They do not change either the Kallio modal-filter solver or the frozen
Otaniemi resilience runtime, derive flood availability, review origins/exits, or
claim safe access.

### `GET /api/scenario-builder/catalog`

Returns the default frozen Otaniemi preset, Finland-v1 point/radius limits, the
750 m context-buffer policy, and an explicit statement that the active solver is
unchanged.

### `POST /api/scenario-builder/preflight`

Accepts one of:

```json
{}
```

```json
{ "preset_id": "otaniemi-coastal-v1" }
```

```json
{
  "area": {
    "kind": "point_radius",
    "longitude": 24.827,
    "latitude": 60.185,
    "radius_m": 1000
  }
}
```

An empty body selects the frozen Otaniemi preset. A custom radius must be 100–2,500
m and the complete area must pass the Finland profile bounds. The response contains
the deterministic recipe identity, core and context bounds, local archive
readiness, current derived snapshot (if any), and source-specific coverage states.
Preflight is offline and does not fetch, prove completeness, infer closure, or
mutate the solver.

For the frozen Otaniemi preset, `analysis_artifacts.flood_exposure` also reports the
validated exposure snapshot ID and the 1/100 and 1/1000 segment, overlap-length, and
vertical-review counts. Its `scope` is always `exposure_only` and
`passability_inferred` is always `false`. A custom area without frozen hazard inputs
returns `not_requested`; missing, incompatible, and invalid artifacts are not shown
as verified.

The same preset's `sources` list includes the separately validated
`mml_elevation` archive. It reports `readiness: "archived"`, offline availability,
acquisition time, and a human-readable 1,616 × 1,734 grid/height-range summary.
`feature_count` is null because raster cells are not vector features. Preflight does
not read `MML_API_KEY`, and no elevation value is interpreted as flooding, closure,
passability, or safety.

### `POST /api/scenario-builder/jobs`

Starts one background base-network build and returns HTTP 202 with the job record.
Offline replay is the default:

```json
{ "preset_id": "otaniemi-coastal-v1" }
```

A live bounded Overpass request requires two explicit fields:

```json
{
  "area": {
    "kind": "point_radius",
    "longitude": 24.827,
    "latitude": 60.185,
    "radius_m": 1000
  },
  "refresh": true,
  "confirm_live_source_refresh": "REFRESH_OSM"
}
```

Supplying the acknowledgement without `refresh: true`, or requesting refresh
without the exact acknowledgement, returns HTTP 422. Arbitrary endpoint URLs are
not accepted. Only one job may be active; a second start returns HTTP 409.

Job states distinguish `queued`, `preflighting`, `building`,
`cancellation_requested`, `verified`, `missing_archive`, `failed`, and `cancelled`.
A custom offline build with no matching frozen archive becomes `missing_archive`,
not an empty graph or a live request.

### `GET /api/scenario-builder/jobs/{job_id}`

Returns the current job record, event history, error envelope, and verified result
when complete. A verified result reports the immutable snapshot ID, path, node and
directed-edge counts, and `scope: "base_network_only"`.

### `GET /api/scenario-builder/jobs/{job_id}/events?after=N`

Returns events whose monotonically increasing `sequence` is greater than `N`. This
is bounded polling, not Server-Sent Events. Event messages distinguish source
replay/refresh, validation, publication, cancellation, missing archive, and failure.

### `POST /api/scenario-builder/jobs/{job_id}/cancel`

Requests cooperative cancellation and returns HTTP 202 when accepted. Cancellation
is checked between deterministic build steps. If the request arrives after an
immutable artifact has been published, the artifact may remain in the cache, but it
still does not activate or replace the Kallio solver. Cancelling an already terminal
job returns HTTP 409.
