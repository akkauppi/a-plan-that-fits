# Expanded resilient scenario — implemented design record

This document records the design and evidence behind the expanded demo. Run
`npm run data:explore-expansion` to reproduce every geographic count below. The
command is read-only: it does not change the recipe or generated scenario.

## Why expand the scene

The previous baseline had 15 locker candidates, four depot candidates and 38,610
exact site selections. It is useful for explaining interacting constraints, but
still small enough to invite trial and error. The proposed scene has 24 locker
candidates, six depot candidates, a ten-locker budget and a four-depot budget:
29,418,840 exact site selections before parcel assignments or supply choices.

This is a record of the expansion's motivation, not evidence of computational
hardness. The subsequent audit finds the default feasible answer after 240
locker sets, and the three-depot impossibility follows from 20 local coverage
checks. The current tour focuses on understanding these constraints; timing
and raw search counts are optional diagnostics, not its research contribution.

The added rule gives the complexity a visible planning purpose:

> The network must keep working when any one selected depot is unavailable.

That means every selected locker must have an eligible selected supplier in
each single-depot-outage case. Assignment and depot-capacity constraints must
also hold separately in every case; merely counting two nearby depots is only a
necessary geographic check.

## How candidates are derived

Locker candidates use the existing documented greedy geography-only method,
still with 500 m maximum walking distance and 80 m minimum spacing. The only
change is requiring at least three candidate choices per population cell rather
than two. On the frozen network this produces exactly 24 candidates. It is not
a claim that these are approved or optimal real sites.

The four existing edge depots remain. Two additional candidates are the nearest
walking-network nodes to points 300 m west and east of the demand-cell bounding
box centre. This deterministic construction produces `osm-node-8209555651` and
`osm-node-12728836257`. They are hypothetical launch points, not real facilities
or flight approvals.

## Why the budget is four depots

The 2 km return-flight limit remains unchanged. If only three depots are
selected, surviving one outage requires each chosen locker to be in range of at
least two of those three. Across all 20 three-depot choices, those robust locker
candidates cover at most 27 of 33 population cells. The scenario is therefore
geographically impossible before capacity is considered.

With four selected depots, three of the 15 depot choices have a locally valid
locker cover using at most ten lockers. The full model is also proven feasible:
both engines and the verifier protect an exact ten-locker/four-depot witness,
including all capacity-aware contingency assignments.

## Safe implementation sequence

1. **Implemented:** explicit `depotOutageTolerance: 1` request semantics and
   one returned contingency plan per selected depot.
2. **Implemented:** per-outage locker supply decisions and depot loads in Z3;
   a plan may rebalance after a depot outage.
3. **Implemented:** the same mathematical problem in the independent exhaustive
   JavaScript solver, including deterministic branch counters.
4. **Implemented:** independent verification of flight eligibility, complete
   supply, conservation and capacity for every outage case.
5. **Implemented:** a tiny oracle distinguishing “two depots are in range” from
   “every outage has a capacity-feasible reassignment.”
6. **Implemented:** `data/recipe.json`, the generated scenario, story, game
   budgets and browser acceptance were migrated together.

Do not manually edit `public/data/scenario.json`. Future changes must continue
to pass both solvers and the independent contingency verifier.
