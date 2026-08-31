import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  Feature,
  FeatureCollection,
  Geometry,
  LineString,
  MultiLineString,
} from 'geojson'
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type MapGeoJSONFeature,
  type MapMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl'
import { Construction, Crosshair, LocateFixed, ShieldCheck, Waves } from 'lucide-react'
import './ResilienceAnalysisMap.css'

export type ResilienceMapView = 'baseline' | 'disrupted' | 'verified'

export type ResilienceLocationStatus = 'unknown' | 'reachable' | 'stranded'

export interface ResilienceMapLocation {
  id: string
  label: string
  point: [number, number]
  kind: 'origin' | 'destination'
  status?: ResilienceLocationStatus
  detail?: string
}

export interface ResilienceMapSegmentPick {
  id: string
  label: string
  highway?: string
  selectedAsRoadwork: boolean
}

export interface ResilienceAnalysisMapProps {
  /** Browser-ready EPSG:4326 features from the frozen base-network artifact. */
  baseNetwork: FeatureCollection
  /** Optional building polygons from an OSM or municipal-context layer. */
  buildings?: FeatureCollection
  /** Frozen, horizontal flood-overlap evidence. This must not imply passability. */
  floodExposure?: FeatureCollection
  /** Edges explicitly declared unavailable by the scenario, not inferred by this map. */
  unavailableSegments?: FeatureCollection<LineString | MultiLineString>
  /** Stable physical IDs can be supplied instead; geometry is joined from baseNetwork. */
  unavailableSegmentIds?: string[]
  /** User-declared or attributed roadworks closures. */
  roadworks?: FeatureCollection<LineString | MultiLineString>
  /** Network subset retained by the disrupted graph verifier. */
  reachableNetwork?: FeatureCollection<LineString | MultiLineString>
  reachableSegmentIds?: string[]
  /** Paths found to remain available after disruption. */
  reachableRoutes?: FeatureCollection<LineString | MultiLineString>
  /** Requested access paths that are broken by the scenario. */
  affectedRoutes?: FeatureCollection<LineString | MultiLineString>
  /** Current verifier counterexample or model-refinement witness. */
  counterexampleRoute?: FeatureCollection<LineString | MultiLineString>
  /** Directed reachable-set frontier used to derive the learned clause. */
  frontierLinks?: FeatureCollection<LineString | MultiLineString>
  frontierSegmentIds?: string[]
  /** Physical links covered by the current continuity-zone assignment. */
  repairLinks?: FeatureCollection<LineString | MultiLineString>
  repairSegmentIds?: string[]
  /** Number of grouped Boolean commitments represented by repairSegmentIds. */
  commitmentCount?: number
  locations?: ResilienceMapLocation[]
  selectedReturnPeriod?: 100 | 1000
  view: ResilienceMapView
  onViewChange?: (view: ResilienceMapView) => void
  center?: [number, number]
  bbox?: [number, number, number, number]
  title?: string
  snapshotId?: string
  solving?: boolean
  iteration?: number
  statusMessage?: string
  verifiedAvailable?: boolean
  selectedRoadworkSegmentIds?: string[]
  /** Enables click-to-toggle modelling closures on base-network links. */
  onNetworkSegmentToggle?: (segment: ResilienceMapSegmentPick) => void
  onLocationSelect?: (location: ResilienceMapLocation) => void
  dataAttribution?: string
}

const EMPTY_COLLECTION: FeatureCollection = { type: 'FeatureCollection', features: [] }

const MAP_STYLE: StyleSpecification = {
  version: 8,
  name: 'Four Planters resilience evidence canvas',
  sources: {},
  layers: [
    {
      id: 'res-paper',
      type: 'background',
      paint: { 'background-color': '#edf0eb' },
    },
  ],
}

type ResilienceSourceName =
  | 'res-base'
  | 'res-buildings'
  | 'res-flood'
  | 'res-unavailable'
  | 'res-roadworks'
  | 'res-reachable-network'
  | 'res-reachable-routes'
  | 'res-affected-routes'
  | 'res-counterexample'
  | 'res-frontier'
  | 'res-frontier-points'
  | 'res-repairs'
  | 'res-repair-points'

function setSourceData(
  map: MapLibreMap,
  name: ResilienceSourceName,
  data: FeatureCollection | undefined,
): void {
  const source = map.getSource(name) as GeoJSONSource | undefined
  source?.setData(data ?? EMPTY_COLLECTION)
}

function featureIdentity(properties: Record<string, unknown> | null | undefined): string {
  return String(
    properties?.physical_segment_id
      ?? properties?.segment_id
      ?? properties?.id
      ?? '',
  )
}

function uniqueSegmentCount(collection?: FeatureCollection): number {
  if (!collection) return 0
  const ids = new Set<string>()
  collection.features.forEach((feature, index) => {
    const id = featureIdentity(feature.properties as Record<string, unknown> | null)
    ids.add(id || String(feature.id ?? index))
  })
  return ids.size
}

function lineFeaturesBySegmentId(
  baseNetwork: FeatureCollection,
  segmentIds: string[] | undefined,
): FeatureCollection<LineString | MultiLineString> {
  if (!segmentIds?.length) return { type: 'FeatureCollection', features: [] }
  const wanted = new Set(segmentIds)
  const features = baseNetwork.features.filter((feature): feature is Feature<LineString | MultiLineString> => (
    (feature.geometry.type === 'LineString' || feature.geometry.type === 'MultiLineString')
    && wanted.has(featureIdentity(feature.properties as Record<string, unknown> | null))
  ))
  return { type: 'FeatureCollection', features }
}

function midpointCollection(
  collection?: FeatureCollection<LineString | MultiLineString>,
): FeatureCollection {
  if (!collection) return EMPTY_COLLECTION
  const features = collection.features.flatMap((feature, featureIndex) => {
    const lines = feature.geometry.type === 'LineString'
      ? [feature.geometry.coordinates]
      : feature.geometry.coordinates
    return lines.flatMap((coordinates, lineIndex) => {
      const coordinate = coordinates[Math.floor((coordinates.length - 1) / 2)]
      if (!coordinate) return []
      const longitude = coordinate[0]
      const latitude = coordinate[1]
      if (longitude === undefined || latitude === undefined) return []
      return [{
        type: 'Feature' as const,
        id: `repair-point-${String(feature.id ?? featureIndex)}-${lineIndex}`,
        properties: feature.properties,
        geometry: { type: 'Point' as const, coordinates: [longitude, latitude] },
      }]
    })
  })
  return { type: 'FeatureCollection', features }
}

function derivedBounds(collection: FeatureCollection): [number, number, number, number] | undefined {
  let west = Number.POSITIVE_INFINITY
  let south = Number.POSITIVE_INFINITY
  let east = Number.NEGATIVE_INFINITY
  let north = Number.NEGATIVE_INFINITY

  const visitCoordinates = (value: unknown): void => {
    if (!Array.isArray(value)) return
    if (
      value.length >= 2
      && typeof value[0] === 'number'
      && typeof value[1] === 'number'
      && Number.isFinite(value[0])
      && Number.isFinite(value[1])
    ) {
      west = Math.min(west, value[0])
      south = Math.min(south, value[1])
      east = Math.max(east, value[0])
      north = Math.max(north, value[1])
      return
    }
    value.forEach(visitCoordinates)
  }

  const visitGeometry = (geometry: Geometry | null): void => {
    if (!geometry) return
    if (geometry.type === 'GeometryCollection') {
      geometry.geometries.forEach(visitGeometry)
      return
    }
    visitCoordinates(geometry.coordinates)
  }
  collection.features.forEach((feature) => visitGeometry(feature.geometry))
  if (![west, south, east, north].every(Number.isFinite)) return undefined
  return [west, south, east, north]
}

function roadClassExpression(): maplibregl.ExpressionSpecification {
  return [
    'match',
    ['coalesce', ['get', 'highway'], ['get', 'road_class'], 'local'],
    ['motorway', 'trunk', 'primary'], '#626a68',
    ['secondary', 'tertiary'], '#7e8581',
    ['footway', 'cycleway', 'path', 'steps'], '#b9bcb4',
    '#9da29c',
  ]
}

function addSourcesAndLayers(map: MapLibreMap, returnPeriod: 100 | 1000): void {
  map.addSource('res-base', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-buildings', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-flood', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-unavailable', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-roadworks', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-reachable-network', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-reachable-routes', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-affected-routes', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-counterexample', {
    type: 'geojson',
    data: EMPTY_COLLECTION,
    lineMetrics: true,
  })
  map.addSource('res-frontier', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-frontier-points', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-repairs', { type: 'geojson', data: EMPTY_COLLECTION })
  map.addSource('res-repair-points', { type: 'geojson', data: EMPTY_COLLECTION })

  map.addLayer({
    id: 'res-network-context',
    type: 'fill',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'network_context'],
    paint: { 'fill-color': '#e3e8e1', 'fill-opacity': 0.52 },
  })
  map.addLayer({
    id: 'res-study-core',
    type: 'fill',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'study_core'],
    paint: { 'fill-color': '#f5f3ec', 'fill-opacity': 0.66 },
  })
  map.addLayer({
    id: 'res-buildings',
    type: 'fill',
    source: 'res-buildings',
    minzoom: 12,
    paint: {
      'fill-color': '#d3d5ce',
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 12, 0.36, 16, 0.72],
      'fill-outline-color': 'rgba(76,84,80,.2)',
    },
  })
  map.addLayer({
    id: 'res-reachable-network-halo',
    type: 'line',
    source: 'res-reachable-network',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#3a857e',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 5, 16, 13],
      'line-opacity': 0.12,
    },
  })
  map.addLayer({
    id: 'res-street-casing',
    type: 'line',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'base_network'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#f9f7f0',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2.2, 16, 8.2],
      'line-opacity': 0.94,
    },
  })
  map.addLayer({
    id: 'res-streets',
    type: 'line',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'base_network'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': roadClassExpression(),
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        11, [
          'match', ['coalesce', ['get', 'highway'], 'local'],
          ['motorway', 'trunk', 'primary'], 1.8,
          ['secondary', 'tertiary'], 1.3,
          0.75,
        ],
        16, [
          'match', ['coalesce', ['get', 'highway'], 'local'],
          ['motorway', 'trunk', 'primary'], 5.4,
          ['secondary', 'tertiary'], 4.1,
          2.25,
        ],
      ],
      'line-opacity': [
        'case',
        ['any', ['boolean', ['get', 'private_car_forward'], false], ['boolean', ['get', 'private_car_reverse'], false]],
        0.96,
        0.55,
      ],
    },
  })
  map.addLayer({
    id: 'res-flood-halo',
    type: 'line',
    source: 'res-flood',
    filter: ['==', ['get', 'return_period_years'], returnPeriod],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#f5f3ec',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 5.2, 16, 11],
      'line-opacity': 0.72,
    },
  })
  map.addLayer({
    id: 'res-flood',
    type: 'line',
    source: 'res-flood',
    filter: ['==', ['get', 'return_period_years'], returnPeriod],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#266b9a',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2.4, 16, 6.4],
      'line-opacity': 0.52,
    },
  })
  map.addLayer({
    id: 'res-affected-routes-halo',
    type: 'line',
    source: 'res-affected-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#fff8ef', 'line-width': 8, 'line-opacity': 0.78 },
  })
  map.addLayer({
    id: 'res-affected-routes',
    type: 'line',
    source: 'res-affected-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#b54d51',
      'line-width': 3.2,
      'line-opacity': 0.62,
      'line-dasharray': [0.7, 1.1],
    },
  })
  map.addLayer({
    id: 'res-unavailable-halo',
    type: 'line',
    source: 'res-unavailable',
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: {
      'line-color': '#fffaf2',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 5.8, 16, 12],
      'line-opacity': 0.9,
    },
  })
  map.addLayer({
    id: 'res-unavailable',
    type: 'line',
    source: 'res-unavailable',
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: {
      'line-color': '#9d3f3b',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2.4, 16, 5.5],
      'line-opacity': 0.95,
      'line-dasharray': [0.45, 0.55],
    },
  })
  map.addLayer({
    id: 'res-roadworks-halo',
    type: 'line',
    source: 'res-roadworks',
    layout: { 'line-cap': 'square', 'line-join': 'round' },
    paint: { 'line-color': '#fffaf2', 'line-width': 10, 'line-opacity': 0.92 },
  })
  map.addLayer({
    id: 'res-roadworks',
    type: 'line',
    source: 'res-roadworks',
    layout: { 'line-cap': 'square', 'line-join': 'round' },
    paint: {
      'line-color': '#2f3332',
      'line-width': 4,
      'line-opacity': 0.98,
      'line-dasharray': [1.2, 0.7],
    },
  })
  map.addLayer({
    id: 'res-reachable-routes-halo',
    type: 'line',
    source: 'res-reachable-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#f7f6ef', 'line-width': 8, 'line-opacity': 0.8 },
  })
  map.addLayer({
    id: 'res-reachable-routes',
    type: 'line',
    source: 'res-reachable-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#2c8179',
      'line-width': 3.6,
      'line-opacity': 0.92,
      'line-dasharray': [2.2, 0.8],
    },
  })
  map.addLayer({
    id: 'res-counterexample-halo',
    type: 'line',
    source: 'res-counterexample',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#fff8ef', 'line-width': 9, 'line-opacity': 0.88 },
  })
  map.addLayer({
    id: 'res-counterexample',
    type: 'line',
    source: 'res-counterexample',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#d44270',
      'line-width': 4.1,
      'line-opacity': 0.98,
      'line-dasharray': [0.35, 0.85],
    },
  })
  map.addLayer({
    id: 'res-frontier-halo',
    type: 'line',
    source: 'res-frontier',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#fff8ef',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 9, 16, 15],
      'line-opacity': 0.96,
    },
  })
  map.addLayer({
    id: 'res-frontier',
    type: 'line',
    source: 'res-frontier',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#d8574d',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 4, 16, 8],
      'line-opacity': 0.98,
    },
  })
  map.addLayer({
    id: 'res-frontier-gates',
    type: 'circle',
    source: 'res-frontier-points',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 5, 16, 8],
      'circle-color': '#fff8ef',
      'circle-stroke-color': '#d8574d',
      'circle-stroke-width': 3,
    },
  })
  map.addLayer({
    id: 'res-repairs-halo',
    type: 'line',
    source: 'res-repairs',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#fffaf2', 'line-width': 12, 'line-opacity': 0.96 },
  })
  map.addLayer({
    id: 'res-repairs',
    type: 'line',
    source: 'res-repairs',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#e9662c',
      'line-width': 6.2,
      'line-opacity': 1,
      'line-dasharray': [1.4, 0.4],
    },
  })
  map.addLayer({
    id: 'res-repair-targets',
    type: 'circle',
    source: 'res-repair-points',
    paint: {
      'circle-radius': 7,
      'circle-color': '#e9662c',
      'circle-stroke-color': '#fffaf2',
      'circle-stroke-width': 3,
    },
  })
  map.addLayer({
    id: 'res-repair-target-centres',
    type: 'circle',
    source: 'res-repair-points',
    paint: { 'circle-radius': 2.1, 'circle-color': '#2c302f' },
  })
  map.addLayer({
    id: 'res-study-core-edge',
    type: 'line',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'study_core'],
    paint: {
      'line-color': '#596360',
      'line-width': 1.5,
      'line-opacity': 0.72,
      'line-dasharray': [2, 1.5],
    },
  })
  map.addLayer({
    id: 'res-base-hit',
    type: 'line',
    source: 'res-base',
    filter: ['==', ['get', 'layer'], 'base_network'],
    paint: {
      'line-color': '#000000',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 8, 16, 18],
      'line-opacity': 0.01,
    },
  })
}

function updateModeLayers(map: MapLibreMap, view: ResilienceMapView): void {
  const baseline = view === 'baseline'
  const verified = view === 'verified'
  const setVisible = (layers: string[], visible: boolean) => {
    layers.forEach((layer) => map.setLayoutProperty(layer, 'visibility', visible ? 'visible' : 'none'))
  }

  map.setPaintProperty('res-flood', 'line-opacity', baseline ? 0.26 : verified ? 0.38 : 0.66)
  map.setPaintProperty('res-flood-halo', 'line-opacity', baseline ? 0.38 : 0.72)
  setVisible(['res-reachable-network-halo'], !baseline)
  setVisible(['res-unavailable-halo', 'res-unavailable'], !baseline)
  setVisible(['res-roadworks-halo', 'res-roadworks'], !baseline)
  setVisible(['res-affected-routes-halo', 'res-affected-routes'], !baseline)
  setVisible(['res-reachable-routes-halo', 'res-reachable-routes'], !baseline)
  setVisible(['res-counterexample-halo', 'res-counterexample'], !baseline && !verified)
  setVisible(['res-frontier-halo', 'res-frontier', 'res-frontier-gates'], !baseline && !verified)
  setVisible([
    'res-repairs-halo',
    'res-repairs',
    'res-repair-targets',
    'res-repair-target-centres',
  ], !baseline)
  map.setPaintProperty('res-repairs', 'line-dasharray', verified ? [1, 0] : [0.65, 0.75])
  map.setPaintProperty('res-repairs', 'line-opacity', verified ? 1 : 0.82)
  map.setPaintProperty('res-repair-targets', 'circle-opacity', verified ? 1 : 0.7)
}

function updateFloodFilter(map: MapLibreMap, returnPeriod: 100 | 1000): void {
  const filter: maplibregl.FilterSpecification = [
    '==', ['get', 'return_period_years'], returnPeriod,
  ]
  map.setFilter('res-flood-halo', filter)
  map.setFilter('res-flood', filter)
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[character] ?? character)
}

function tooltipContent(layerId: string, properties: Record<string, unknown>): string {
  const name = String(properties.name ?? properties.street_name ?? properties.label ?? 'Unnamed network link')
  const segmentId = featureIdentity(properties)
  let eyebrow = 'Frozen network link'
  let detail = String(properties.highway ?? 'Street-network evidence')
  if (layerId === 'res-flood') {
    eyebrow = `1/${String(properties.return_period_years ?? '—')} mapped coastal-flood scenario`
    const length = Number(properties.intersected_length_m)
    detail = Number.isFinite(length)
      ? `${length.toFixed(1)} m horizontal overlap · not measured carriageway depth · passability not inferred`
      : 'Horizontal overlap · not measured carriageway depth · passability not inferred'
  } else if (layerId === 'res-unavailable') {
    eyebrow = 'Explicitly unavailable'
    detail = String(properties.reason ?? properties.assumption ?? 'Scenario assumption')
  } else if (layerId === 'res-roadworks') {
    eyebrow = 'Roadworks closure'
    detail = String(properties.description ?? properties.source ?? 'User-declared scenario input')
  } else if (layerId === 'res-repairs') {
    eyebrow = 'Continuity-zone member'
    detail = String(properties.reason ?? 'Selected by the current Z3 assignment; check run status')
  }
  return `<span>${escapeHtml(eyebrow)}</span><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small>${segmentId ? `<code>${escapeHtml(segmentId)}</code>` : ''}`
}

function locationAriaLabel(location: ResilienceMapLocation): string {
  const kind = location.kind === 'origin' ? 'Origin' : 'Destination'
  const status = location.status === 'stranded'
    ? ', stranded in current scenario'
    : location.status === 'reachable'
      ? ', reachable in current scenario'
      : ''
  return `${kind}: ${location.label}${status}${location.detail ? `. ${location.detail}` : ''}`
}

export function ResilienceAnalysisMap({
  baseNetwork,
  buildings,
  floodExposure,
  unavailableSegments,
  unavailableSegmentIds,
  roadworks,
  reachableNetwork,
  reachableSegmentIds,
  reachableRoutes,
  affectedRoutes,
  counterexampleRoute,
  frontierLinks,
  frontierSegmentIds,
  repairLinks,
  repairSegmentIds,
  commitmentCount,
  locations = [],
  selectedReturnPeriod = 100,
  view,
  onViewChange,
  center = [24.828, 60.184],
  bbox,
  title = 'Otaniemi coastal access',
  snapshotId,
  solving = false,
  iteration,
  statusMessage,
  verifiedAvailable = false,
  selectedRoadworkSegmentIds = [],
  onNetworkSegmentToggle,
  onLocationSelect,
  dataAttribution = 'OSM · SYKE · City of Espoo · MML',
}: ResilienceAnalysisMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const markersRef = useRef<maplibregl.Marker[]>([])
  const onSegmentToggleRef = useRef(onNetworkSegmentToggle)
  const selectedRoadworkIdsRef = useRef(new Set(selectedRoadworkSegmentIds))
  const [loaded, setLoaded] = useState(false)
  const [rendered, setRendered] = useState(false)

  const mapBounds = useMemo(() => bbox ?? derivedBounds(baseNetwork), [baseNetwork, bbox])
  const resolvedUnavailableSegments = useMemo(
    () => unavailableSegments ?? lineFeaturesBySegmentId(baseNetwork, unavailableSegmentIds),
    [baseNetwork, unavailableSegmentIds, unavailableSegments],
  )
  const resolvedRoadworks = useMemo(
    () => roadworks ?? lineFeaturesBySegmentId(baseNetwork, selectedRoadworkSegmentIds),
    [baseNetwork, roadworks, selectedRoadworkSegmentIds],
  )
  const resolvedReachableNetwork = useMemo(
    () => reachableNetwork ?? lineFeaturesBySegmentId(baseNetwork, reachableSegmentIds),
    [baseNetwork, reachableNetwork, reachableSegmentIds],
  )
  const resolvedRepairLinks = useMemo(
    () => repairLinks ?? lineFeaturesBySegmentId(baseNetwork, repairSegmentIds),
    [baseNetwork, repairLinks, repairSegmentIds],
  )
  const resolvedFrontierLinks = useMemo(
    () => frontierLinks ?? lineFeaturesBySegmentId(baseNetwork, frontierSegmentIds),
    [baseNetwork, frontierLinks, frontierSegmentIds],
  )
  const exposedCount = useMemo(() => {
    if (!floodExposure) return 0
    return uniqueSegmentCount({
      type: 'FeatureCollection',
      features: floodExposure.features.filter((feature) => (
        Number(feature.properties?.return_period_years) === selectedReturnPeriod
      )),
    })
  }, [floodExposure, selectedReturnPeriod])
  const strandedCount = locations.filter((location) => (
    location.kind === 'origin' && location.status === 'stranded'
  )).length
  const commitmentLinkCount = uniqueSegmentCount(resolvedRepairLinks)

  useEffect(() => {
    onSegmentToggleRef.current = onNetworkSegmentToggle
  }, [onNetworkSegmentToggle])

  useEffect(() => {
    selectedRoadworkIdsRef.current = new Set(selectedRoadworkSegmentIds)
  }, [selectedRoadworkSegmentIds])

  useEffect(() => {
    if (!containerRef.current || typeof WebGLRenderingContext === 'undefined') return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center,
      zoom: 13.3,
      minZoom: 10,
      maxZoom: 19,
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }),
      'top-right',
    )
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 100 }), 'bottom-right')
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a>',
      }),
      'bottom-right',
    )

    map.once('load', () => {
      addSourcesAndLayers(map, selectedReturnPeriod)
      updateModeLayers(map, view)
      const bounds = bbox ?? derivedBounds(baseNetwork)
      if (bounds) {
        map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
          padding: { top: 74, right: 58, bottom: 78, left: 62 },
          duration: 0,
        })
      }
      setLoaded(true)
    })

    const hoverLayers = ['res-repairs', 'res-roadworks', 'res-unavailable', 'res-flood', 'res-base-hit']
    const onMove = (event: MapMouseEvent) => {
      if (!map.isStyleLoaded()) return
      let hit: MapGeoJSONFeature | undefined
      for (const layer of hoverLayers) {
        hit = map.queryRenderedFeatures(event.point, { layers: [layer] })[0]
        if (hit) break
      }
      map.getCanvas().style.cursor = hit && onSegmentToggleRef.current ? 'pointer' : ''
      if (!hit) {
        popupRef.current?.remove()
        popupRef.current = null
        return
      }
      const layerId = hit.layer.id === 'res-base-hit' ? 'res-base' : hit.layer.id
      const properties = (hit.properties ?? {}) as Record<string, unknown>
      popupRef.current?.remove()
      popupRef.current = new maplibregl.Popup({
        className: 'resilience-map-tooltip',
        closeButton: false,
        closeOnClick: false,
        offset: 13,
      })
        .setLngLat(event.lngLat)
        .setHTML(tooltipContent(layerId, properties))
        .addTo(map)
    }
    const onClick = (event: MapMouseEvent) => {
      const callback = onSegmentToggleRef.current
      if (!callback || !map.isStyleLoaded()) return
      const hit = map.queryRenderedFeatures(event.point, { layers: ['res-base-hit'] })[0]
      if (!hit) return
      const properties = (hit.properties ?? {}) as Record<string, unknown>
      const id = featureIdentity(properties) || String(hit.id ?? '')
      if (!id) return
      callback({
        id,
        label: String(properties.name ?? properties.street_name ?? 'Unnamed network link'),
        highway: properties.highway ? String(properties.highway) : undefined,
        selectedAsRoadwork: selectedRoadworkIdsRef.current.has(id),
      })
    }
    map.on('mousemove', onMove)
    map.on('click', onClick)

    return () => {
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      popupRef.current?.remove()
      popupRef.current = null
      map.off('mousemove', onMove)
      map.off('click', onClick)
      map.remove()
      mapRef.current = null
      setLoaded(false)
    }
    // The analytical map is constructed once; data props update its sources below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    setSourceData(map, 'res-base', baseNetwork)
    setSourceData(map, 'res-buildings', buildings)
    setSourceData(map, 'res-flood', floodExposure)
    setSourceData(map, 'res-unavailable', resolvedUnavailableSegments)
    setSourceData(map, 'res-roadworks', resolvedRoadworks)
    setSourceData(map, 'res-reachable-network', resolvedReachableNetwork)
    setSourceData(map, 'res-reachable-routes', reachableRoutes)
    setSourceData(map, 'res-affected-routes', affectedRoutes)
    setSourceData(map, 'res-counterexample', counterexampleRoute)
    setSourceData(map, 'res-frontier', resolvedFrontierLinks)
    setSourceData(map, 'res-frontier-points', midpointCollection(resolvedFrontierLinks))
    setSourceData(map, 'res-repairs', resolvedRepairLinks)
    setSourceData(map, 'res-repair-points', midpointCollection(resolvedRepairLinks))
  }, [
    affectedRoutes,
    baseNetwork,
    buildings,
    counterexampleRoute,
    floodExposure,
    loaded,
    resolvedReachableNetwork,
    reachableRoutes,
    resolvedFrontierLinks,
    resolvedRepairLinks,
    resolvedRoadworks,
    resolvedUnavailableSegments,
  ])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || rendered) return
    const markWhenStreetsAreVisible = () => {
      if (!map.getLayer('res-streets')) return
      if (!map.queryRenderedFeatures({ layers: ['res-streets'] }).length) return
      setRendered(true)
    }
    map.on('render', markWhenStreetsAreVisible)
    map.triggerRepaint()
    return () => {
      map.off('render', markWhenStreetsAreVisible)
    }
  }, [loaded, rendered])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    updateModeLayers(map, view)
  }, [loaded, view])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    updateFloodFilter(map, selectedReturnPeriod)
  }, [loaded, selectedReturnPeriod])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    markersRef.current.forEach((marker) => marker.remove())
    markersRef.current = locations.map((location) => {
      const element = document.createElement('button')
      element.type = 'button'
      element.className = [
        'resilience-location-marker',
        `is-${location.kind}`,
        `is-${location.status ?? 'unknown'}`,
      ].join(' ')
      element.textContent = location.status === 'stranded'
        ? '!'
        : location.kind === 'origin' ? 'O' : 'D'
      element.title = locationAriaLabel(location)
      element.setAttribute('aria-label', locationAriaLabel(location))
      if (onLocationSelect) {
        element.addEventListener('click', (event) => {
          event.stopPropagation()
          onLocationSelect(location)
        })
      } else {
        element.tabIndex = -1
      }
      return new maplibregl.Marker({ element, anchor: 'center' })
        .setLngLat(location.point)
        .addTo(map)
    })
  }, [loaded, locations, onLocationSelect])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !counterexampleRoute || view !== 'disrupted') return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      map.setPaintProperty('res-counterexample', 'line-gradient', '#d44270')
      return
    }
    const started = performance.now()
    let frame = 0
    const draw = (time: number) => {
      const progress = Math.min(1, (time - started) / 720)
      map.setPaintProperty('res-counterexample', 'line-gradient', [
        'step', ['line-progress'], '#d44270', progress, 'rgba(212,66,112,0)',
      ])
      if (progress < 1) frame = window.requestAnimationFrame(draw)
    }
    frame = window.requestAnimationFrame(draw)
    return () => window.cancelAnimationFrame(frame)
  }, [counterexampleRoute, loaded, view])

  const recenter = () => {
    const map = mapRef.current
    if (!map) return
    if (mapBounds) {
      map.fitBounds([[mapBounds[0], mapBounds[1]], [mapBounds[2], mapBounds[3]]], {
        padding: { top: 74, right: 58, bottom: 78, left: 62 },
        duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 520,
      })
    } else {
      map.easeTo({ center, zoom: 13.3, duration: 420 })
    }
  }

  const viewLabel = view === 'baseline'
    ? 'Frozen network before disruption'
    : view === 'disrupted'
      ? 'Declared disruption and verifier evidence'
      : 'Fresh-graph checked continuity commitments'

  return (
    <section
      className={`resilience-analysis-map is-${view}`}
      aria-label={`Interactive resilience analysis map: ${title}`}
      data-map-ready={rendered ? 'true' : 'false'}
    >
      <p className="resilience-map__sr-only" id="resilience-map-instructions">
        The map compares the frozen baseline, declared disruption, and checked continuity commitments.
        Origin markers are circles labelled O, destinations are diamonds labelled D, and stranded
        origins are marked with an exclamation point. Flood colour indicates horizontal overlap
        evidence only; dashed red links are explicit unavailability assumptions.
      </p>
      <div
        ref={containerRef}
        className="resilience-map__canvas"
        role="application"
        aria-describedby="resilience-map-instructions resilience-map-summary"
      />
      <div className="resilience-map__grain" aria-hidden="true" />

      <div className="resilience-map__context" id="resilience-map-summary" aria-live="polite">
        <span className="resilience-map__eyebrow">Access vulnerability · Otaniemi</span>
        <strong>{title}</strong>
        <span>{viewLabel}</span>
        <dl>
          <div><dt>Exposed</dt><dd>{exposedCount}</dd></div>
          <div><dt>Stranded</dt><dd>{strandedCount}</dd></div>
          <div><dt>Zones</dt><dd>{commitmentCount ?? 0}</dd></div>
          <div><dt>Links</dt><dd>{commitmentLinkCount}</dd></div>
        </dl>
        {snapshotId && <code title={snapshotId}>{snapshotId}</code>}
      </div>

      <div className="resilience-map__views" aria-label="Network state shown on map">
        {(['baseline', 'disrupted', 'verified'] as const).map((nextView) => (
          <button
            key={nextView}
            type="button"
            className={view === nextView ? 'is-active' : ''}
            aria-pressed={view === nextView}
            onClick={() => onViewChange?.(nextView)}
            disabled={!onViewChange || (nextView === 'verified' && !verifiedAvailable)}
            title={nextView === 'verified' && !verifiedAvailable ? 'Available after a fresh successful graph check' : undefined}
          >
            {nextView === 'baseline' ? 'Before' : nextView === 'disrupted' ? 'Event' : 'Verified'}
          </button>
        ))}
      </div>

      <button
        type="button"
        className="resilience-map__recenter"
        onClick={recenter}
        aria-label="Recenter Otaniemi study area"
        title="Recenter study area"
      >
        <LocateFixed size={17} aria-hidden="true" />
      </button>

      {(solving || statusMessage) && (
        <div className={`resilience-map__status ${solving ? 'is-solving' : ''}`} role="status">
          <span>
            {solving
              ? <Crosshair size={15} aria-hidden="true" />
              : view === 'verified'
                ? <ShieldCheck size={15} aria-hidden="true" />
                : <Waves size={15} aria-hidden="true" />}
          </span>
          <p>
            <strong>{solving ? 'Checking the graph' : view === 'verified' ? 'Verified state' : 'Scenario state'}</strong>
            <small>{statusMessage ?? `Iteration ${iteration ?? 1} · testing retained access`}</small>
          </p>
        </div>
      )}

      <div className="resilience-map__legend" aria-label="Map legend">
        <span><i className="legend-network" />Frozen street network</span>
        <span><i className="legend-flood" />1/{selectedReturnPeriod.toLocaleString('en-US')} horizontal exposure</span>
        {view !== 'baseline' && <span><i className="legend-unavailable" />Declared unavailable</span>}
        {view !== 'baseline' && resolvedRoadworks.features.length > 0 && <span><i className="legend-roadworks"><Construction size={10} /></i>Roadworks</span>}
        {view !== 'baseline' && (resolvedReachableNetwork.features.length > 0 || (reachableRoutes?.features.length ?? 0) > 0) && <span><i className="legend-route" />Directed reachable set / retained path</span>}
        {view === 'disrupted' && resolvedFrontierLinks.features.length > 0 && <span><i className="legend-frontier" />Learned-clause frontier</span>}
        {view === 'disrupted' && counterexampleRoute && <span><i className="legend-witness" />Diagnostic route</span>}
        {view === 'disrupted' && resolvedRepairLinks.features.length > 0 && <span><i className="legend-repair" />Z3 candidate · not verified</span>}
        {view === 'verified' && <span><i className="legend-repair" />Checked continuity commitment</span>}
        <span><i className="legend-origin">O</i>Origin</span>
        <span><i className="legend-destination">D</i>Destination</span>
      </div>

      <div className="resilience-map__attribution">
        {dataAttribution} ·{' '}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          © OpenStreetMap contributors · ODbL
        </a>
      </div>
    </section>
  )
}
