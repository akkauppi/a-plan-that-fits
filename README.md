# A plan that fits

A hands-on introduction to **constraint solving on a real map**. One self-guided browser tour, designed for colleagues who do not write code.

A constraint is a rule a plan must meet. A constraint solver searches for choices that satisfy all the rules together—and can prove that none work within the model. This tour uses **Z3**, a general-purpose solver, to explore that idea in a geographic context. See [an introduction to constraint solving](https://developers.google.com/optimization/cp) and [Microsoft Research's description of Z3](https://www.microsoft.com/en-us/research/project/z3-3/).

**Can this neighbourhood deliver?** People need a short walk to a parcel locker. Drones need a workable supply network. Can we choose the locations so every rule is met?

A coverage map is only the beginning. The locker locations, parcel assignments, supply depots, capacities and drone connections must work together. The tour starts with a collection plan that looks reasonable but cannot be supplied from two depots. Z3 can find a working network when it chooses the lockers and depots jointly.

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
2. **Play the planning puzzle:** start with no selected sites, choose among 15 locker candidates and submit exactly eight lockers and two depots. Lockers and depots toggle directly on the map or with equivalent labelled buttons. Once a depot is selected, coral rings mark every candidate outside all selected depots’ exact 2 km return-flight range. Quick map checks expose simple gaps; Z3 checks the hidden assignments and shared capacities.
3. **Reveal the conflict:** that locker layout needs at least three depots under the flight rule.
4. **Let Z3 choose:** keep the rules, but choose all locations and assignments together. Then send the identical request to a transparent exhaustive JavaScript solver and compare one warm run without claiming a universal speed benchmark.
5. **Explore:** add a depot, extend drone range, or test whether seven lockers suffice.

The walking limit remains **500 m throughout**. All feasible answers are checked again by separate JavaScript code. A timeout, cancellation or error is never presented as an impossibility proof. The result is feasible, not necessarily optimal.

The geography contains 33 population cells, 8,554 published residents, 15 hypothetical locker candidates and four hypothetical depots. Illustrative demand is one parcel per ten residents, rounded up separately in each cell: 871 parcels/day. A representative point stands for each cell; this is not a household-level accessibility guarantee.

The candidate shortlist is generated from walking geography, not selected by Z3: a simple coverage procedure adds sites at least 80 m apart until every cell has two options within 500 m. The tour explains this under “Where did the candidate sites come from?”. `npm run data:audit-candidates` replays the procedure and reproduces the same 15 sites, without changing data. See [the exact method](data/README.md#how-the-candidate-shortlist-was-selected).

`npm run data:audit-complexity` measures the difference between the headline search space and effective difficulty. It deterministically reports choice degrees, raw exact site combinations, selections that pass the visible checks, full feasible/impossible counts and brute-force branches for representative feasible and impossible questions. It deliberately excludes unstable elapsed-time assertions.

Step 1 is inspection-only: explore population cells and their collection journeys in a prepared eight-locker example. Step 2 starts empty; map markers and equivalent labelled buttons toggle both locker and depot choices. Depot-reach highlighting is derived from the same frozen flight table and exact return-distance limit used by the model; it is not an approximate radius drawn around a depot. At least one eight-locker/two-depot solution exists. “Let Z3 find a plan” provides an escape hatch and a direct comparison with the player’s choices.

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
