# First vertical slice: continuation handoff

Read this before starting work. The product direction is settled for this slice: **one excellent, self-guided demonstration of Z3 in geography**, using drone-supplied parcel lockers and a 500 m walking limit. Do not reopen the demo catalogue, introduce an API service or redesign the problem just because the next task looks easier that way.

The current working title is **A plan that fits**, with the opening headline **Can this neighbourhood deliver?** The opening screen explains “constraint” and “constraint solver” before introducing Z3 and links to a general introduction. Keep this concept-first approach: the audience is not expected to recognise Z3's name.

## Implemented end to end

- One React/MapLibre tour: question → play a winnable eight-locker/two-depot planning puzzle → reveal the prepared starter's supply contradiction → let Z3 choose jointly → explore two repairs and a tighter locker budget.
- Real browser Z3 5.2.0, running in an isolated classic worker from local static assets. No Python or remote solver.
- Complete frozen geographic fixture, reproducible Node build, source archives/hashes/licences and explicit hypothetical operating assumptions.
- Joint location, cell assignment and supply assignment model with parcel conservation and shared depot capacities. Independent route/load verification before feasible answers are displayed.
- Named conflicting rule groups, honest result scope, cancellation, timeouts, error states, single-flight request handling and stale-result rejection.
- A route inspector, keyboard-accessible site controls and explanation dialog, desktop/tablet layout, actual browser acceptance tests.
- A visible explanation of candidate selection and a reproducible `data:audit-candidates` command. The shortlist is a walking-only heuristic, distinct from both the prepared example and the final Z3 network. Step 1 is explicitly inspection-only; it does not toggle sites.
- A step-2 game where map markers and accessible site buttons toggle exact locker/depot choices. An on-map instruction makes both control paths explicit. After at least one depot is selected, a coral ring marks every locker candidate outside all selected depots’ exact 2 km return-flight range; this is computed from the frozen flight table, not a map-radius approximation. Live checks show uncovered cells, directly unreachable lockers and whether budgets are filled; they explicitly do not claim capacity feasibility. Z3 checks the player's exact plan, while “Let Z3 find a plan” removes those fixed choices. A known exact win is protected in the model tests, but not spoiled in the interface.
- The planning game starts and resets with every candidate visible but no selected locker or depot. The prepared starter remains only as an inspection/conflict example.
- A second, independent brute-force JavaScript implementation exhaustively searches the same site, collection and supply decisions without calling Z3. The chapter-4 comparison runs warm Z3 and brute-force workers sequentially on the identical request, shows status/time and transparent branch counts, sends both feasible plans through the same verifier, and explicitly disclaims general benchmark conclusions.
- `npm run data:audit-complexity` records deterministic raw and effective complexity: choice degrees, exact site combinations, locally plausible and fully feasible selections, plus representative brute-force branch profiles. Its pinned test prevents future work from claiming complexity based only on a larger combinatorial headline.
- CI checks and a manual-only GitHub Pages workflow. **No remote publication has been performed.**

The retirement checkpoint `7f2bdaf` / `archive/geographic-demos-2026-09-05` preserves all pre-slice changes. The old source tree, branding and demos have been removed. Raw geography that is actually reused remains under `data/` with new explanatory documentation.

## Baseline you must preserve

See [model.md](model.md) for exact semantics. At baseline there are 33 demand cells, 871 parcels/day, 15 lockers, 4 depots and 78 allowed walks. Walking is always **≤ 500,000 mm including connectors**. Default limits are 8 lockers, 2 depots, 200 parcels/locker/day, 600 parcels/depot/day and a 2,000,000 mm return flight.

The starter set A/C/D/E/G/H/I/M fails with any two depots; the joint free-choice model succeeds. Adding a third depot or extending return range to 2.4 km repairs the fixed starter. Seven lockers fail even when other restrictions are generous. These are executable cases, not copy that can be casually rephrased into a different promise.

## Verification record

Baseline work is checked with Node 24.15.0. `npm run check` is the release gate. Real Z3 is compared against exhaustive enumeration of 32 small combinations plus exact-selection cases. The Node suite also protects the frozen fixture, independent verifier, cancellation, worker watchdogs and stale-message handling.

Verification on September 5, 2026: **20 Node tests and 4 Chromium browser tests passed**, along with strict type checking, deterministic source/snapshot validation and the production build. The exhaustive engine agrees with Z3 on every pinned geographic question, including feasible, fixed-selection, repaired and globally impossible cases. The deterministic complexity audit is also pinned. Re-importing from the archive after retiring the old tree reproduced identical input, manifest and scenario hashes. Local documentation links and Git whitespace checks also passed. The production payload is approximately 45 MB before HTTP compression; download-size reduction is not part of this slice.

Browser acceptance uses the **built** site on a header-less server at `/tour/`, in fresh Chromium contexts at desktop (1440 × 1000) and tablet (820 × 1180) sizes. It checks the empty game start, map-based locker and depot toggles, the exact depot-reach warning, a manual game win, the solver escape hatch, sequential two-engine comparisons for feasible and impossible questions, the full story and both repairs, correct service-worker scope, site isolation, local-only asset requests and keyboard dialog behaviour. Run `npm run build` before `npm run test:e2e`; look at the generated start/game-empty/game-range/game-win/conflict/solved/comparison-feasible/comparison-impossible screenshots, not only the exit code.

Not yet established: a production GitHub Pages deployment, Firefox/WebKit compatibility, screen-reader audit, slow corporate-network behaviour, long-run memory use, or user comprehension with nontechnical colleagues. Do not report those as done just because Chromium passes.

## Choose one bounded next task

### 1. Introduce a genuinely hidden capacity near-miss

This is now the recommended next teaching improvement. Keep the game start empty. Under the current 600-parcel depot capacity, an exhaustive audit found that all 16 exact eight-locker/two-depot selections which pass the visible walking/range checks are also fully feasible, so the map checks currently make Z3 unnecessary once green. A trial with a round 450-parcel depot capacity retained feasible plans while making four of those 16 geographically plausible selections fail the coupled assignment/capacity model.

First turn that audit into a committed deterministic test or tool using the independent exhaustive engine. Then change the hypothetical capacity through `data/recipe.json` and the documented builder—never by editing generated scenario JSON—and protect at least one map-green/solver-UNSAT near-miss plus one exact feasible win in both engines. Do not preselect the near-miss when the game opens; reveal it as an optional challenge or explanation after the player has built from an empty map. Explain that 871 parcels leave little balancing room across two 450-parcel depots. Update every rule card, receipt, pinned case and screenshot affected by the assumption.

Acceptance: both engines agree on the near-miss and win, the independent verifier accepts both engines' feasible plans, the game still starts empty, visible checks remain explicitly necessary rather than sufficient, and the browser tour demonstrates why a green map can still fail. This is a deliberate teaching-assumption change already discussed with the owner; preserve the fixed 500 m walking rule and source geography.

### 2. Make the conflict visible on the map

This is the recommended next explanation improvement. The three-way H/I/E contradiction is currently clear in the side panel but not highlighted geographically.

Touch primarily `src/ui/App.tsx`, `src/ui/MapView.tsx`, `src/ui/styles.css` and `tests/browser/tour.spec.ts`. Add a chapter-3-only overlay for H→South, I→West, E→East/North. Derive admissibility from the real flight table and default range; do not hard-code invented line lengths or pretend these are a solver-selected plan. Clearly label them **possible supply connections**, visually distinct from a verified result's chosen supply line. Keep map buttons and the population-cell selector usable. Turning to another chapter must remove the overlay.

Acceptance: all current checks remain green; a browser assertion confirms the overlay only in the reveal chapter; at desktop/tablet sizes the highlighted depots and lockers are visible and legends explain the distinction. Numeric flight distances still come from the scenario. No model, range or data changes are needed.

### 3. Certify one additional browser engine

Touch `playwright.config.ts`, browser tests, and only the runtime/isolation files if a diagnosed problem requires it. Add a real Firefox project, install that browser explicitly, and run the cold-start/full-tour cases. Report the exact tested version. Do not add a server fallback, CDN worker or “pre-solved” animation to make it pass. If corporate restrictions prevent isolated workers, improve the explicit unsupported-browser guidance and record the limitation.

Acceptance: a clean profile starts from the project subpath, no reload loop occurs, SAT/UNSAT cases run through real WASM, cancellation remains honest, and external app requests remain absent. Update the browser support statement only after this succeeds. WebKit can be a separate task.

### 4. Facilitate a short colleague walkthrough

This needs people, not more model features. Ask a colleague to explain what the map does, what Z3 does, why the starter fails, and what a green result does not prove. Record where they hesitate. Then make a small copy/layout change with a corresponding browser check. Do not infer comprehension from a screenshot.

## Things deliberately deferred

No second demo, optimisation/cheapest-network objective, flight scheduling, resilience, live OSM import, individual addresses, shareable custom scenarios, offline installation, animated solver internals, arbitrary site editing or general solver framework. The current custom controls are sufficient for the first slice. A raw-source importer is separate from the normalized-input rebuild; do not confuse those boundaries.

The browser payload is intentionally larger than a polished distribution because it carries the full walking graph for eligibility verification. Do not trim it to only chosen routes to improve download size: that can invalidate UNSAT claims. Any later compression/splitting must preserve identical graph semantics and completeness tests.

## Safe workflow for an agent

1. Read [AGENTS.md](../AGENTS.md), then pick a task with a small edit surface. Tell the user the intended boundary.
2. Run the baseline checks. If they fail, diagnose without changing model assumptions or weakening tests. For source mismatch, stop and inspect the recipe/input/hash diff; do not regenerate a new hash to hide corruption.
3. Make the change. Restart the dev command after shared-core or worker edits. Do not hand-edit generated files.
4. Run the relevant focused test, then `npm run check`, then browser tests where applicable. Inspect screenshots. Preserve evidence of any unresolved failure.
5. Update this handoff with what changed, what passed and what remains. Hand off one coherent improvement, not a partially introduced new architecture.

Stop for owner direction if the task requires changing the 500 m rule, source snapshot, candidate set, demand interpretation, selection semantics, publishing destination, external services or another product direction. These are decisions, not routine implementation details.
