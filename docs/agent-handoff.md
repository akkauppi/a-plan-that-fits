# Planning-constraints learning prototype: continuation handoff

Read [AGENTS.md](../AGENTS.md), [model.md](model.md),
[expanded-scenario.md](expanded-scenario.md) and [development.md](development.md)
before changing behaviour. This repository intentionally contains one
self-guided browser demonstration of constraint solving in geography.

## Public home and distribution

- Repository: [akkauppi/a-plan-that-fits](https://github.com/akkauppi/a-plan-that-fits).
- Demo: [GitHub Pages](https://akkauppi.github.io/a-plan-that-fits/).
- Our code and documentation: [MIT](../LICENSE). Geographic data and
  dependencies retain their separate licences and attribution.
- [CITATION.cff](../CITATION.cff) identifies the software. Public documentation
  should continue to distinguish implementation evidence from an unevaluated
  learning hypothesis.
- Pages uses an explicit manual deployment workflow. A push runs checks, not
  publication. See [deployment instructions](development.md#publish-an-update).

## Product story

The title is **A plan that fits** and the hero is **What makes a plan work?**
The research question is whether a map-based game and solver feedback help
people understand interacting planning constraints. This is an exploratory
prototype: no participant study has yet demonstrated a learning benefit. Read
[research-framing.md](research-framing.md) for claim boundaries, related work
and a proposed evaluation. Do not add participant tracking incidentally.

The tour follows **predict → check → explain**. Nontechnical users choose
hypothetical drone-supplied parcel lockers and depots on a real walking map.
Every population-cell representative point must have a directed walk of at most
500 m. The network must fit whole-cell
parcel demand, locker and shared depot capacities, a 2 km return-flight range,
and a complete supply reassignment after any one selected depot is unavailable.

The game starts with no selected sites and asks for exactly ten lockers and four
depots from 24 and six candidates. Map checks show walking coverage and whether
each locker has two selected depots in range. They are necessary conditions,
not a feasibility claim. Z3 checks hidden collection, normal supply and four
outage assignments. “Let Z3 find a plan” remains available.

The teaching boundary is four depots feasible, three UNSAT. Across all 20
three-depot choices, robust lockers cover at most 27 of 33 cells. An expandable
explanation shows this simple geographic proof. The boundary does not require
Z3 to establish impossibility, and a depot-first baseline could reject it before
enumerating locker sets. Large raw counts are not evidence of inherent hardness.

The optional two-method cross-check is initially collapsed and starts with the
feasible question. It compares answers, not speed. Timings and branch counts
remain in separate, initially collapsed diagnostic details. Agreement supports
implementation consistency, not the real-world validity of the model.

## Implemented contracts

- Frozen real walking graph and aggregate HSY population cells; hypothetical
  candidates, demand, capacities and drone rules.
- Reproducible 24-locker shortlist: at least three walking choices per cell,
  80 m candidate spacing, deterministic tie-breaking. The builder rejects a
  recipe whose checked IDs differ from the replay.
- Six hypothetical depot candidates. Two central candidates have a documented,
  reproducible geometric derivation.
- Browser-local TypeScript/JavaScript and Z3 WebAssembly; no Python, backend,
  API key, remote tiles, analytics or runtime CDN.
- `depotOutageTolerance: 1` creates one explicit contingency per selected depot.
  Collection assignments stay fixed; locker suppliers may rebalance. Range,
  conservation and shared capacity are rechecked in every contingency.
- Independent exhaustive JavaScript implements the same finite decisions using
  lazy site-combination generators. Feasible plans from either engine pass the
  same Z3-free verifier.
- A tiny oracle distinguishes two depots being in range from a survivor having
  enough capacity. It covers SAT, range-UNSAT, capacity-UNSAT and corrupted
  contingency plans.
- Conclusion-copy tests ensure only matching feasible/UNSAT results establish
  agreement. Timeouts, cancellations and errors remain inconclusive even when
  both implementations return the same status.
- `npm run data:audit-complexity` reports 29,418,840 exact site choices, choice
  degrees, deterministic feasible branch profiles and the complete 20-choice
  local proof at the three-depot boundary. It does not allocate every exact
  selection or pin wall-clock time.

## Pinned scenario

- 33 cells, 8,554 published residents, 871 illustrative parcels/day.
- 24 lockers, six depots, 120 eligible walks and 144 return-flight distances.
- Defaults: at most ten used lockers, four used depots, 200 parcels/locker,
  600 parcels/depot, 2,000,000 mm return flight, one depot outage.
- Exact tested game witness: A/B/C/D/E/F/G/J/L/N with
  West/North/East/Central-West.
- At most three depots with one outage: UNSAT.
- At most three depots without the outage rule: feasible.
- At most nine lockers with four depots and one outage: feasible.

## Verification workflow

Run:

```sh
npm run data:audit-candidates
npm run data:audit-complexity
npm run check
npm run test:e2e
```

`npm run check` rebuilds the browser workers. Browser acceptance must use the
built site and inspect desktop/tablet screenshots as well as exit status. The
30-second solver limit yields “no conclusion” on expiry, never UNSAT.

Learning/science refocus verification on September 5, 2026: `npm run check`
passed strict types, byte-identical scenario regeneration, all seven serialized
Node test files and the production build. `npm run data:audit-complexity`
retained the pinned counts and branch profiles. The final `npm run test:e2e`
passed all four Chromium tests, including both feasibility cross-check questions
on desktop and tablet. Opening, answer-only comparison, reflection and methods/
research screenshots were visually reviewed at those viewport sizes. Known
classic-script and chunk-size build warnings remain as documented.

No solver constraints, frozen geography or candidate choices changed in this
refocus. No participant study, recruitment or data collection was performed;
automated tests do not establish learning effectiveness.

Publication-readiness verification on September 5, 2026: `npm run check` and
all four desktop/tablet Chromium tests passed again after adding the public
repository metadata, citation file and MIT licence. The browser tests also
check the canonical share URL and served `LICENSE.txt`; the built licence is
byte-identical to the source licence. Opening desktop/tablet screenshots were
reviewed. These local checks are not a substitute for testing the deployed
Pages site after publication.

Live Pages verification on September 6, 2026: the initial
[publication run](https://github.com/akkauppi/a-plan-that-fits/actions/runs/33982549181)
succeeded for app commit `9c3d618`. A fresh desktop Chromium context on the
public HTTPS URL confirmed project-scoped service-worker isolation, map and
snapshot loading, the served MIT licence, a Z3-selected resilient plan with
independently verified walks and four outage assignments, and the three-depot
UNSAT case. No page errors or off-project runtime requests were observed.
Opening, feasible-result and conflict screenshots were visually reviewed.
This live smoke test supplements the full local/CI desktop and tablet suites;
it does not extend browser-engine certification or establish learning benefits.

Previous resilience checkpoint verification on September 5, 2026:
`npm run check` passed strict types,
byte-identical scenario regeneration, all six serialized Node test files and the
production build. `npm run test:e2e` passed four Chromium tests: full desktop
and tablet journeys plus both unsupported-browser/dialog cases. Desktop and
tablet screenshots for the empty game, backup warning, exact win, three-depot
conflict, resilient result and engine comparison were reviewed. The last
pre-expansion commit is `ee89542`; inspect Git history for the subsequent
resilience checkpoint.

## Safe continuation

Preserve exact-selection semantics, the empty game start, the fixed 500 m rule,
complete eligibility validation, explicit result scope and independent
verification. Do not hand-edit generated scenario/runtime files. Do not claim
real locker suitability, approved flight routes, household accessibility,
optimality, simultaneous-failure resilience or general solver superiority.

Useful next work is a short colleague walkthrough focused on whether users can
explain: what geography supplies, what people assume, what Z3 chooses, why two
in-range depots are insufficient by themselves, and what feasible/UNSAT results
do and do not establish. Prefer one observed comprehension fix over adding
another feature or demo. A formal comparative study needs a defined protocol
and participant-data handling before recruitment or collection.

The owner has explicitly deferred generation from unprepared locations. Do not
add a location picker, live geographic import or a new scenario as a continuation
of this learning/science refocus.
