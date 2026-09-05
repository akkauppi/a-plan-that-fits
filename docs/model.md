# Model contract

This document defines the teaching model implemented in [model.ts](../src/solver/model.ts). Change it only together with the tests and the tour's explanation.

## Facts, decisions and rules

Geographic preprocessing finds the allowed connections. Z3 chooses a network using those facts; it does not calculate walking paths.

| Quantity | Meaning | Default |
| --- | --- | --- |
| Walking limit | Representative-point connector + directed path to a locker | **500 m, fixed** |
| Locker budget | Maximum number of open, used lockers | 8 of 15 candidates |
| Depot budget | Maximum number of open, used depots | 2 of 4 candidates |
| Locker capacity | Parcels assigned to one locker each day | 200 |
| Depot capacity | Parcels supplied across all of one depot's lockers each day | 600 |
| Drone range | Twice the straight-line EPSG:3067 distance from depot to locker | 2 km return |
| Cell demand | `ceil(published population / 10)` | 871 total parcels/day |

All distances are integer millimetres; inclusive comparisons use `<=`. Edge lengths are rounded to millimetres once, then summed. Connectors and return flights are rounded once to integer millimetres. Eligibility is defined at that precision, not by rounded metre labels in the UI.

For each candidate locker/depot, a Boolean says whether it is open. For each allowed cell–locker pair, a Boolean says whether the cell collects there. For each allowed locker–depot pair, a Boolean says whether that depot supplies the locker.

The constraints are:

1. Each cell chooses exactly one eligible locker. Its whole demand travels together; there is no fractional allocation or multiple daily suppliers.
2. A locker is open if and only if at least one cell is assigned to it. Its load is the sum of those cells' parcels.
3. An open locker chooses exactly one eligible supply depot; a closed locker chooses none.
4. A depot is open if and only if it supplies at least one locker. Its load is the sum of all parcels at the lockers it supplies.
5. Open-site counts and both types of load respect the requested limits.
6. Optional exact site selections are honoured. There are no additional unstated sites.

For example, locker load is `sum(if(cell_assigned_here, cell_parcels, 0))`. Depot load is `sum(if(locker_supplied_here, locker_load, 0))`. These are Boolean decisions with integer arithmetic. This slice uses Z3's `Solver`, not `Optimize`.

### Exact selections are part of the question

| Request field | Interpretation |
| --- | --- |
| `fixedLockerIds` omitted | Z3 may choose any locker subset within the budget |
| `fixedLockerIds: ['A', 'C']` | Exactly A and C open; every other locker closed |
| `fixedLockerIds: []` | No lockers open |
| `fixedDepotIds` | Identical semantics for depots |

Invalid IDs, duplicate IDs, non-integer limits or out-of-range input are **errors**, not UNSAT. See [validateRequest](../src/core/validate.ts). Budgets may be zero. Capacities are 0–10,000 parcels/day, return range 0–10,000,000 mm, and solver timeout 1–30,000 ms. The tour normally uses 15 seconds.

## Pinned teaching cases

Starter lockers: **A, C, D, E, G, H, I, M**. The built starter assignments satisfy walking and locker capacity only. They are computed by a deterministic, small backtracking allocator during the data build, not presented as a cached live Z3 answer.

| Case | What remains fixed | Expected result |
| --- | --- | --- |
| Joint baseline | Original rules; no exact selections | Feasible, 8 lockers and 2 depots |
| Starter supply challenge | Exact starter lockers; any 2 depots | UNSAT |
| Add a depot | Exact starter lockers; up to 3 depots | Feasible |
| Extend drone range | Exact starter lockers; 2 depots; 2.4 km return | Feasible |
| Seven lockers | All sites free; at most 7 lockers | UNSAT |

The planning puzzle is winnable. One regression witness is lockers A/C/D/E/G/K/L/N with depots West/East. This is not presented as the unique or optimal answer, and the UI does not hard-code it as a hint. It protects the promise that a player can succeed using exactly eight lockers and two depots.

The starter contradiction has a simple geographic witness: at 2 km return range, H can only use South, I can only use West, and E needs East or North. These three disjoint requirements need at least three depots. The test checks the actual flight table behind that explanation.

Seven lockers remain impossible even with ample capacities and drone range: within this frozen candidate set, eight are needed for walking coverage. Do not imply that depot capacity or longer flights can repair that geographic constraint. Conversely, do not extrapolate the impossibility to all possible sites in Espoo.

The regression tests assert these results and verify assignments. They deliberately do not pin the arbitrary feasible layout Z3 happens to return.

## What the result establishes

- `feasible`: a model was extracted **and** [verifyPlan](../src/core/verify.ts) accepted it. The checker has no Z3 imports; it reconstructs directed walks from edge IDs, recalculates return-flight distances, and independently counts assignments and shared loads.
- `unsat`: Z3 proved the encoded constraints incompatible after scenario completeness validation. A conflicting set of named rule groups accompanies the result. It need not be smallest, unique or a ranked repair list. The exhaustive JavaScript implementation can independently prove the same finite search exhausted; unlike Z3, it does not calculate an unsat core.
- `timeout`, `cancelled`, `error`: no feasibility conclusion. The UI must not retain an older result as if it belonged to the current question.

The pre-solve validator recomputes shortest paths on the **full frozen walking graph**, including every allowed cell–locker pair within 500 m, and checks every return-flight entry. Checking only routes selected by a model is insufficient: omissions can falsely exclude a feasible solution.

## Two implementations, one question

[`solveScenario`](../src/solver/model.ts) expresses the decisions as Boolean and integer constraints for Z3. [`solveByEnumeration`](../src/exhaustive/model.ts) is a brute-force implementation that independently enumerates locker sets, depot sets, whole-cell assignments and one-depot-per-locker supply assignments. It prunes only after a stated budget, eligibility, use or capacity rule makes every completion of that branch impossible. It never calls Z3.

The browser comparison gives both engines the same validated scenario, request and 15-second limit. They run sequentially in separate warm workers, and each feasible plan passes through the same independent verifier. Displayed time includes validation, search/model construction and verification, but excludes download and worker initialization. Branch counts describe only the exhaustive run. One run on this small structured fixture is explanatory evidence, not a general performance benchmark; different search order, browser, hardware or model can reverse the result.

## Deliberate limits

This is a demonstration of coupled choices, not a claim of Z3 exclusivity or scalability superiority. Integer programming or custom search are alternatives. The in-browser timing comparison is not a statistically controlled benchmark, and there is no optimality claim here.

We do not model individual addresses, delivery-time distributions, routing between multiple lockers, fleet size, flight schedules, wind, obstacles, airspace, battery reserves, construction costs, site ownership or outage resilience. Population, routing topology and representative-point assumptions are frozen and fallible. See [data notes](../data/README.md).
