# Otaniemi resilient-access experiment

- **Foundation date:** 2026-08-30
- **First solver slice:** 2026-08-31
- **Profile:** `finland-resilient-access-v1`
- **Pilot:** Otaniemi coastal core, Espoo
- **Runtime status:** reproducible source, terrain, network, and exposure pipeline;
  Otaniemi-first browser; streaming Z3/NetworkX access solver; bounded custom-location
  base builder

## What exists

The repository has a second, deliberately separate experiment beside the completed
Kallio Four Planters demonstrator. It accepts a strict versioned recipe, uses
source-specific adapters with fixed endpoints, freezes their responses by checksum,
builds a directed multi-mode OSM base network, and intersects that network with the
published Syke 1/100 and 1/1000 coastal-flood zones. A separate adapter freezes the
National Land Survey of Finland (MML/NLS) Elevation Model 2 m window for terrain and
vertical quality review. City of Espoo address and building evidence supplies the
origin aggregation and map context.

The separation is intentional:

```text
versioned recipe
  ├─ OSM archive ─────> directed base-network snapshot
  ├─ MML archive ────> terrain/QC evidence only
  ├─ Syke archives ───> clipped exposure-only overlay
  └─ Espoo archives ──> address representatives + buildings

frozen evidence + explicit stress rule + reviewed graph exits
  ──> unavailable private-car links
  ──> Z3 continuity-zone choices
  ──> NetworkX counterexamples and fresh final verification
```

The source bundle is not a graph, and the exposure overlay is not intrinsically an
availability graph. The new solver loads both only after the user explicitly elects
to treat horizontal exposure as private-car unavailability for a stress test. That
choice supports a scoped graph-access statement, never a flood-safe-route claim.

Implemented contracts and adapters are in `services/scenario_builder/`:

- a Finland-v1 scenario recipe for a simple WGS84 polygon or a point and radius,
  with a bounded metric network-context buffer and `EPSG:3067` analysis;
- offline-by-default OSM, MML elevation, Syke coastal-flood, and Espoo WFS adapters with
  content-addressed raw archives, whose endpoints and layer allowlists cannot be
  replaced by recipe URLs;
- source metadata, field-lineage, licence, checksum, query, CRS, and acquisition
  contracts;
- a strict frozen roadworks GeoJSON interchange with explicit affected modes,
  effect, direction, restriction basis, and fixed or flexible schedule;
- immutable derived snapshots with a checksummed `latest.json` pointer and
  validators that recheck their inputs and contents.

The runtime in `services/solver/otaniemi_resilience.py` adds:

- 15 deterministic 500 m representative origin cells derived from 297 frozen City
  of Espoo address points inside the core;
- four reviewed outbound graph endpoints at Kuusisaarentie, Tapiolantie,
  Kalevalantie, and Kehä I;
- an explicit private-car availability rule combining the selected Syke tier with
  user-declared fixed roadworks;
- visible contiguous exposure zones as Boolean solver decisions;
- streamed Z3 proposals and NetworkX stranded-origin/frontier counterexamples;
- a fresh directed-graph verification before any optimal or infeasible result is
  presented as verified.

The MML adapter uses coverage `korkeusmalli_2m` at the fixed WCS 2.0.1 endpoint
`https://avoin-karttakuva.maanmittauslaitos.fi/ortokuvat-ja-korkeusmallit/wcs/v2`,
requests the native 2 m grid in `EPSG:3067`, and validates the complete ASCII
response before writing a canonical gzip archive. Its API credential is used only
for an explicit refresh and never appears in the query URL, pointer, bundle, browser
response, or committed files. The frozen raster is quality-control evidence only.
It does not replace an official flood-hazard layer or imply road closure,
passability, or safety.

## Location workflow

The browser now opens an **Otaniemi resilient-access** research workspace first,
with the completed Kallio planter solver preserved as the switchable baseline. Its
study-area instrument and a small FastAPI job service expose the first bounded
location workflow. The frozen Otaniemi preset is the default. A user
may instead click an offline coordinate canvas or enter a precise Finland WGS84
longitude/latitude, choose a 500, 750, 1,000, 1,500, or 2,000 m browser radius,
preflight the resulting recipe, inspect local archive readiness and coverage
warnings, start an offline base-network build, follow real event history, and
request cancellation. The underlying API accepts 100–2,500 m. The canvas is a
coordinate picker, not a live basemap or place search, so it makes no background
tile request. A completed job publishes a verified base-network artifact; it does
not switch the active Otaniemi resilience graph or the preserved Kallio graph.

```text
GET  /api/scenario-builder/catalog
POST /api/scenario-builder/preflight
POST /api/scenario-builder/jobs
GET  /api/scenario-builder/jobs/{job_id}
GET  /api/scenario-builder/jobs/{job_id}/events?after=N
POST /api/scenario-builder/jobs/{job_id}/cancel
```

Build requests default to `refresh: false`. A custom location without a matching
frozen OSM archive reaches a distinct `missing_archive` state. Contacting Overpass
requires both `refresh: true` and the literal acknowledgement
`confirm_live_source_refresh: "REFRESH_OSM"`; the endpoint and 750 m context remain
adapter-controlled and bounded. One build may be active at a time. Cancellation is
cooperative at safe checkpoints, so an immutable snapshot can finish publishing
after a late request while still never becoming the active planter scenario.

This v1 browser flow supports the preset and clickable point/radius selection. It
also validates and summarizes the frozen MML elevation source and Otaniemi
flood-exposure artifact. Elevation values are terrain/QC evidence and exposure
numbers are horizontal geometry intersections; neither means passability or a safe
route. Place search, polygon editing, MML/Syke/Espoo acquisition jobs for a new
location, flood derivation jobs, origin/gateway review, and promotion of a built
graph into the resilience runtime remain outside it. In other words, location
selection automates only the bounded base-network stage today, not an end-to-end
new-location solve.

## Pilot geometry

The core polygon is 2.743279 km² and has WGS84 bounding box
`[24.8115, 60.1735, 24.8425, 60.1912]`:

```json
{
  "type": "Polygon",
  "coordinates": [[
    [24.8140, 60.1900],
    [24.8115, 60.1835],
    [24.8150, 60.1760],
    [24.8320, 60.1735],
    [24.8415, 60.1763],
    [24.8425, 60.1870],
    [24.8345, 60.1912],
    [24.8140, 60.1900]
  ]]
}
```

Network and source queries use a separately recorded 750 m context geometry. Its
rounded bounds are:

| CRS | Context bounding box |
| --- | --- |
| WGS84 (`EPSG:4326`) | `[24.7979839, 60.1667697, 24.8560175, 60.1979322]` |
| TM35FIN (`EPSG:3067`) | `[377872.166, 6671958.249, 381103.681, 6675424.132]` |
| Espoo GK25 (`EPSG:3879`) | `[25488789.951, 6672665.056, 25492011.199, 6676136.706]` |

This buffer avoids severing every route at the core boundary. It is not evidence
that a destination outside the core is safe, and it has not yet been sensitivity
tested against the proposed 500 m and 1,000 m alternatives.

## Frozen provenance

The checked-in recipes are:

- `data/recipes/espoo-otaniemi-coastal-base-v1.json` for the independently frozen
  OSM base-network build;
- `data/recipes/espoo-otaniemi-coastal-v1.json` for the combined OSM, Syke, and
  Espoo source declarations;
- `data/recipes/espoo-otaniemi-coastal-elevation-v1.json` for the separately frozen
  MML Elevation Model 2 m selection.

Selection-specific source manifests coexist. The normal hazard/context replay
selects `syke` and `espoo_wfs`; a complete three-source manifest also verifies OSM,
Syke, and Espoo together, so the full recipe replays offline. The independently
derived base network remains tied to the base-only recipe and its earlier OSM
observation; this avoids pretending that a base-only artifact satisfies the full
recipe's required hazard and municipal sources. Capability labels in any source
bundle mean “source archived,” not “derived scenario built.”

The full bundle's OSM response has source timestamp `2026-08-30T16:42:06Z` and the
same 25,390 elements as the base observation after normalizing the response
timestamp. It is preserved as a separate source identity rather than silently
substituted into the checked base snapshot.

| Source | Frozen observation | Contents |
| --- | --- | ---: |
| OpenStreetMap/Overpass | base timestamp `2026-08-30T09:57:36Z`; acquired `2026-08-30T09:59:33.503935Z`; raw identity `88d79a3217333d77…` | 25,390 source elements |
| MML Elevation Model 2 m | acquired `2026-08-30T20:23:48.749054Z`; WCS 2.0.1 coverage `korkeusmalli_2m`; raw identity `ffffffcbda7fcf05…` | 1,616 × 1,734 cells; 2,802,144 valid; 0 NoData |
| Syke 1/100 sea flood | feature `muutospvm` value `2025-11-18`; response `2026-08-30T16:07:06.575Z`; raw identity `ab76b89c567dc131…` | 1,650 features in the buffered query |
| Syke 1/1000 sea flood | feature `muutospvm` value `2025-11-18`; response `2026-08-30T16:07:08.513Z`; raw identity `58be5d12d8ed8388…` | 1,638 features in the buffered query |
| Espoo street centrelines | response `2026-08-30T19:07:12+03:00`; raw identity `34e3b98ed1fd39d3…` | 15,038 features |
| Espoo cycling map | response `2026-08-30T19:07:19+03:00`; raw identity `0c7b1b92dae6768e…` | 14,121 features |
| Espoo buildings | response `2026-08-30T19:07:23+03:00`; raw identity `4bc90a2d5b2ff196…` | 1,189 features |
| Espoo addresses | response `2026-08-30T19:07:25+03:00`; raw identity `a58f5ee649981759…` | 947 features |
| Espoo water areas | response `2026-08-30T19:07:27+03:00`; raw identity `ea40df8425d8549b…` | 72 features |
| Espoo public street areas | response `2026-08-30T19:07:29+03:00`; raw identity `8c50339a55c7bb0c…` | 4,104 features |

The Espoo timestamps are response times, not dataset edition dates. Non-empty WFS
responses also do not prove complete spatial coverage. Both the Syke and Espoo
adapters retain `spatial_coverage: unknown` with the supporting bounded-query
evidence instead of converting “unknown” into “full.”

The MML request bbox is snapped outwards to the native grid as
`[377872, 6671958, 381104, 6675426]` in `EPSG:3067`. The archived values use N2000
(`EPSG:3900`) and range from −2.266 m to 30.116 m. The ASCII grid is stored as a
canonical gzip archive. The acquisition time records this delivery, not the DEM's
dataset edition; the WCS response supplied no source timestamp. Its exact identities
are:

| Item | SHA-256 |
| --- | --- |
| elevation recipe | `57a35e661f305d97a2c924342257bc6c74d75d0df5ef2e58944d8da048939ed2` |
| compressed archive | `d15a1435762cc18a6fe09b03120108066675833e91544ff4140864e79aaa0153` |
| canonical raw ASCII payload | `ffffffcbda7fcf054fb1c051698241c9e4ece4bb8013454e72af1b09119b5fc9` |

Negative values in this source are retained observations, not by themselves errors
or evidence of inundation. The raster has not been sampled onto network edges and
does not participate in the current exposure derivation.

The current compact OSM snapshot is
`base-c8dcbcfaca2b2c9498420681` (base-network schema 1.1, builder 1.3.0): 18,710
nodes, 42,077 directed edges, and 21,526 physical display segments. It explicitly
records walking, cycling, and private-car permissions, one-way assumptions, core and
context boundaries, vertical-separation tags, and source-edge lineage. It does not
model turn restrictions, conditional access, schedules, barriers, emergency,
public-transport, or service-vehicle semantics. Builder 1.3.0 also excludes 949
unreferenced nodes (947 OSM nodes and two derived boundary nodes) and prevents a generic
`access=*` value from promoting an otherwise inappropriate highway/mode pairing.

The loaded browser scenario adds the checked flood and municipal identities to form
`base-c8dcbcfaca2b2c9498420681+flood-bf45a84ac9ce456045f8932b+espoo-0c59d1ca21a9e918b058`.
Runtime loading verifies the declared sizes and SHA-256 hashes of base/flood JSON,
flood display GeoJSON, and the compressed plus raw Espoo address/building GML.
`snapshot_components` exposes those exact identities and binds the representative
origin derivation to the same base graph.

The v1 edge permission is nevertheless Boolean. On an otherwise eligible way,
`access=destination` and `access=delivery` are flattened to “permitted” rather than
retained as route-purpose constraints. That is suitable for preserving possible
local access in this experiment, but not for deciding that unrestricted through
movement is legal or intended. A future routing model must contextualize these tags
for origin/destination access versus through movement before making a through-route
claim.

## Reproduce and validate

All ordinary commands below are offline. They fail if a referenced archive or
checksum is missing rather than silently contacting a service.

```bash
make otaniemi-sources          # verify/replay frozen Syke + Espoo source evidence
make otaniemi-sources-all      # verify the complete OSM + Syke + Espoo bundle
make otaniemi-elevation        # verify/replay frozen MML terrain evidence
make otaniemi-base             # rebuild from the frozen OSM archive
make otaniemi-flood            # intersect the latest verified base with frozen Syke

make otaniemi-base-validate
make otaniemi-flood-validate
```

The four replay/build steps can be run in order with:

```bash
make otaniemi-offline
```

Run the application and complete verification from the repository root with:

```bash
make setup
make otaniemi-offline
make dev                 # API :8000 and Vite :5173

make lint
make test                # Python plus frontend lint/type/unit checks
make build               # strict TypeScript + production Vite build
make test-e2e            # Playwright desktop/tablet browser stories
```

Open <http://127.0.0.1:5173>. Ordinary startup and solving use only the frozen local
artifacts. `make dev` uses API reload for development; the browser never needs the
MML credential. The committed review captures are:

| State | Desktop | Tablet |
| --- | --- | --- |
| Before solve | [desktop](screenshots/four-planters-resilience-before-desktop.png) | [tablet](screenshots/four-planters-resilience-before-tablet.png) |
| Counterexample/refinement | [desktop](screenshots/four-planters-resilience-refinement-desktop.png) | [tablet](screenshots/four-planters-resilience-refinement-tablet.png) |
| Verified result | [desktop](screenshots/four-planters-resilience-verified-desktop.png) | [tablet](screenshots/four-planters-resilience-verified-tablet.png) |
| Constraint workbench | [desktop](screenshots/four-planters-constraint-workbench-desktop.png) | [tablet](screenshots/four-planters-constraint-workbench-tablet.png) |
| Route solver vs Z3 guide | [desktop](screenshots/four-planters-solver-comparison-desktop.png) | [tablet](screenshots/four-planters-solver-comparison-tablet.png) |

The equivalent explicit commands are:

```bash
.venv/bin/python scripts/acquire_scenario_sources.py \
  --recipe data/recipes/espoo-otaniemi-coastal-v1.json \
  --adapter syke --adapter espoo_wfs

.venv/bin/python scripts/acquire_scenario_sources.py \
  --recipe data/recipes/espoo-otaniemi-coastal-elevation-v1.json \
  --adapter mml_elevation

.venv/bin/python scripts/build_base_network.py \
  --recipe data/recipes/espoo-otaniemi-coastal-base-v1.json

base_snapshot="$(.venv/bin/python -c \
  'import json; from pathlib import Path; print(json.loads(Path("data/derived/espoo-otaniemi-coastal-base-v1-base-network/latest.json").read_text())["snapshot_path"])')"
.venv/bin/python scripts/build_flood_exposure.py \
  --base-network "data/derived/espoo-otaniemi-coastal-base-v1-base-network/${base_snapshot}/base-network.json" \
  --syke-pointer data/source/scenario-builder/espoo-otaniemi-coastal-v1/syke/espoo-otaniemi-coastal-v1.syke-coastal-flood.archive.json \
  --output-dir data/derived/espoo-otaniemi-coastal-v1-flood-exposure
```

The source preflight checks adapter configuration, bounds, and local pointer presence
but publishes nothing. Pointer presence is deliberately not archive validation:

```bash
make otaniemi-sources-coverage
```

Network refresh is always explicit and separately scoped:

```bash
make otaniemi-base-refresh       # Overpass only
make otaniemi-sources-refresh    # Syke and Espoo WFS only
make otaniemi-elevation-refresh  # MML WCS only; reads MML_API_KEY from local .env
```

`make otaniemi-elevation` is fully offline and verifies the pointer, recipe identity,
gzip archive checksum, ASCII-grid shape, bbox, resolution, cell counts, and value
range. `make otaniemi-elevation-coverage` validates the bounded request without
publishing anything. To make a deliberate live refresh, copy `.env.example` to the
Git-ignored `.env`, set `MML_API_KEY`, and run
`make otaniemi-elevation-refresh`. The target reads the key only in its child shell,
uses HTTP Basic authentication against the fixed endpoint, and never writes the
credential to source metadata. Do not use the refresh target in startup or routine
offline reproduction.

Refreshes create content-addressed raw archives through adapter-controlled URLs and
atomically advance mutable latest pointers and selection-specific bundle manifests.
Review the new timestamps, checksums, feature counts, licences, and geometry before
accepting them. Raw archive versions remain, but v1 does not preserve every historical
pointer document; after a refresh, an older flood snapshot cannot necessarily be
revalidated without reconstructing its former pointer. Refresh is therefore not part
of normal startup, replay, solving, or validation.

## Flood overlay semantics

The selected 1/100 and 1/1000 values are Syke's published coastal-flood recurrence
scenario labels. In the source documentation, 1/100 corresponds to an estimated 1%
probability in a given year; it does not mean one event occurs regularly every
century, and neither tier is a forecast for a particular date. The solver preserves
the labels rather than converting them into probabilities or expected losses.

The overlay treats Syke `syvsuojluokka_id` values 1–5 as mapped terrestrial depth
bands. It records line/polygon intersection length and share for each physical OSM
segment, the deepest intersecting published band, source feature IDs, and whether
OSM `bridge`, `tunnel`, `layer`, `covered`, or `ford` tags require vertical review.
Published classes for dry land, fixed protection, and waterbody are counted but
excluded from terrestrial exposure; unknown classes are excluded with a warning.

That source output means only:

> The horizontal geometry of this frozen OSM segment intersects this frozen Syke
> hazard polygon under the documented class mapping.

It does not say the road is closed, flooded at carriageway level, traversable by a
particular mode, or part of a safe route. The access experiment therefore requires a
separate, visible user choice before treating exposure as unavailable:

```text
unavailable(edge) := declared_roadworks(edge)
                  OR (stress_rule_enabled AND exposed(edge, selected_return_period))
```

This is a deliberately conservative binary stress rule for explaining network
dependency. It is not a depth threshold or physical passability model. Disabling the
rule removes all flood decision variables and closures from the solve. Declared
roadworks remain fixed unavailable links.

The checked derived snapshot is `flood-bf45a84ac9ce456045f8932b` (builder 1.1.0):

| Return period | Exposed physical segments | Intersecting length | With vertical-review tags |
| --- | ---: | ---: | ---: |
| 1/100 | 892 | 11,265.132 m | 35 |
| 1/1000 | 1,608 | 20,013.350 m | 35 |

The build used 21,526 physical segments and separately records excluded dry-land,
fixed-protection, waterbody, null-boundary, and outside-context source features.
These figures describe the frozen geometric overlay, not flooded road length at
carriageway elevation.

Only some source-exposed segments participate in the private-car graph used by the
experiment:

| Return period | Source-exposed segments | Effective exposed private-car segments |
| --- | ---: | ---: |
| 1/100 | 892 | 241 |
| 1/1000 | 1,608 | 528 |

The browser keeps these concepts separate: blue clipped geometry shows the source
intersection, while dashed unavailable-link styling appears only when the explicit
stress rule or declared works makes a private-car segment unavailable.

## Origins and reviewed network exits

The frozen `GIS:Osoitteet` archive contains 297 City of Espoo address points inside
the study core. For a bounded teaching model, they are grouped by deterministic
500 m `EPSG:3067` grid cell into 15 representative origins, labelled from their
member street names and snapped to permitted private-car nodes. Every representative
lies inside the core; the maximum observed snap distance is 58.48 m. The membership
count and snap distance remain inspectable in the browser.

This aggregation does **not** mean that 297 addresses are individually verified.
It omits occupancy, population, vulnerable-user, entrance, parcel, parking, and
building-specific access semantics. The all-cell preset is an aggregation
sensitivity check, not a household-access certification.

Four exact outbound nodes at the frozen context edge were manually reviewed against
the graph and mapped road names:

| Direction | Label | Frozen graph node |
| --- | --- | --- |
| East | Kuusisaarentie | `osm-boundary-7b941de776af6b9c` |
| South | Tapiolantie | `osm-boundary-c97c13269991761e` |
| West | Kalevalantie | `osm-boundary-3794e75dd2e13051` |
| North | Kehä I | `osm-boundary-bcf840a7014acbf0` |

They are reviewed outbound network endpoints, not shelters or certified safe
destinations. If several are selected, the requirement is disjunctive: each origin
must reach **at least one** selected endpoint.

## Constraint solver and visual refinement

The solver uses one Boolean `passable[decision_group_id]` for each eligible
continuity zone. A zone groups connected exposed OSM fragments with the same
normalized street name; unnamed segments are grouped by OSM way/highway continuity.
Groups are disjoint and map-visible. The primary objective minimizes their count,
the secondary objective minimizes their rounded summed mapped length in metres, and
stable IDs break remaining ties. The budget counts groups, while the result also
reports the exact expanded physical-fragment count. This prevents raw OSM
segmentation from masquerading as dozens of independent decisions, but the grouping
is still an analytical convention rather than an engineering project definition.

The reachability requirement is checked by NetworkX rather than encoded as an
enumeration of all paths in Z3:

1. Z3 proposes a set of `passable[...]` variables under the budget and learned
   clauses.
2. NetworkX applies the fixed availability assumptions and proposed continuity
   zones to the directed graph.
3. For a stranded origin, the browser receives a least-disrupted diagnostic route
   and NetworkX computes the eligible decision zones on the directed reachable
   frontier.
4. That frontier becomes a necessary clause, for example
   `passable[zone_a] OR passable[zone_b]`.
5. Z3 proposes again; the loop ends only when every selected origin reaches at least
   one selected exit or the accumulated constraints are UNSAT.
6. A fresh directed NetworkX graph then reconstructs availability and repeats every
   required reachability check for the final selected zones.

The magenta diagnostic route is visual evidence of why the current proposal fails;
it is not itself the learned constraint. The orange frontier/continuity zones are
the Boolean decision units. Timeout, cancellation, data error, and verified UNSAT
remain distinct terminal states.

The default teaching preset uses the Otaranta representative, East · Kuusisaarentie,
the 1/1000 tier, the explicit stress rule, no works, budget four, and a 30 second
deadline. The frozen deterministic result is:

| Metric | Verified result |
| --- | ---: |
| continuity-zone commitments | 3 |
| expanded OSM physical fragments | 21 |
| aggregation-length cost | 388 m |
| post-stress route detour | +1,093 m |
| graph-verifier findings learned | 3 |

The minimum dependency includes mapped service/driveway links without restrictive
OSM access tags. Their presence is a source-review warning: missing restrictions do
not prove public or legal access. Moreover, each of the three teaching frontiers is
a singleton, so the learned clauses force three successive choices. This makes the
counterexample-guided protocol easy to see but exercises little combinatorial choice;
it does not demonstrate superiority over shortest-path or cut-specific methods.

The **all-cell sensitivity** preset sends all 15 representatives to the east exit.
Under the same frozen 1/1000 rule, budget four is verified UNSAT and five continuity
commitments are required. This difference is valuable precisely because it exposes
origin and gateway sensitivity. It is not evidence that Otaniemi as a whole is or is
not resilient.

## Reusing the solver pattern for other GIS questions

The transferable idea is not “put Z3 on a map.” It is a division of labour:

```text
GIS evidence and policy choices ──> discrete facts and decision candidates
Z3                              ──> globally consistent choice under budgets/rules
domain algorithm                ──> find a concrete violated requirement
counterexample                  ──> compile a necessary clause and repeat
fresh domain check              ──> verify the final scoped claim
```

That pattern becomes useful when several spatial requirements and discrete choices
interact. Examples include:

- scheduling roadworks across time buckets while every critical origin retains one
  or two routes in each enabled hazard scenario;
- selecting temporary evacuation links or facility contingencies under equipment,
  staffing, incompatibility, and per-district coverage constraints;
- choosing habitat-restoration parcels while a graph/raster verifier discovers
  species-specific connectivity gaps;
- coordinating winter-maintenance priorities under fleet, depot, time-window, and
  minimum-service rules;
- placing valves or sectionalising actions in a utility network while hydraulic or
  connectivity checks find customers that remain exposed;
- selecting public-service locations under capacity, equity, jurisdiction, and
  travel-threshold constraints, with shortest-path checks producing uncovered demand
  counterexamples.

The GIS-to-solver translation must always remain inspectable: which source field or
user choice became a fact, which spatial aggregation became one decision, which
requirements are hard, which quantities are objectives, and which external
algorithm verifies them. If a question is only one shortest route or one static
minimum cut, a specialized graph algorithm is usually clearer and faster. Constraint
solving earns its role when decisions are coupled across scenarios, modes, time,
budgets, capacities, and policy rules.

## Roadworks interchange

There is no live Espoo roadworks adapter. The advertised `GIS:Katutapahtumat` layer
was not anonymously readable during the audit and has not been shown to encode
complete closures by mode and direction. Current roadworks support is consequently
a validation and canonicalization contract for a frozen, user-supplied GeoJSON
`FeatureCollection` only.

Each imported work must have a stable ID and source feature IDs, LineString,
MultiLineString, or Polygon geometry, an explicit `closed` or explained `restricted`
effect, affected modes, direction, and a timezone-aware fixed or flexible schedule.
The source declaration must state
`restriction_interpretation: explicit_declared_effects_only`; generic event or
permit inference is prohibited.

The current browser also supports a narrower interactive experiment: clicking a
visible base-network segment marks that exact stable physical ID as a declared fixed
private-car closure for the current solve. Those links are removed before
continuity-zone grouping and can never be selected back by Z3. This provides a real
flood-plus-works availability interaction, but it is not a municipal works import,
geometric conflation, temporal schedule, or operational closure claim. Matching a
frozen imported work to the graph and choosing flexible time windows remain future
work.

## Licences and attribution

- OpenStreetMap data is © OpenStreetMap contributors under ODbL 1.0.
- The frozen Syke material is CC BY 4.0 and requires Finnish Environment Institute
  attribution. Long-term or intensive service use requires a Syke application
  identifier.
- The frozen MML Elevation Model 2 m material is CC BY 4.0 and requires National
  Land Survey of Finland attribution.
- The checked Espoo open-data layers are CC BY 4.0 and require City of Espoo
  attribution plus identification of modifications.

Raw sources remain separately identifiable and checksummed so downstream database
distribution and attribution decisions can be audited. See the
[source audit](otaniemi-source-audit.md) for the service investigation and the
[project roadmap](project-status-and-roadmap.md) for the proof boundary and next
analytical step.

## Next boundary

The first access solve is complete, but it is intentionally a binary,
single-scenario teaching slice. The most valuable next extension is **roadworks
scheduling across time buckets**: freeze one documented works case with explicit
mode/direction closure semantics, match it to graph links with reviewable confidence,
let Z3 choose among genuinely flexible windows, and require each representative to
retain access in every enabled flood/work time combination. That creates meaningful
cross-scenario choices rather than three singleton frontier clauses.

Before any operational claim, the project still needs certified or purpose-reviewed
destinations, mode-specific impedance, road elevation/vertical-separation review,
works-to-edge conflation, capacity and travel-time semantics, and sensitivity to
origin aggregation, context, exits, return period, and availability policy. The
location workflow can preflight and build a bounded base-network snapshot, but does
not yet acquire/derive all evidence or load a custom graph into the resilience
runtime. Terrain height must never be converted directly into a home-made flood
extent.
