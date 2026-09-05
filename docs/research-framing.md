# Research framing and proposed learning evaluation

[Open the prototype](https://akkauppi.github.io/a-plan-that-fits/) ·
[Source repository](https://github.com/akkauppi/a-plan-that-fits) ·
[Model contract](model.md)

## Purpose and current evidence

**Research question:** can a map-based planning game, with constraint-solver
feedback, help nontechnical users understand interacting planning requirements
and the scope of a solver's answers?

This repository contains an exploratory prototype, not a completed participant
study. There is no measured learning effect, usability result, demonstrated
transfer to professional planning, or claim of algorithmic novelty. No Aalto
endorsement or research-study approval is implied. The current app collects no
participant responses or analytics.

What is implemented and testable:

- A browser-local game using real walking geography and aggregate population
  cells, with documented hypothetical locations and operating rules.
- A fixed 500 m walking limit, whole-cell demand assignments, shared capacities
  and supply reassignment after any one selected depot is unavailable.
- A solver model, an independent exhaustive implementation, a separate feasible
  plan checker, small-instance oracle tests and reproducible geographic inputs.
- Predict/check/explain prompts, inspectable answers and explicit distinctions
  between feasible, impossible within the model, and no conclusion.

These are implementation and reproducibility properties. They do not establish
that people learn from the interface, that the source data is complete, or that
the hypothetical model describes an operational service.

When reporting an observation, record the Git commit, geographic snapshot,
selected sites and rule values. [CITATION.cff](../CITATION.cff) identifies the
software; it is not a citation for a completed learning study. The frozen
snapshot and build procedure are described in [data provenance](../data/README.md).

## Claims the interface should help users examine

1. **A nearby connection is a necessary condition, not a complete plan.**
   Shared capacities and assignments must fit simultaneously. Two in-range
   depots alone do not prove a capacity-feasible outage reassignment.
2. **The model separates inputs, assumptions and decisions.** Walking geography
   defines allowed collection links. People set demand assumptions, budgets,
   capacities and the outage requirement. The solver checks their consequences;
   it does not decide which planning values a community should adopt.
3. **Feasible means at least one assignment works under the rules.** It does not
   mean cheapest, fairest, uniquely best, buildable or operationally validated.
4. **Impossible has a scope.** A proof concerns this candidate set and these
   rules. A timeout or error is no conclusion. Different candidate sites or
   assumptions can change the answer.
5. **Solver feedback needs interpretation.** Named conflicting rule groups need
   not be minimal, understandable without explanation, or a recommended repair.

The simple three-depot geographic explanation is part of the learning material.
All 20 depot triples fail local resilient coverage (best: 27 of 33 cells), even
before capacity is tested. General-purpose constraint solving is one way to
check the full model; it is not necessary to discover this particular proof.

## Proposed evaluation — not yet conducted

Start with a short observed colleague walkthrough. Ask participants to explain
their reasoning aloud and identify one concrete comprehension problem to fix.
This is formative feedback, not a causal estimate of learning effectiveness.

For a subsequent comparative study:

- Define the learning outcomes and scoring rubric before collecting results.
  Assess local versus joint feasibility, model assumptions, answer scope and
  interpretation of an unfamiliar rule change.
- Compare a map-and-explanation condition with the game plus solver feedback,
  holding the case, factual content and exposure time as comparable as possible.
  Randomise allocation or counterbalance order to address practice effects.
- Use a short baseline assessment, then an unfamiliar case or question after
  the tour. Score explanations as well as correct choices. Confidence and task
  time can supplement comprehension measures; winning the game alone is not
  a learning measure.
- Include cases where local coverage passes but capacity fails, plus feasible,
  impossible and inconclusive answers. Avoid relying entirely on the current
  three-depot case, whose explanation is already supplied by the tour.
- Report recruitment, prior GIS/solver knowledge, sample size, exposure,
  uncertainty and limitations. A small colleague sample supports a pilot,
  not generalisation to all planners.

Participant recruitment, consent, data handling and any applicable study review
must be settled before collection. They are not implemented by this app change.
Do not add tracking as an incidental continuation task.

## Optional implementation diagnostics

The main tour concerns understanding, not a race between algorithms. The
optional cross-check asks whether two implementations answer the same question
consistently. Both use the same request and feasible-plan verifier. Matching
inconclusive states do not establish agreement.

The audit reports 29,418,840 raw exact site choices, while the default exhaustive
search finds a feasible answer after 240 locker sets. A depot-first screen can
establish the three-depot boundary by checking 20 triples. Search order and
pruning therefore matter; raw combinations and one timing pair cannot establish
inherent difficulty or solver superiority. Retain observations where custom
search is faster, as well as those where Z3 is faster.

The browser's optional timings exclude startup and include validation, model
construction/search and feasible-plan checking. A computational study would
require multiple cases, stronger baselines, controlled repeated measurements
and an explicit account of preprocessing. It is separate from the proposed
learning evaluation.

## Selected related research

These are foundations and neighbouring applications, not studies of this app.

- de Moura & Bjørner (2008), [Z3: An Efficient SMT Solver](https://www.microsoft.com/en-us/research/publication/z3-an-efficient-smt-solver/).
  The technical foundation for combining logical choices with arithmetic.
- Deutsch & Golany (2018), [A parcel locker network as a solution to the logistics last mile problem](https://doi.org/10.1080/00207543.2017.1395490).
  Locker-network design using integer programming; a direct application
  precedent, with a different objective and model.
- Snyder & Daskin (2005), [Reliability Models for Facility Location: The Expected Failure Cost Case](https://pubsonline.informs.org/doi/10.1287/trsc.1040.0107).
  Facility location accounting for disruption costs. It studies expected costs,
  rather than this prototype's requirement to survive every single-depot outage.
- Hong, Kuby & Murray (2018), [A range-restricted recharging station coverage model for drone delivery service planning](https://doi.org/10.1016/j.trc.2018.02.017).
  Range-limited drone infrastructure and obstacle-aware routes; a more
  operational geographic modelling context.
- Brown & Kyttä (2014), [Key issues and research priorities for public participation GIS (PPGIS): A synthesis based on empirical research](https://doi.org/10.1016/j.apgeog.2013.11.004).
  Participation, spatial-data quality and evaluation of planning-support
  effectiveness. Relevant to framing the human-facing research question;
  it does not evaluate solver games.
