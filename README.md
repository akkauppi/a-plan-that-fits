# A plan that fits

A hands-on introduction to **constraint solving on a real map**. One self-guided browser tour, designed for colleagues who do not write code.

A constraint is a rule a plan must meet. A constraint solver searches for choices that satisfy all the rules together—and can prove that none work within the model. This tour uses **Z3**, a general-purpose solver, to explore that idea in a geographic context. See [an introduction to constraint solving](https://developers.google.com/optimization/cp) and [Microsoft Research's description of Z3](https://www.microsoft.com/en-us/research/project/z3-3/).

**Can this neighbourhood keep delivering?** People need a short walk to a parcel locker. Drones need a supply network that still works when one depot is unavailable. Can we choose the locations so every rule is met?

A coverage map is only the beginning. The locker locations, parcel assignments, supply depots, capacities and drone connections must work together on a normal day and after each possible depot outage. Z3 chooses and checks those coupled decisions jointly.

This is a first vertical slice, not an operational urban-planning or drone product. It uses real paths and published population cells around Tapiola–Otaniemi in Espoo, with explicitly hypothetical sites and operating rules. It does not claim Z3 is the only suitable solver.

## Run the tour

Use Node.js 24.15.0 (see [.nvmrc](.nvmrc); minimum 22.18 for native TypeScript stripping).

```sh
npm ci
npm run dev
```

Open the localhost URL printed by Vite. The first visit may reload once to enable browser isolation. Z3's WebAssembly download is about 34 MB. No Python, API server, account, map key or external tile service is used.

For a production build:

```sh
npm run build
npm run preview
```

Serve over HTTPS or localhost; double-clicking `index.html` with `file://` will not work. This slice is browser-local, **not an offline-installed application**. See [development and hosting](docs/development.md) for GitHub Pages and browser requirements. Nothing is published automatically.

## What the tour teaches

1. **The question:** residents walk to lockers; drones supply them from depots.
2. **Play the planning puzzle:** start with no selected sites, choose among 24 locker candidates and submit exactly ten lockers and four depots. Coral rings mark candidates that lack two selected depots within the exact 2 km return-flight range. Quick map checks expose geographic gaps; Z3 checks hidden assignments and shared capacity in normal operation and four outage cases.
3. **Add resilience:** ask whether three depots could survive one outage. Across all 20 depot choices, robust lockers cover at most 27 of 33 cells, so Z3 proves the full question impossible.
4. **Let Z3 choose:** restore four depots and choose all locations and assignments together. The comparison defaults to proving the three-depot boundary impossible; an optional feasible run demonstrates that brute force can find an early lucky branch faster.
5. **Explore:** remove the outage rule, restore the fourth depot, or test a nine-locker budget.

The walking limit remains **500 m throughout**. All feasible answers are checked again by separate JavaScript code. A timeout, cancellation or error is never presented as an impossibility proof. The result is feasible, not necessarily optimal.

The geography contains 33 population cells, 8,554 published residents, 24 hypothetical locker candidates and six hypothetical depots. Illustrative demand is one parcel per ten residents, rounded up separately in each cell: 871 parcels/day. A representative point stands for each cell; this is not a household-level accessibility guarantee.

The candidate shortlist is generated from walking geography, not selected by Z3: a simple coverage procedure adds sites at least 80 m apart until every cell has three options within 500 m. The tour explains this under “Where did the candidate sites come from?”. `npm run data:audit-candidates` replays the procedure and reproduces the same 24 sites without changing data. See [the exact method](data/README.md#how-the-candidate-shortlist-was-selected).

`npm run data:audit-complexity` measures the difference between the 29,418,840 exact site combinations and effective difficulty. It reports choice degrees, deterministic exhaustive branch profiles and the complete 20-choice geographic proof that three depots cannot survive an outage. It deliberately excludes unstable elapsed-time assertions and does not attempt to hold all exact site combinations in memory.

Step 1 is inspection-only: explore population cells and collection journeys in a prepared example. Step 2 starts empty; map markers and equivalent labelled buttons toggle both locker and depot choices. Backup-reach highlighting is derived from the same frozen flight table and exact return-distance limit used by the model; it is not an approximate radius. At least one exact ten-locker/four-depot resilient solution is tested. “Let Z3 find a plan” provides an escape hatch.

## Verify or continue development

```sh
npm run check
npm run data:audit-complexity
npx playwright install chromium
npm run test:e2e
```

`check` covers types, frozen-data reproducibility, real Z3 tests, an exhaustive small-instance oracle, and the production build. Browser tests exercise the built site under `/tour/` without server-provided isolation headers.

Start with [the agent handoff](docs/agent-handoff.md) and [AGENTS.md](AGENTS.md). They specify what is implemented, the invariants that must not change, and bounded next tasks.

- [Model contract and teaching cases](docs/model.md)
- [Development, tests and static hosting](docs/development.md)
- [Data provenance, assumptions and licences](data/README.md)

## Earlier experiments

The previous branding, demonstrations and Python applications are retired from the active tree. They remain in Git at commit `7f2bdaff04bb20c43c2a44290773e91a49afe4c2`, tagged `archive/geographic-demos-2026-09-05`. That checkpoint includes the work present before this slice. Restore material in a separate branch or worktree if needed; do not reintroduce a demo catalogue into this tour.
