# Instructions for agents continuing this repository

This is **A plan that fits**: an educational, self-guided browser introduction to constraint solving in geography, using Z3. The opening headline is “Can this neighbourhood keep delivering?”. Explain the solver concept before assuming the audience knows Z3. It is not a logistics product, generic geospatial workbench or collection of unrelated examples.

Read [README.md](README.md), [docs/agent-handoff.md](docs/agent-handoff.md) and [docs/model.md](docs/model.md) before changing behaviour. Read [data/README.md](data/README.md) before changing geographic processing, and [docs/development.md](docs/development.md) before changing the worker or hosting.

The owner-authorized single-depot-outage expansion in
[docs/expanded-scenario.md](docs/expanded-scenario.md) is now the generated
scenario. Do not treat local two-depot reach as full feasibility: Z3, exhaustive
search and the verifier all check capacity-feasible contingency assignments.

## Non-negotiable invariants

- Walking eligibility is **at most 500,000 integer millimetres**, including the cell-to-path connector plus directed walking edges. Do not introduce a walking-distance slider or silently use straight-line coverage.
- Residents walk **to lockers**; drones supply lockers **from depots**. Drone range is **return distance**, not one-way distance. Never imply that these are real approved flight routes or real locker sites.
- Assign every cell's whole illustrative daily demand to exactly one open locker. Assign each open locker to exactly one open depot in normal operation and to one remaining depot in every requested outage case. Both capacities apply, with depot load summed across its lockers. No unused sites in the normal plan; contingency plans may leave available depots unused.
- Omitted `fixedLockerIds`/`fixedDepotIds` means free choice. An array means **exactly** that set; `[]` means zero. Do not change this to “these plus any others”. Display the scope of every result.
- Validate the complete geographic eligibility matrix before solving. An omitted allowed pair can create a false UNSAT claim. Verify a feasible result independently before displaying it.
- SAT is feasible, not optimal. UNSAT concerns only this finite candidate set and these rules. Timeouts, cancellations, worker errors, validation failures and stale replies are not UNSAT. Unsat cores are conflicting rule groups, not necessarily minimal explanations or suggested repairs.
- Keep browser-local JavaScript/TypeScript + Z3 WebAssembly. No Python/backend fallback, API keys, CDN runtime, external tiles or analytics. Serve from the project's own subpath. Do not bundle Emscripten's `z3-built.js` into the high-level worker bundle.
- Do not edit `public/data/scenario.json`, `public/runtime/`, `public/coi-serviceworker.js`, `public/third-party-notices.txt` or `dist/` manually. Use the documented builders. Do not refresh frozen sources or change candidates to make a test pass.
- Preserve source attribution, raw source hashes and the difference between real geography and invented planning rules. Do not add claims about individual homes from aggregate cell points.
- The planning game must remain winnable: exactly 10 lockers and 4 depots have a tested capacity-feasible selection that survives each single-depot outage. Live game checks show necessary geographic conditions only; they must not claim full feasibility before Z3 and the independent verifier run. Keep an immediate “Let Z3 find a plan” escape hatch.
- In the game, map locker circles and depot labels are controls. A locker’s backup-reach warning must count selected eligible depots from `scenario.flights` and the active return-flight limit. Do not replace this with a geometric map radius: flight eligibility uses the frozen exact return distances.
- Step 2 starts with all candidates visible but no lockers or depots selected. Keep the prepared starter only in the inspection/conflict chapters; do not silently turn it back into the player's starting answer.
- `src/exhaustive/model.ts` is an independent exhaustive implementation of the same finite decisions and exact-selection semantics as Z3. Sound pruning may skip only branches that a stated constraint has already made impossible. Both engines must validate the complete scenario, use the same request, and pass feasible plans through `verifyPlan`. Describe browser timings as illustrative warm runs, never a general solver benchmark.
- Run `npm run data:audit-complexity` before and after a scenario/model expansion. Update its pinned test intentionally: raw combination counts alone are insufficient; locally plausible selections and deterministic branch profiles must show whether effective difficulty changed.

## Change protocol

1. Take one bounded task from the handoff or the user's request. Identify its acceptance test before editing. Do not start a broad refactor or add another demo unless asked.
2. Inspect the worktree and preserve unrelated user edits. Do not read `.env`, reset branches, publish a site, or rewrite history as an incidental development step.
3. Make the smallest coherent change. UI/copy tasks normally stay in `src/ui/` and browser tests. Model tasks also need independent oracle/verifier tests. Data changes require explicit approval of changed teaching assumptions.
4. Run `npm run check` and, for UI/worker/build changes, `npm run test:e2e`. Report failures honestly; do not weaken assertions, replace real solves with fixtures, or call unrun tests passed.
5. Review desktop/tablet screenshots. Update the handoff's verification notes and remaining tasks if their status changed. State exactly what was and was not tested.

Use Node 24.15.0 via `.nvmrc`; commit the lockfile when deliberately changing dependencies. Never run dependency upgrades as unrelated cleanup. `npm run predev` rebuilds the classic solver bundle: **restart `npm run dev` after edits in `src/solver/` or `src/core/`**. The normal Vite watcher does not rebuild that separate worker.

In the original managed workspace, `.git` is an empty read-only mount. If `.git-local/HEAD` exists, use `git --git-dir=.git-local --work-tree=.`. In a normal checkout, use ordinary `git`; do not copy `.git-local` into source control.

The retired demos are recoverable at `archive/geographic-demos-2026-09-05` / `7f2bdaf`. The current tree intentionally has one demo. Ignored old environment/cache directories can remain locally; they are not implementation dependencies.
