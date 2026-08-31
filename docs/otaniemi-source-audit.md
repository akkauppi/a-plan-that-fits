# Otaniemi resilient-access source audit

- **Audit date:** 2026-08-30
- **Decision:** proceed with a bounded source prototype
- **Candidate area:** Otaniemi campus, adjoining shoreline, and the
  Otaniemi–Keilaniemi/Tapiola transition, Espoo
- **Status:** audit followed by a frozen source/base/exposure foundation; still not a
  flood-safe access claim

## Recommendation

Use the polygon below as the first **analysis core** for the resilient-access
successor. It is small enough for rapid graph iteration, but it contains measurable
coastal-flood exposure and extends north and east into less exposed network context.
Do not use its boundary as a proxy for safety. Build routes in a buffered context
graph and require explicitly selected destinations.

The source audit supports a first flood-reachability experiment. It does not yet
support a live municipal-roadworks experiment: no complete, openly accessible feed
with closure geometry, time windows, and affected modes has been confirmed.

## Implementation update

The bounded prototype recommended by this audit was implemented later on the same
date. Versioned recipes now freeze the polygon and a distinct 750 m context; real
OSM, MML, Syke, and Espoo observations are archived with checksums; the OSM network,
MML terrain window, and Syke segment-exposure overlay are reproducible offline. The
browser now opens this Otaniemi research workspace before the preserved Kallio
planter baseline. See the
[foundation architecture and provenance](resilient-access-foundation.md) for the
actual schemas, commands, snapshot identities, feature counts, and proof boundary.

The original audit observations below are retained because they explain why those
sources and semantics were chosen. They should not be read as the latest
implementation status where the linked foundation records a completed item.

## Proposed analysis polygon

The exterior ring is counter-clockwise and uses WGS84 longitude/latitude
(`EPSG:4326`):

```json
{
  "type": "Feature",
  "properties": {
    "id": "otaniemi-coastal-pilot-v0",
    "name": "Otaniemi coastal resilient-access pilot",
    "purpose": "analysis core, not a safety or flood-risk boundary"
  },
  "geometry": {
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
}
```

| Measure | Value |
| --- | ---: |
| Metric analysis CRS | ETRS89 / TM35FIN (`EPSG:3067`) |
| Projected area | 2.743279 km² |
| WGS84 bounding box | `24.8115,60.1735,24.8425,60.1912` |
| `EPSG:3067` bounding box | `378622.10,6672708.24,380353.73,6674674.24` |
| `EPSG:3879` query bounding box | `25489540.01,6673414.97,25491261.15,6675386.67` |

The polygon includes approximately 0.434 km² classified as open water by the
sampled Syke sea-flood layers, leaving approximately 2.309 km² of terrestrial core.
That water is intentional: it preserves the shoreline relationship and makes
clipping errors visible. The northern and eastern vertices include the principal
inland-facing approaches; the southern part includes the campus-to-Keilaniemi
transition. The western edge follows the peninsula rather than pretending that
Laajalahti is a road-network exit.

For the first build, acquire the routable network with a 750 m buffer around the
core, select origins only inside the core, and test the result again with 500 m and
1,000 m buffers. This is a starting sensitivity test, not a universal buffer rule.

## What was checked

The audit queried official service capabilities on 2026-08-30. Syke features were
downloaded for the projected bounding box and intersected locally with the exact
polygon. Espoo counts below are server-reported **core-bbox audit counts**, not the
larger frozen 750 m-context snapshot counts; they were not clipped to the polygon or
topologically simplified. The subsequent build did commit bounded, checksummed raw
responses with timestamps, parameters, CRS, and licences as documented in the
foundation guide.

### Coverage summary

| Source | Exact-area result | Access and terms | Decision |
| --- | --- | --- | --- |
| MML Elevation Model 2 m | The original service audit established product coverage; the subsequent adapter run froze the exact 750 m-context window: 1,616 × 1,734 native 2 m cells, all 2,802,144 valid. | Open CC BY 4.0 data; live WCS access requires a user API key, while the frozen archive replays offline without it. | Implemented terrain and quality-control adapter. Never derive the canonical flood extent, road closure, or route safety from elevation alone. |
| MML Topographic Database | National product includes roads, buildings, waterways, and terrain; custom-area downloads are supported. Exact Otaniemi features were **not** queried without an API key. | Open CC BY 4.0; programmatic current-data services require an API key. | Optional national comparison/fallback source, not an automatic replacement for OSM or municipal geometry. |
| Espoo open WFS | Anonymous responses contain dense street/cycling geometry, buildings, addresses, water, and public street areas for the proposed bbox. | The checked catalogue records are CC BY 4.0. WFS layers and update rhythms are published by the city. | Confirmed municipal enrichment and cross-check source. Keep field-level provenance. |
| Syke sea-flood hazards | Exact polygon intersects every checked basic coastal-flood recurrence layer and its published flooded-road layers. | Open CC BY 4.0. Long-term or intensive application use requires a Syke application identifier. | Canonical hazard source for the prototype. |
| Espoo operational roadworks | No usable open feed confirmed. A capability-only layer is not anonymously readable and lacks proven mode-closure semantics. | Unknown for operational reuse. Human-facing project pages are not a complete closure feed. | Use an explicitly user-supplied, frozen works file until access and semantics are confirmed. |

## National Land Survey of Finland (MML/NLS)

### Confirmed

The official [Elevation Model 2 m product
description](https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/elevation-model-2-m)
defines a 2 m ground-surface raster in `EPSG:3067` with N2000 heights
(`EPSG:3900`). It is open data under CC BY 4.0. Quality class I has average vertical
accuracy of 0.3 m; class II varies from 0.3 m to 1 m. The product page describes
coverage across Finland with limited exceptions in parts of the outer archipelago
and eastern border. Otaniemi is not close to those stated exceptions.

The [Topographic Database product
description](https://www.maanmittauslaitos.fi/en/maps-and-spatial-data/datasets-and-interfaces/product-descriptions/topographic-database)
confirms national roads, buildings, waterways, land use, and related features in
`EPSG:3067`, also under CC BY 4.0. The [GeoPackage distribution
description](https://www.maanmittauslaitos.fi/en/geopackage) supports municipal and
custom-area downloads and documents stable `mtk_id` identifiers in GeoPackage.

The [OGC API Processes file-service
description](https://www.maanmittauslaitos.fi/paikkatiedon-tiedostopalvelu) lists
both Elevation Model 2 m and the Topographic Database and accepts bbox or polygon
requests. The service is free, but identifies users with an API key. MML's [API-key
instructions](https://www.maanmittauslaitos.fi/en/rajapinnat/api-avaimen-ohje)
explicitly include the orthophoto/elevation WCS, Topographic Database OGC API
Features, and OGC API Processes services.

### Implemented elevation observation

The dedicated recipe
`data/recipes/espoo-otaniemi-coastal-elevation-v1.json` now drives a fixed-endpoint
WCS 2.0.1 adapter for coverage `korkeusmalli_2m`. It snapped the context request
outwards to bbox `[377872, 6671958, 381104, 6675426]` in `EPSG:3067` and acquired
the response at `2026-08-30T20:23:48.749054Z`. The validated grid has 1,616 columns,
1,734 rows, 2 m resolution, 2,802,144 valid cells, and no NoData cells. Its N2000
(`EPSG:3900`) values range from −2.266 m to 30.116 m.

The response is retained as a canonical ASCII grid gzip archive. Reproducibility
identities are listed below. The acquisition time is the archived delivery time, not
a dataset-edition date; the response supplied no separate source timestamp.

| Item | SHA-256 |
| --- | --- |
| recipe | `57a35e661f305d97a2c924342257bc6c74d75d0df5ef2e58944d8da048939ed2` |
| compressed archive | `d15a1435762cc18a6fe09b03120108066675833e91544ff4140864e79aaa0153` |
| canonical raw ASCII | `ffffffcbda7fcf054fb1c051698241c9e4ece4bb8013454e72af1b09119b5fc9` |

The live-refresh target reads `MML_API_KEY` only from a local Git-ignored `.env`,
uses it as the HTTP Basic username, and does not put it in a URL, archive pointer,
bundle manifest, browser response, or repository file. `.env.example` contains only
the placeholder. Offline preflight and replay do not read the credential.

### Still not established by elevation

- The 2 m DEM is suitable for profiles and source-quality checks, but it is not a
  hydraulic model and must not replace Syke's published flood scenarios.
- The WCS response did not identify the cell-specific MML quality class. Product-level
  accuracy descriptions therefore cannot be silently assigned to this exact window.
- The adapter validates source cells but does not yet sample them onto road edges,
  decide whether any road is closed, or prove passability or safe access.
- A Topographic Database adapter still needs a field-by-field reconciliation policy.
  Source roads may be useful for comparison and stable cross-references, but cannot
  silently overwrite OSM access, direction, or topology.

## City of Espoo open geographic data

### Confirmed layers and coverage

Espoo publishes the [open geographic-data WFS and layer
catalogue](https://www.espoo.fi/en/open-data-of-the-geographic-information-unit).
The recommended endpoint is:

```text
https://kartat.espoo.fi/teklaogcweb/wfs.ashx?OUTPUTFORMAT=GML2
```

The proposed `EPSG:3879` bounding box returned the following anonymous WFS 1.1
responses on 2026-08-30:

| Layer | Server-reported bbox features | Proposed role |
| --- | ---: | --- |
| `GIS:Keskilinjat` | 7,072 | Municipal street/path geometry and attributes; topology cross-check |
| `GIS:Pyorailykartta` | 6,398 | Cycling-route enrichment and completeness check |
| `GIS:Rakennukset` | 381 | Origin geometry and visual context |
| `GIS:Osoitteet` | 336 | Address-origin input, subject to clustering rules |
| `GIS:Vesialueet` | 22 | Coastline/water consistency check |
| `GIS:InfStreet` | 2,024 | Public street-area geometry and ownership/context |

These are granular source features, not graph-node counts. They also cover the bbox
corners outside the irregular polygon. The v1 adapter issues one bounded request per
layer and rejects a declared/member count mismatch; it does not yet tile. Larger-area
support will need tiling plus source-ID deduplication. Geometry validation and
deterministic topology simplification remain necessary at the current size.

Espoo's WFS schema exposes potentially useful centerline fields including functional
and administrative class, direction, speed, maintenance, and cycling fields. Their
population and semantic reliability in Otaniemi must be profiled before they become
routing permissions. OSM should remain the first routable topology in the prototype,
with municipal features joined as sourced evidence rather than silently substituted.

The national open-data catalogue records the [Espoo transport
centerlines](https://avoindata.suomi.fi/data/en_GB/dataset/espoon-liikennevaylien-keskilinjat),
[Espoo buildings](https://avoindata.suomi.fi/data/en_GB/dataset/espoon-rakennukset),
[Espoo addresses](https://avoindata.suomi.fi/data/en_GB/dataset/espoon-osoitteet),
and [Espoo public-area
register](https://avoindata.suomi.fi/data/en_GB/dataset/espoon-kaupungin-yleisten-alueiden-rekisteri)
under CC BY 4.0. The city catalogue describes the checked simple layers as weekly
updated. Every snapshot still needs the exact dataset name, query time, source URL,
and attribution; the general WFS capabilities list is not a licence substitute for
an unlisted layer.

### Service observations to encode in the adapter

- Native storage and query CRS is ETRS-GK25 (`EPSG:3879`); normalize to
  `EPSG:3067` after acquisition.
- The service recommends GML2. During this audit, adding a CRS suffix to `BBOX`
  returned an empty collection, while supplying the same native-coordinate bbox
  without the suffix returned the expected features. Treat that as a tested service
  quirk and retain a regression fixture.
- The response can be large for a compact area. The v1 adapter makes one bounded
  request per layer, validates declared/member counts, and treats a structurally
  valid empty collection as an observation with coverage still unknown. Larger-area
  support needs bounded tiling, stable-ID deduplication, and explicit retry policy.
- Buildings and addresses are geometric origins, not population counts, occupancy
  claims, or declarations that an address must support private-car access.

### Reproducible Espoo endpoint check

The dated anonymous-access observation above used the official capabilities and
feature endpoint, not a browser map:

```text
Capabilities:
https://kartat.espoo.fi/teklaogcweb/wfs.ashx?request=GetCapabilities

GetFeature template observed working on 2026-08-30:
https://kartat.espoo.fi/teklaogcweb/wfs.ashx
  ?OUTPUTFORMAT=GML2
  &SERVICE=WFS
  &VERSION=1.1.0
  &REQUEST=GetFeature
  &TYPENAME=GIS:Keskilinjat
  &BBOX=25489540,6673414,25491262,6675387
```

`GIS:Keskilinjat` can be replaced by the other confirmed layer identifiers in the
table. The response declares coordinates in `EPSG:3879`. In this audit, appending
`,EPSG:3879` to that `BBOX` unexpectedly returned zero features; omitting it returned
7,072. The adapter must assert returned bounds and a plausible count so a service
parser change becomes a data error rather than a valid empty scenario.

## Finnish Environment Institute (Syke)

### Confirmed coastal-flood coverage

Syke's [web-map service
catalogue](https://www.syke.fi/en/environmental-data/open-web-services/web-map-services)
publishes WMS/WFS/WCS services for basic and special flood scenarios, flood risk,
and roads under flood inundation. The [basic flood-hazard dataset
description](https://luontotieto.syke.fi/aineisto/tulvavaaravyohykkeet-perusskenaariot-flood-hazard-zones-basic-scenarios/)
defines coastal scenarios at recurrence intervals of 1/2, 1/5, 1/10, 1/20, 1/50,
1/100, 1/250, and 1/1000 years. A 1/100 event is described as having an estimated
1% probability in a given year. Depth classes include 0–0.5 m, 0.5–1 m, 1–2 m,
2–3 m, over 3 m, and waterbody.

The exact proposed polygon produced the following diagnostic intersections. Flooded
land excludes source classes `kuiva maa` (dry land) and `vesistö` (waterbody):

| Coastal scenario | Terrestrial inundation inside core | Share of approximate terrestrial core |
| --- | ---: | ---: |
| 1/2 | 0.179 km² | 7.8% |
| 1/10 | 0.211 km² | 9.2% |
| 1/50 | 0.241 km² | 10.4% |
| 1/100 | 0.257 km² | 11.1% |
| 1/250 | 0.281 km² | 12.2% |
| 1/1000 | 0.331 km² | 14.3% |

Syke also publishes road-network-under-inundation layers. After exact polygon
clipping and union by depth class, the audit found:

| Coastal scenario | Intersecting source road features | Affected source-road length |
| --- | ---: | ---: |
| 1/100 | 69 | 2.054 km |
| 1/1000 | 115 | 3.280 km |

This is enough signal for a nontrivial first experiment. The canonical solver input
should nevertheless be produced by intersecting the chosen hazard polygons with the
frozen routable graph. Syke's precomputed road layers should be retained as an
independent QA comparison because their MML-linked topology and segment IDs do not
match OSM or Espoo identifiers directly.

Useful initial WFS feature types are:

```text
inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_100a
inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_1000a
tulva_perus_tiet:Tulvariskitiet_Meritulva_1_0100a
tulva_perus_tiet:Tulvariskitiet_Meritulva_1_1000a
```

The exact machine endpoints and request form used on 2026-08-30 were:

```text
Hazard WFS:
https://paikkatiedot.ymparisto.fi/geoserver/inspire_nz/wfs

Flooded-road QA WFS:
https://paikkatiedot.ymparisto.fi/geoserver/tulva_perus_tiet/wfs

Common WFS 2.0 parameters:
service=WFS
version=2.0.0
request=GetFeature
srsName=EPSG:3067
BBOX=378622,6672708,380354,6674675,EPSG:3067
outputFormat=application/json
```

Use `typeNames` with one exact identifier from the block above. Note the naming
asymmetry: the hazard layer spells a century scenario `1_100a`, while the flooded-
road layer spells it `1_0100a`. The services returned `numberMatched` and GeoJSON
without a credential for these bounded audit requests. The capabilities declare a
10,000-feature default. The v1 adapter rejects a response when the reported matched
count exceeds the returned features rather than silently accepting truncation; a
future larger-area adapter must page or tile and reconcile the final count. This
dated observation does not waive Syke's identifier requirement for a long-lived or
intensive application.

Sampled intersecting features reported a source change date of 2025-11-18 and a
0.3 m elevation-error attribute. The dataset landing page also displays an older
dataset-update date. The snapshot must therefore record catalogue metadata, service
capabilities, and per-feature edition fields separately rather than presenting one
ambiguous “latest” date.

Syke's [licence and responsibility
page](https://www.syke.fi/en/environmental-data/use-license-and-responsibilities)
places open datasets under CC BY 4.0 and requires source attribution. The service
catalogue asks long-lived or intensive WFS/WCS applications to request a unique
application identifier from `gistuki@syke.fi`. Prototype requests worked without a
credential; production-style automated acquisition must follow that requirement.

### Limits that must be visible in the experiment

- The source explicitly warns that coarse flood maps are not suitable for
  building-specific conclusions. Polygon intersection does not prove that a
  building floods or remains dry.
- Recurrence is an estimate tied to the mapping edition, not a forecast for a
  particular date.
- A line intersecting a hazard polygon is not automatically impassable. Depth
  threshold, mode, bridge/tunnel level, culverts, local protection, and uncertainty
  must be explicit scenario semantics.
- The experiment will evaluate topological access under the chosen closures. It will
  not simulate hydraulics, certify evacuation safety, or predict traffic capacity.

## Roadworks: confirmed gap

The Espoo WFS capabilities response advertises a `GIS:Katutapahtumat` feature type.
Its schema contains permit type/state and validity start/end fields. However:

- it is absent from the city's published open simple-feature list;
- an anonymous `GetFeature` request returned HTTP 401 on 2026-08-30;
- the exposed schema does not establish which road edge is closed, whether a
  closure is complete, or which modes and directions remain permitted; and
- Espoo's [transport-project
pages](https://www.espoo.fi/en/transport-and-streets/transport-projects) are useful
human-readable context, but not a complete operational closure feed.

Capabilities visibility is not authorization to ingest or redistribute a layer.
Until the city confirms access, licence, completeness, geometry, and mode semantics,
the prototype should accept a versioned GeoJSON/CSV works file with explicit fields:

```text
works_id, geometry, starts_at, ends_at, affected_modes,
direction, closure_kind, source, source_date, confidence, notes
```

Such a file must be labelled **user-supplied scenario data**, not current municipal
roadworks. Missing mode information is a validation error, not permission to assume
a full closure. Public project pages may motivate a research fixture, but should not
be scraped and transformed into operational restrictions without a documented
source and review.

## Historical candidate machine-readable recipe

This was the audit handoff sketch, not the implemented schema. It is retained to
show the source-role decisions. The authoritative typed schema is implemented in
`services/scenario_builder/models.py`; the checked recipes are
`data/recipes/espoo-otaniemi-coastal-base-v1.json` and
`data/recipes/espoo-otaniemi-coastal-v1.json`. The later exact elevation adapter has
its own authoritative recipe,
`data/recipes/espoo-otaniemi-coastal-elevation-v1.json`; the historical JSON below
is not its runtime configuration.

```json
{
  "schema_version": "resilient-access.recipe/v0.1",
  "scenario_id": "otaniemi-coastal-pilot-v0",
  "country_profile": "finland",
  "area": {
    "analysis_crs": "EPSG:3067",
    "analysis_polygon_wgs84": {
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
    },
    "network_context_buffer_m": 750,
    "context_sensitivity_m": [500, 1000]
  },
  "sources": {
    "osm": {
      "role": "primary_routable_topology",
      "snapshot_required": true
    },
    "mml_elevation_2m": {
      "role": "elevation_and_hazard_qa",
      "required": true,
      "wcs_endpoint": "https://avoin-karttakuva.maanmittauslaitos.fi/ortokuvat-ja-korkeusmallit/wcs/v2",
      "file_process_endpoint": "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/",
      "crs": "EPSG:3067",
      "vertical_crs": "EPSG:3900",
      "credential_env": "MML_API_KEY"
    },
    "mml_topographic": {
      "role": "national_geometry_crosscheck",
      "required": false,
      "credential_env": "MML_API_KEY"
    },
    "espoo_wfs": {
      "role": "municipal_enrichment",
      "endpoint": "https://kartat.espoo.fi/teklaogcweb/wfs.ashx",
      "native_crs": "EPSG:3879",
      "output_format": "GML2",
      "layers": [
        "GIS:Keskilinjat",
        "GIS:Pyorailykartta",
        "GIS:Rakennukset",
        "GIS:Osoitteet",
        "GIS:Vesialueet",
        "GIS:InfStreet"
      ]
    },
    "syke_flood": {
      "role": "canonical_hazard",
      "hazard_wfs_endpoint": "https://paikkatiedot.ymparisto.fi/geoserver/inspire_nz/wfs",
      "road_qa_wfs_endpoint": "https://paikkatiedot.ymparisto.fi/geoserver/tulva_perus_tiet/wfs",
      "wfs_version": "2.0.0",
      "output_format": "application/json",
      "crs": "EPSG:3067",
      "operator_identifier_required_for_long_term_use": true,
      "hazard_layers": [
        "inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_100a",
        "inspire_nz:NZ.Tulvavaaravyohykkeet_Meritulva_1_1000a"
      ],
      "qa_road_layers": [
        "tulva_perus_tiet:Tulvariskitiet_Meritulva_1_0100a",
        "tulva_perus_tiet:Tulvariskitiet_Meritulva_1_1000a"
      ]
    },
    "works": {
      "role": "time_dependent_edge_availability",
      "adapter": "user_supplied_geojson_or_csv",
      "required": false,
      "live_municipal_feed_confirmed": false
    }
  },
  "semantics": {
    "hazard_source": "syke_polygon_intersection",
    "mml_elevation": "quality_control_only",
    "syke_flooded_roads": "independent_qa_only",
    "analysis_boundary_is_safe_destination": false
  }
}
```

## Go/no-go assessment

### Go

- The core is within the requested compact size and contains both coastal exposure
  and inland-facing network context.
- Published Syke coastal scenarios affect a meaningful area and kilometres of source
  roads, so the experiment is not based on a nominal shoreline label.
- Espoo supplies dense weekly municipal geometry for streets, cycling, buildings,
  addresses, water, and public street areas.
- MML supplies a nationally consistent 2 m elevation model under an open licence;
  the exact context window is now frozen and replayable. A live refresh still needs
  operator credentials, and the Topographic Database remains only a candidate
  cross-check.

### Not ready

- Safe destinations, critical origins, and acceptable per-mode travel thresholds
  have not been selected or reviewed.
- Bridge, tunnel, underpass, and vertical-separation semantics have not been
  validated against the hazard layers.
- No open operational roadworks feed with adequate mode and schedule semantics has
  been confirmed.
- Flood exposure has not yet been translated into edge availability, and reviewed
  origins, safe destinations, service thresholds, and vulnerability verification
  have not been implemented.

The next defensible milestone is therefore a **vulnerability-only Otaniemi
analysis**: select explicit destinations in the context graph, adopt one documented
flood-to-availability policy after vertical review, and report lost/reduced access
without proposing optimisation actions. Roadworks should enter only after one
explicit user-supplied case is validated and matched to the graph or a municipal
feed is formally confirmed.

## Implement next

The command-line source, graph, and exposure foundation is complete. The next work
should stay vulnerability-first:

1. Inspect every exposed bridge, tunnel, layer, covered way, and ford flag before
   defining explicit depth/mode availability assumptions.
2. Join Espoo address/building evidence without overwriting OSM topology; select
   origins only in the core and require reviewed destinations in the context graph.
3. Independently verify retained and lost access for the 1/100 and 1/1000 scenarios,
   with counterexample routes and threshold sensitivity.
4. Sample the frozen MML Elevation Model 2 m window for inspectable vertical and
   low-point review, not as a replacement flood model or automatic closure rule.
5. Export an inspectable browser vulnerability dataset. Add optimization only after
   that report and its boundary/destination sensitivity are credible.

The user-supplied roadworks file schema is now implemented and tested. Network-edge
matching and temporal access analysis can proceed in parallel once a documented
case exists, but it must not be presented as live Espoo data while the municipal
operational-feed gap remains unresolved.
