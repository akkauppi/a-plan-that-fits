# Contributing

This project explores how people understand planning constraints and solver
feedback. A clearer explanation or a well-observed comprehension problem is
more valuable here than another unrelated demo.

## Feedback from the tour

Open a [GitHub issue](https://github.com/akkauppi/a-plan-that-fits/issues) with
the chapter, what you expected, what happened and what was difficult to explain.
For calculation issues, include the selected sites, rule values, result status
and snapshot ID from **How it works**. Browser/version and a screenshot help
with interface problems. Do not include private addresses, credentials or
participant information in public reports.

## Code and documentation changes

1. Read [README.md](README.md), [AGENTS.md](AGENTS.md), the
   [model contract](docs/model.md) and [handoff](docs/agent-handoff.md).
2. Choose one bounded change and its acceptance test. Preserve the empty game
   start, the 500 m walking rule, exact-selection semantics and independent
   verification. Do not silently change geographic inputs or teaching rules.
3. Use Node 24.15.0 and the committed lockfile. Run `npm ci`, then
   `npm run check`. For interface, worker or hosting changes, also run
   `npx playwright install chromium` and `npm run test:e2e` after building.
4. Review desktop and tablet captures. State what was tested, what changed and
   any remaining limitations. Keep the relevant documentation consistent.

Generated geography and browser runtime files must be rebuilt using the
documented tools, not hand-edited. See [development](docs/development.md) and
[data provenance](data/README.md).

## Scientific scope

Keep assumptions, implementation evidence and proposed research distinct.
The prototype has no demonstrated learning effect or general solver speed
advantage. A feasible result is not an optimal or operationally validated plan.
An impossibility claim is limited to its candidate set and rules.

[Research framing](docs/research-framing.md) describes a proposed evaluation.
Participant recruitment, consent and data handling require a separate agreed
protocol. Do not add analytics or collect responses as an incidental feature.
Generation from unprepared locations is currently deferred.

Code and documentation contributions use the project's [MIT licence](LICENSE).
Retain source attribution and separate data/dependency licences. Opening or
merging a change does not automatically publish the demo: Pages deployment is
an explicit maintainer action described in the development guide.
