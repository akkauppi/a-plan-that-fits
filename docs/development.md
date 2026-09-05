# Development and hosting

## Reproducible commands

Use Node 24.15.0 (`nvm use` if you use nvm). No Python environment is needed.

```sh
npm ci
npm run check
npx playwright install chromium
npm run test:e2e
```

| Command | Purpose |
| --- | --- |
| `npm run dev` | Prepare browser runtime; start Vite on localhost |
| `npm run build` | Prepare runtime; type-check; build `dist/` |
| `npm run preview` | Serve the existing build on localhost |
| `npm run data:build` | Rebuild the committed scenario from frozen inputs and recipe |
| `npm run data:validate` | Check source hashes and byte-identical deterministic rebuild without writing |
| `npm run data:audit-candidates` | Replay how the 24 locker candidates were chosen; compare to the frozen recipe without writing |
| `npm run data:audit-complexity` | Report deterministic raw/effective search-space counts and brute-force branch profiles without writing |
| `npm run data:explore-expansion` | Derive and audit the read-only 24-locker/6-depot resilience proposal without writing |
| `npm test` | Real Z3 regression cases, exhaustive oracle, data checks and client lifecycle tests |
| `npm run check` | Types + data validation + Node tests + production build |
| `npm run test:e2e` | Test existing `dist/` in browsers under `/tour/`, without isolation headers |
| `node tools/serve.mjs` | Manually inspect that same header-less static build at `http://127.0.0.1:5187/tour/` |

**Rebuild before browser tests.** Playwright intentionally tests the production artifact, not the Vite development server. Screenshots and failure traces go into ignored `test-results/`; reports into `playwright-report/`.

The current Vite build warns about the two intentional classic isolation scripts and the large MapLibre app chunk. These are known first-slice packaging warnings, not failed checks. Do not resolve the classic-script warning by bundling Emscripten or moving bootstrap URLs to the origin root. Payload optimisation is a separate task and must preserve the complete graph and cold-start tests.

`predev` bundles the solver workers once. After editing `src/core/`, `src/solver/` or `src/exhaustive/`, restart the dev command. Vite's app hot reload alone does not rebuild those separate workers. Production builds rebuild them explicitly; run a build before the browser suite.

In restricted agent environments, localhost binding, browser launch or test subprocesses may require execution approval. Request that approval rather than changing the implementation, weakening tests or adding a server fallback. In this original workspace, use `git --git-dir=.git-local --work-tree=.` if `.git-local/HEAD` exists; elsewhere use ordinary Git.

## Small architecture, explicit boundaries

```text
frozen input + recipe
       │ tools/build-data.mjs (Node; no Z3 needed)
       ▼
public/data/scenario.json
       ├── React / MapLibre: explanation, controls, map
       ├── classic Z3 Web Worker
       │      validate → Z3 → independent verification
       └── brute-force JavaScript Web Worker
              validate → enumerate/prune → same verification
```

- `src/core/types.ts`: shared, typed scenario/request/result contracts.
- `src/core/graph.ts`: integer-distance Dijkstra and directed route reconstruction.
- `src/core/validate.ts`: request validation and complete geographic eligibility checks.
- `src/core/verify.ts`: independent assignment/route/load checker. Keep Z3 out of this file.
- `src/solver/model.ts`: the whole constraint model and named rule groups.
- `src/solver/worker.ts`: WASM initialization and one in-flight solve.
- `src/solver/client.ts`: lifecycle, monotonically increasing request IDs, cancellation, crash handling and watchdogs.
- `src/exhaustive/model.ts`: transparent brute-force enumeration of the same site, collection and supply decisions, with sound constraint pruning and branch counts.
- `src/exhaustive/worker.ts`: separate browser worker used by the sequential comparison.
- `src/ui/App.tsx`: five-stop narrative, request scope and result invalidation.
- `src/ui/MapView.tsx`: local vector geography and one inspectable collection/supply journey.
- `src/ui/CandidateExplanation.tsx`: visible shortlist provenance and its distinction from the final solver-selected plan.
- `tools/candidate-selection.mjs`: repeatable walking-only shortlist procedure, checked against the frozen candidate IDs in tests.

Types are stripped by Node in tests/build-data and compiled by Vite/esbuild for browsers. Avoid TypeScript features requiring runtime transforms in shared modules (enums, parameter properties). Strict type checking is separate and mandatory.

## Browser Z3 and isolation

Z3's JavaScript bindings are a real WebAssembly build using worker threads and shared memory. Read the [upstream JavaScript documentation](https://github.com/Z3Prover/z3/blob/master/src/api/js/PUBLISHED_README.md) before changing its initialization.

`tools/prepare-runtime.mjs` copies the **pinned** `z3-solver@5.2.0` Emscripten script and WASM into `public/runtime/z3-5.2.0/`. It bundles our worker and Z3's high-level browser API separately, and generates a classic worker bootstrap. The bootstrap sets `globalThis.global = globalThis` in its own worker and imports the standalone Emscripten script before the bundle. Both `locateFile` and `mainScriptUrlOrBlob` resolve beside that worker, never at the site root or a CDN.

Do not bundle `z3-built.js`: its own pthread workers need the standalone script. A build that works in Node can still fail in a browser if this boundary changes.

Shared memory requires a secure, isolated browsing context. The project-local [coi-serviceworker](https://github.com/gzuidhof/coi-serviceworker) supplies COOP/COEP when a static host cannot set them. `public/isolation.js` waits for an active controller before one guarded reload. A fresh browser visit is part of acceptance, not just a warm developer tab. Service-worker scope is the project directory, not the entire origin.

Current acceptance covers Chromium desktop and tablet viewports. Other engines and embedded corporate browsers are not certified by this slice. WebGL is needed for the map, but the narrative, site controls and numeric route details remain available if map creation fails. WebAssembly, workers, `SharedArrayBuffer` and site isolation are required for solving. Unsupported or restricted contexts show an explanation; there is no silent remote solver.

Each client serializes solves. Cancellation terminates its worker, invalidates its generation, and starts a fresh runtime; Z3 additionally receives an interrupt. Wrong request IDs and old-worker replies are ignored. Expanded-tour requests use a 30-second solver limit; the client watchdog allows 5 additional seconds before restarting. Initial loading has a 60-second watchdog. These limits yield no conclusion, never UNSAT.

This is not an offline cache: the service worker forwards requests and adds headers. First load includes roughly 34 MB of WASM and 9 MB of uncompressed geography, plus the app/runtime scripts. No third-party assets or service calls are required while following the tour. External reference links open only when followed.

## GitHub Pages

The Vite base is relative (`./`). Keep asset, worker, WASM and service-worker URLs relative to the project path. Do not “fix” paths to `/runtime/...` or `/data/...`; that breaks repository Pages sites.

The [manual publication workflow](../.github/workflows/pages.yml) builds, checks, browser-tests, uploads only `dist/`, and deploys via GitHub Pages. It runs **only** on `workflow_dispatch`, not on a push. The independent [check workflow](../.github/workflows/check.yml) does not publish.

When the repository owner is ready to publish:

1. Push the reviewed slice to their repository, including its lockfile and frozen inputs. Preserve/push the archive tag if they want the named historical checkpoint remotely.
2. In repository Settings → Pages, choose GitHub Actions as the source.
3. Run “Publish static tour” manually and approve any configured `github-pages` environment gate.
4. Test the resulting HTTPS URL in a fresh browser profile. Confirm local initialization, a verified joint network, a genuine impossible case, and correct subpath asset loading.

These follow [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). A real remote deployment is deliberately not performed as part of this slice. Hosting requires owner authority and repository configuration.

## Tests and interpretation

The Node suite includes exhaustive enumeration of 32 tiny budget/capacity/range combinations plus exact-selection cases, independently compared with real Z3. A separate tiny outage oracle proves that redundant range alone is insufficient, compares both engines on feasible and impossible capacity-aware contingencies, and mutates returned outage plans against the independent verifier. The geographic fixture suite checks the pinned teaching cases and every offered repair. Mutation tests reject omitted eligible walks, route corruption, missing/duplicated demand, unreachable supply and shared-capacity violations. Client tests use a fake worker only for timing and stale-message control; the model and browser acceptance use real Z3.

The browser suite checks a cold service-worker bootstrap, an empty game start, map/keyboard site toggles, exact flight-table-based backup warnings, a manual exact resilient win, the solver escape hatch, verified outage plans, the three-depot impossibility, sequential Z3/brute-force comparisons, rule-change experiments, local-only asset requests, keyboard dialog behaviour and an unsupported-browser explanation. It captures the major story states at desktop and tablet sizes. It is not yet a full accessibility audit, long-running stress test or multi-engine certification.
