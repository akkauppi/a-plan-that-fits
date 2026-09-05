# Geographic data and teaching assumptions

The demo uses a frozen real walking graph and published aggregate population cells around Tapiola–Otaniemi, Espoo. Locker/depot candidates and every operational rule are **hypothetical**. They are not Service Map facilities, business locations, site permissions or drone authorisations.

## What is retained

| File | Role |
| --- | --- |
| `inputs/geography.json.gz` | Canonical normalized walking graph, cell polygons, representative points and snap connectors; input to ordinary Node rebuilds |
| `recipe.json` | Candidate-selection parameters and checked node IDs, inspection locker set and teaching defaults |
| `sources/osm-overpass.json.gz` | Original archived OSM response |
| `sources/population-grid-2025.geojson` | Original HSY response, including cells outside the selected 33 |
| `sources/manifest.json` | Source/licence/query metadata, archive paths and SHA-256 hashes |
| `../public/data/scenario.json` | Generated, committed browser snapshot: complete graph, all eligible walks, all return-flight distances and the walking-only starter |

`npm run data:build` uses the normalized input and recipe, verifies raw-source and input hashes, then regenerates the scenario. `npm run data:validate` independently reruns it and compares the complete output bytes without writing. No network access, Git history or Python is needed for routine builds or checks.

The snapshot identifier hashes the generated content, including provenance and recipe-derived choices. It is not a claim that the data reflects present-day conditions. Current snapshot: `parcel-a31a8c8e18f0a9a8635c6562`.

## Origin and normalization boundary

The import checkpoint is `7f2bdaff04bb20c43c2a44290773e91a49afe4c2` (`archive/geographic-demos-2026-09-05`). The old applications and processing code live there, not in the active runtime.

`npm run data:import` is an explicit one-time migration/recovery command. It uses Node, `git show` and proj4 to re-extract the original full base graph, original selected population cells and raw evidence from that checkpoint. It reproduces the committed normalized input and manifest. It requires history containing that commit; do not add it to ordinary CI or use it as a routine data refresh. Use `data:build` instead.

This slice **does not reimplement raw OSM topology extraction** in JavaScript. The frozen normalized graph is the audited migration boundary; source topology and permission decisions are inherited from the archived builder. Raw source archives remain inspectable, but the current builder does not independently prove that every OSM permission was interpreted correctly. A future raw importer is a separate, reviewed task, not a prerequisite for running this tour.

From base network `base-c8dcbcfaca2b2c9498420681`, the importer retains walking-permitted directed edges and their endpoint nodes: **17,725 nodes and 40,946 directed edges**. It does not use the previous demo's route-union graph; that smaller graph can omit paths needed for the new candidate locations. The full retained graph is shipped so eligibility completeness can be checked before any UNSAT claim.

Source geographic coordinates are longitude/latitude (EPSG:4326). Projected coordinates and edge lengths use ETRS-TM35FIN (EPSG:3067), stored as integer millimetres. Cell representative points and snapped node IDs are inherited; connector distances are recomputed from the rounded geographic representative points via proj4, then rounded to millimetres. This is an explicit precision boundary, not an invisible reuse of old distance floats.

Millimetre storage makes the calculation deterministic; it is not a claim of survey-level positional accuracy.

## Walking, demand and flights

The 33 selected, populated HSY cells retain their published counts (8,554 residents total). Suppressed cells are not imputed as zero or reconstructed. The selected cells are a teaching subset, not a census of the whole map extent and not a statement about unshown residents.

Each 250 m grid cell is represented by one point, connected by a straight segment to its frozen snapped walking node. The connector counts toward **500 m**. Shortest paths use directed walking edges from that node to each candidate locker. There are 120 eligible pairs across the 33 × 24 possible combinations. Eligibility checks must include all pairs, not merely those selected in a result.

Representative points and straight snap connectors do not establish front-door accessibility, accessibility for people with limited mobility, or an obstacle-free connector. Walking permissions and the graph can be incomplete or outdated. “Every cell is covered” means these representative points under this model, not every dwelling.

Daily demand is invented: `ceil(population / 10)` per cell, summing to **871**, not `ceil(8554 / 10)`. It is not an empirical parcel forecast. Each cell's entire demand is assigned together, so this is a deliberately coarser model than individual parcels or households.

Flights use twice the Euclidean distance between projected site coordinates. This is an invented return-range eligibility rule, not a flight route or battery model. It excludes obstacles, altitude, take-off/landing, airspace, weather, reserve energy, payload and scheduling. The map's dashed supply line is a connection diagram, not an approved corridor.

## How the candidate shortlist was selected

The 24 hypothetical locker candidates are **not existing parcel lockers**, a random scatter, or Z3's output. They were generated by this simple geographic procedure:

1. From each of the 33 cell representative points, find every directed walking node reachable within 500 m, including the snap connector. The union contains **13,045 possible nodes**.
2. Count how many shortlisted locker options each cell currently has. Initially all counts are zero.
3. Choose the node that adds an option for the largest number of cells still having fewer than **three**. Skip nodes less than **80 m straight-line distance** from an already shortlisted site.
4. Break ties by the shortest worst walking distance among the cells gaining an option, then by lexicographic node ID. This makes the result repeatable.
5. Repeat until every cell has at least three candidate collection sites. It takes **24 additions**, labelled A–X in selection order.

This is a greedy coverage heuristic: a rule that makes one locally useful addition at a time. It is **not** a globally optimal shortlist or a joint capacity/supply solution. The three-option target creates choices for the lesson, not a requirement that three lockers open. Every cell is later assigned to exactly one locker. The 80 m spacing is purely a candidate-diversity rule; it does not replace the 500 m walking rule.

Replay every addition and compare it to the frozen recipe:

```sh
npm run data:audit-candidates
```

The command prints which node was added, how many cells gained a useful option, how many cells can reach it, and its worst useful walk. [The replay implementation](../tools/candidate-selection.mjs) uses the full frozen graph. Its output exactly matches `recipe.json`; a regression test protects that match. The command does **not** rewrite the shortlist or the scenario. The explicit recipe IDs remain canonical.

Four depot candidates sit around the demand area. Central-West and Central-East are the nearest network nodes to points 300 m west and east of the demand-cell bounding-box centre; the checked derivation is recorded in [`expanded-scenario.md`](../docs/expanded-scenario.md). The prepared eight-locker subset exists only for route inspection. Depot candidates and the prepared subset are not outputs of Z3. Inspection assignments are built deterministically as documented in [the model contract](../docs/model.md).

No candidate location has been checked for ownership, usable space, safe landing access or construction feasibility. These are teaching choices, not observed infrastructure. Other candidate sets may have different feasibility thresholds; Z3 only proves claims within the supplied set.

## Attribution and licences

- Walking graph and archived source: **© OpenStreetMap contributors**, [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/). See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright). OSM source timestamp: 2026-08-30 09:57:36 UTC. The normalized graph and its derived route database retain this attribution and ODbL terms. The machine-readable graph is included in the downloadable scenario.
- Population grid of Helsinki metropolitan area: **Helsinki Region Environmental Services HSY**, 2025 edition, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [Dataset landing page](https://hri.fi/data/en/dataset/vaestotietoruudukko). Archived September 1, 2026; source update timestamp recorded as 2026-08-05. Changes here: selected 33 cells, representative-point snapping/reprojection, and explicitly invented derived parcel counts.

The source manifest records endpoints, queries, timestamps and hashes. Reused inputs are public aggregate geographic data, not person-level data. Retired flood, elevation, address, facility and unrelated demonstration datasets are not needed by this slice and remain in Git history.

The project's own code and documentation are licensed under [MIT](../LICENSE).
That licence does not replace the ODbL and CC BY terms of the geographic data,
including the data in the generated browser snapshot. Third-party software
retains its own licences. Dependency notices are generated into
`public/third-party-notices.txt` during the runtime build and shipped with the
static site alongside `LICENSE.txt` for the project code. Archived datasets
retain the attributions and terms recorded with them in Git history.
