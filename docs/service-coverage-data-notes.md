# Experiment 03 evidence: Otaniemi–Tapiola service coverage

This note documents the first frozen evidence slice for the equitable service-coverage
experiment. It is a reproducible analytical demonstrator, not a recommendation to open,
close, staff, or repurpose any named facility.

## Question and proof scope

The experiment asks:

> Which reviewed public-facility sites should host a hypothetical temporary
> neighbourhood-support service, and which published population-grid cell should each
> selected site serve, when site count, connector-inclusive walking distance, and declared analytical
> capacity are constrained?

A verified solution proves only that the encoded assignment satisfies those rules on the
frozen evidence. It does not prove that a facility is available, physically suitable,
accessible to every resident, staffed, funded, legally usable, or capable of serving the
declared number of people.

The first slice deliberately differs from the two connectivity experiments. GIS and
NetworkX compile a finite demand-to-site distance matrix first; Z3 then solves a capacitated
Boolean assignment model directly. Each matrix value is the sum of a demand-point snap
connector, the shortest graph path, and a site-point snap connector. NetworkX independently
recomputes all three components of each chosen route before the application labels a result
verified.

## Frozen study area

Scenario identifier: `service-coverage-otaniemi-tapiola-v1`

Frozen derived snapshot: `coverage-4e7e682613eb7d074b8a3341`.

The polygon covers the Otaniemi peninsula and a Tapiola-side extension containing a useful
mix of residential demand and reviewed municipal venues. Coordinates are longitude,
latitude in EPSG:4326:

```json
[
  [24.8020, 60.1725],
  [24.8020, 60.1840],
  [24.8115, 60.1900],
  [24.8345, 60.1912],
  [24.8425, 60.1870],
  [24.8415, 60.1763],
  [24.8320, 60.1735],
  [24.8140, 60.1720],
  [24.8020, 60.1725]
]
```

Population cells are included when their Shapely representative point lies inside or on
this polygon. Network routes may leave the displayed polygon and use the frozen OSM context
buffer. This avoids creating artificial shortest paths along the study boundary. It also
means the boundary is a demand-selection boundary, not a claim that people cannot walk
outside it.

## Official source evidence

### HSY population grid

- Dataset: *Population grid of Helsinki metropolitan area*, maintained by Helsinki Region
  Environmental Services HSY.
- Layer: `asuminen_ja_maankaytto:Vaestotietoruudukko_2025`.
- Official interface: `https://kartta.hsy.fi/geoserver/wfs`, WFS 1.0.
- Frozen bounded query: `bbox=24.79,60.16,24.86,60.21,EPSG:4326`, with
  `outputFormat=application/json` and `srsName=EPSG:4326`.
- Response timestamp: `2026-09-01T09:18:48.333Z`.
- Source data update field: `2026-08-05Z` in every returned feature.
- Native CRS documented by HSY: ETRS-GK25, EPSG:3879. The archived response was explicitly
  requested as EPSG:4326; metric snapping uses EPSG:3067.
- Licence: Creative Commons Attribution 4.0.
- Frozen response: `data/source/service-coverage/otaniemi-tapiola-v1/hsy/population-grid-2025.geojson`.
- Frozen WFS capabilities: `data/source/service-coverage/otaniemi-tapiola-v1/hsy/wfs-capabilities.xml`.

HSY publishes only cells that meet its privacy rules. The pipeline does not impute omitted
cells or interpret the source's privacy-coded age values. Only the published total population
field `asukkaita` is exported to the solver.

### Helsinki metropolitan area Service Map

- Dataset: *Helsinki metropolitan area Service Map APIs*, maintained by the Helsinki City
  Executive Office / Digitalisation Unit with source municipalities.
- Official API: `https://api.hel.fi/servicemap/v2/unit/{unit_id}/?format=json`.
- Frozen acquisition window: 1 September 2026, approximately 09:46:50–10:10:33 UTC.
- Licence: Creative Commons Attribution 4.0.

Each reviewed candidate is frozen from its exact unit endpoint. Broad service categories
were useful for discovery, but are not treated as evidence that every returned place is a
suitable host. Candidate eligibility is therefore an explicit analyst review and assumption.
The archive preserves each source unit ID, service IDs, displayed owner, data source, and
source `last_modified_time`.

| Unit | Frozen label | Analytical category | Latitude | Longitude |
|---:|---|---|---:|---:|
| 15311 | Tapiola Library | Library | 60.178085 | 24.804646 |
| 15324 | Aarnivalkean koulu | Education | 60.182260 | 24.806044 |
| 15386 | Espoon aikuislukio | Education | 60.173786 | 24.802662 |
| 15415 | Haukilahden lukio | Education | 60.180744 | 24.824846 |
| 15426 | Tapiolan koulu | Education | 60.179350 | 24.803534 |
| 20039 | Tapiolan nuorisotila | Youth centre | 60.176727 | 24.803997 |
| 39431 | Otahalli / Monitoimihalli | Indoor sports | 60.184418 | 24.835045 |
| 60321 | Otaniemi library | Library | 60.184093 | 24.818619 |
| 63347 | Kivimiehen koulu | Education | 60.182520 | 24.831257 |
| 66832 | Tuulimäki Sports hall / air-raid shelter | Indoor sports | 60.173595 | 24.805847 |

The labels and locations describe real source records. The shared hypothetical service and
all capacity values are experiment assumptions, not attributes supplied by Service Map.

### Frozen walking graph

The pipeline reuses OSM snapshot `base-c8dcbcfaca2b2c9498420681` from
`espoo-otaniemi-coastal-base-v1`:

- OSM acquisition: `2026-08-30T09:59:33.503935Z`;
- metric analysis CRS: ETRS-TM35FIN, EPSG:3067;
- display CRS: EPSG:4326;
- source attribution: © OpenStreetMap contributors;
- licence: Open Data Commons Open Database License 1.0.

Only edges carrying the frozen builder's `walking=true` permission are used. The largest
weakly connected walking component is selected deterministically. This model does not yet
encode kerbs, gradients, construction, winter conditions, signal delay, crossing delay,
opening hours, indoor access, or person-specific accessibility.

## Derived evidence and deterministic method

The pipeline performs these steps:

1. Verify every raw archive against its byte length and SHA-256 in
   `source-manifest.json`.
2. Select published HSY cells by representative point within the study polygon.
3. Preserve the HSY grid index as stable ID `hsy-grid-{index}`.
4. Snap demand representative points and Service Map coordinates to the EPSG:3067 walking
   graph.
5. Reject a demand snap above 275 m or a site snap above 175 m. Actual maxima in this
   snapshot are 51.815 m and 42.399 m, respectively.
6. Compute a deterministic NetworkX shortest path for every demand/site pair and record its
   ordered node and edge IDs.
7. Define the assignment distance as `demand connector + graph shortest path + site
   connector`. The two connectors are projected straight-line segments from the source point
   to its nearest graph node. They are a visible analytical approximation, not evidence of an
   entrance, footway, safe crossing, or accessible link.
8. Draw all three components in the stored route geometry and retain each component distance,
   connector method, route-node chain, and route-edge chain for independent audit.
9. Retain the union of all 330 graph-path components as a compact verification graph. Because
   each matrix graph route remains in that subgraph, every compact-graph shortest component is
   identical to its source-graph value to 0.01 m.
10. Export canonical, key-sorted `scenario.json`, `solver.json`, and `browser.json`. Derive the
    snapshot ID from the normalized scenario content after replacing its top-level, solver, and
    browser snapshot IDs with `pending`.
11. Re-read all published documents, require the three payloads to be structurally identical to
    their split files, recompute the normalized fingerprint, and verify every size and SHA-256
    recorded in `metadata.json`. Validation also audits graph contiguity, edge-length sums,
    shortest graph components, snap distances, total arithmetic, route geometry, attribution,
    and capacity provenance.

Current derived counts:

| Evidence | Count |
|---|---:|
| Published population cells | 33 |
| Included published population | 8,554 people |
| Reviewed candidate sites | 10 |
| Demand/site distance records | 330 |
| Compact verification nodes | 3,207 |
| Compact verification directed edges | 4,426 |
| Display walking-network features | 15,315 |

The three `district_id` values are transparent longitude bands used only for reporting in
this slice. They are not official neighbourhoods, statistical districts, or administrative
boundaries, and no district quota is currently a hard solver constraint.

## Declared capacity and default sensitivity

Every candidate has a default capacity of 5,000 people. This is a deliberately declared
assignment bound for the demonstrator. It is not a sourced occupancy, throughput, emergency
shelter capacity, service level, or statement about a building's suitability.

The default request is:

- at most four active sites;
- every one of the 33 cells assigned as an indivisible whole to exactly one active site;
- connector-inclusive walking distance at most 1,600 m;
- capacity multiplier 1.0;
- 30 second timeout;
- lexicographic objectives: active-site count, worst assignment distance,
  population-weighted distance, then selected-site load imbalance.

On the frozen snapshot, the default request returned `verified_optimal`. Runtime depends on
hardware and concurrent load and is not part of the frozen result contract. The result selected
Haukilahden lukio and Tapiolan nuorisotila, assigned all 8,554 included residents, produced loads
of 4,248 and 4,306, a worst route of 1,231.82 m, and a population-weighted mean distance of
757.83 m. Its complete objective vector is `[2, 123182, 648245240, 58]`: site count, worst
centimetres, population-weighted person-centimetres, and selected-site load imbalance. These site
names are a reproducibility observation, not a planning recommendation; another equally optimal
structural assignment may also exist.

Two useful sensitivity checks explain different failure modes:

- **Budget one, 1,600 m, capacity 1.0:** `verified_unsat`.
  One site can accept at most 5,000 of the included 8,554 people. The explanation suggests
  increasing the site budget or the declared capacity multiplier.
- **Distance 1,000 m:** `verified_unsat` with a mapped coverage-gap witness for cells that
  have no reviewed site within the threshold. This is distinct from the capacity core.

Timeout remains indeterminate and is never presented as UNSAT.

## Commands

Rebuild entirely from the committed frozen evidence:

```bash
make service-coverage
```

Validate the committed derived artifact and independently recompute all matrix distances:

```bash
make service-coverage-validate
make service-coverage-test
```

An intentional live refresh is available, but it creates a new evidence snapshot and rewrites
the source checksums. Review and commit that change as a data update, never as an incidental
application start-up action:

```bash
make service-coverage-refresh
```

The browser and API always load the derived frozen snapshot; no official API is contacted on
a browser request.

## Known limitations and next evidence work

- A 250 m cell is indivisible and represented by one point. This can exaggerate or hide
  within-cell walking differences.
- Published totals omit privacy-suppressed cells; 8,554 is included model demand, not a claim
  of complete study-area population.
- Connector-inclusive network length is not walking time and is not a universal-access route
  model. The straight snap connectors are particularly coarse approximations and may cross
  barriers or miss the correct facility entrance.
- Candidate eligibility and capacity are declared assumptions requiring real estate,
  operational, accessibility, safety, and legal review before any practical use.
- All candidates share one capacity in the first slice. A later experiment should expose
  scenario-specific, evidence-reviewed capacities rather than infer them from building size.
- The reporting bands are analytical constructs. A fairness extension should introduce
  defensible population groups or administrative areas and state its normative rule explicitly.
- Robust planning across time-of-day, facility outage, flood, and roadworks scenarios remains
  future work.

Source links and exact archive checksums are in the
[source manifest](../data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json);
derived counts, assumptions, source identities and validation thresholds are in the
[metadata artifact](../data/derived/service-coverage-otaniemi-tapiola-v1/metadata.json).
