# Resilient solver tour: continuation handoff

Read [AGENTS.md](../AGENTS.md), [model.md](model.md),
[expanded-scenario.md](expanded-scenario.md) and [development.md](development.md)
before changing behaviour. This repository intentionally contains one
self-guided browser demonstration of constraint solving in geography.

## Product story

The title is **A plan that fits** and the hero is **Can this neighbourhood keep
delivering?** Nontechnical users choose hypothetical drone-supplied parcel
lockers and depots on a real walking map. Every population-cell representative
point must have a directed walk of at most 500 m. The network must fit whole-cell
parcel demand, locker and shared depot capacities, a 2 km return-flight range,
and a complete supply reassignment after any one selected depot is unavailable.

The game starts with no selected sites and asks for exactly ten lockers and four
depots from 24 and six candidates. Map checks show walking coverage and whether
each locker has two selected depots in range. They are necessary conditions,
not a feasibility claim. Z3 checks hidden collection, normal supply and four
outage assignments. “Let Z3 find a plan” remains available.

The core teaching boundary is now meaningful: four depots are feasible, while
three are UNSAT. Across all 20 three-depot choices, robust lockers cover at most
27 of 33 cells. In a local Node profile, Z3 proved this much faster than the
independent enumeration, which inspected millions of sets; browser timings are
illustrative and never a universal benchmark claim.

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

Verification on September 5, 2026: `npm run check` passed strict types,
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

Useful next work after the migration is verified is a short colleague
walkthrough focused on whether users can explain: what geography supplies, what
Z3 chooses, why two in-range depots are insufficient by themselves, and what
SAT/UNSAT do and do not establish. Prefer one observed comprehension fix over
adding another feature or demo.
