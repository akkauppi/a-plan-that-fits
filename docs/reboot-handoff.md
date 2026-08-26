# Reboot handoff — 2026-08-26

## State at freeze

The browser, data pipeline, solver service, streaming API, tests, and documentation
are present. All local Vite, Uvicorn, browser-capture, and agent processes were stopped
before this handoff.

The last design iteration reduced 40 visually cluttered boundary portals to eight
real analytical crossing groups (two contiguous groups on each side). Every retained
group contains all detected non-service car crossing nodes in its sector; the marker
is placed on the member crossing nearest the group centroid. This semantics is encoded
in the frozen metadata.

## Checks completed immediately before freeze

Passing:

```text
17/17 synthetic engine and API tests
8/8 frontend unit tests
TypeScript strict typecheck
Frontend ESLint
Python module compilation
Frozen scenario --validate-only
```

Known failing integration check:

```text
services/solver/tests/test_helsinki_scenario.py
expected: verified_optimal
actual:   timeout
timeout:  20 seconds per repeated deterministic solve
```

The test command spent about 40 seconds on its two runs and failed the first result
assertion. Earlier two-second results were against the old single-crossing portal
semantics and must not be quoted as evidence for the current eight-group dataset.

## Work in progress at interruption

`FourPlantersSolver._counterexample_batch` now batches multiple portal-node routes per
candidate and reports `routes_added`, but that first batching attempt is not yet enough
to prove the grouped default within the interactive timeout. The source compiles and
all synthetic tests pass, so it is a safe restart point rather than an unresolved
merge conflict.

Highest-value next action:

1. Profile one current default solve and inspect batch size/duplicate path clauses.
2. Generate a stronger deterministic set of distinct candidate-path clauses per pair
   and direction (or seed them with a candidate-capacitated cut/path routine).
3. Preserve the honest grouped-portal quantification; do not silently revert the UI
   to representative-node-only proof semantics.
4. Target a verified result below 10 seconds, preferably below five.
5. Re-run the Helsinki determinism test, the entire Python suite, production build,
   and Playwright desktop/tablet story.
6. Capture final before, verified, alternative, and UNSAT screenshots under
   `docs/screenshots/`; replace the current review-only timeout image.

## Restart commands

```bash
make setup
make data-validate
.venv/bin/pytest services/solver/tests/test_engine.py services/solver/tests/test_api.py
npm --prefix apps/web run test
make dev
```

After solver work:

```bash
.venv/bin/pytest services/solver/tests/test_helsinki_scenario.py -vv
make test
make build
make test-e2e
```

## Git metadata in this environment

The execution environment injects `/home/antti/zroad/.git` as an empty read-only
mount. `git init` therefore fails with `Read-only file system`. The checkpoint commit
uses `/home/antti/zroad/.git-local` as its Git directory and the workspace as its work
tree. Until the environment supplies a normal writable `.git`, use:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline -1
```

After reboot, if the injected empty `.git` mount is gone, a normal repository can be
created and the working tree recommitted with `git init`, or the local metadata can be
moved into place before using ordinary Git commands.
