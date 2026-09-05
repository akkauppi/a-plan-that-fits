import { useEffect, useMemo, useRef, useState } from 'react'
import type { FeatureCollection, LineString, MultiLineString, Point, Polygon, MultiPolygon } from 'geojson'
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type MapGeoJSONFeature,
  type StyleSpecification,
} from 'maplibre-gl'
import { Crosshair, LocateFixed, ShieldCheck, TriangleAlert, UsersRound } from 'lucide-react'
import type {
  ServiceCandidateSite,
  ServiceCoverageAssignment,
  ServiceCoverageAttributionSource,
  ServiceCoverageScenario,
  ServiceCoverageStatus,
  ServiceSiteConstraint,
  ServiceSiteLoad,
} from './ServiceCoverageTypes'
import './ServiceCoverageMap.css'

export type ServiceCoverageMapView = 'demand' | 'assignment'

interface ServiceCoverageMapProps {
  scenario: ServiceCoverageScenario
  assignments?: ServiceCoverageAssignment[]
  selectedSiteIds?: string[]
  siteLoads?: ServiceSiteLoad[]
  forcedSiteIds?: string[]
  bannedSiteIds?: string[]
  witnessCellId?: string
  view: ServiceCoverageMapView
  onViewChange: (view: ServiceCoverageMapView) => void
  onSiteSelect?: (site: ServiceCandidateSite) => void
  solving?: boolean
  resultStatus?: ServiceCoverageStatus
  statusMessage?: string
  iteration?: number
}

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

const MAP_STYLE: StyleSpecification = {
  version: 8,
  name: 'Service coverage evidence canvas',
  sources: {},
  layers: [{ id: 'coverage-paper', type: 'background', paint: { 'background-color': '#edf0eb' } }],
}

function addCoverageLayers(map: MapLibreMap): void {
  map.addSource('coverage-buildings', { type: 'geojson', data: EMPTY })
  map.addSource('coverage-cells', { type: 'geojson', data: EMPTY })
  map.addSource('coverage-network', { type: 'geojson', data: EMPTY })
  map.addSource('coverage-routes', { type: 'geojson', data: EMPTY })

  map.addLayer({
    id: 'coverage-buildings',
    type: 'fill',
    source: 'coverage-buildings',
    paint: { 'fill-color': '#d9ddd6', 'fill-opacity': 0.72 },
  })
  map.addLayer({
    id: 'coverage-cells-fill',
    type: 'fill',
    source: 'coverage-cells',
    paint: {
      'fill-color': [
        'case',
        ['==', ['get', 'witness'], true], '#d74370',
        ['==', ['get', 'assigned'], true], '#5b9b91',
        ['interpolate', ['linear'], ['coalesce', ['get', 'population'], 0], 0, '#e9e9df', 80, '#bfcec6', 250, '#73958d', 500, '#315f5b'],
      ],
      'fill-opacity': [
        'case',
        ['==', ['get', 'witness'], true], 0.58,
        ['==', ['get', 'assigned'], true], 0.38,
        0.6,
      ],
    },
  })
  map.addLayer({
    id: 'coverage-cells-edge',
    type: 'line',
    source: 'coverage-cells',
    paint: {
      'line-color': ['case', ['==', ['get', 'witness'], true], '#a72d56', '#75827d'],
      'line-width': ['case', ['==', ['get', 'witness'], true], 2.8, 0.65],
      'line-opacity': 0.8,
    },
  })
  map.addLayer({
    id: 'coverage-cells-point',
    type: 'circle',
    source: 'coverage-cells',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['coalesce', ['get', 'population'], 0], 0, 5, 500, 14],
      'circle-color': ['case', ['==', ['get', 'witness'], true], '#d74370', ['==', ['get', 'assigned'], true], '#5b9b91', '#73958d'],
      'circle-opacity': 0.72,
      'circle-stroke-color': '#fffdf8',
      'circle-stroke-width': 2,
    },
  })
  map.addLayer({
    id: 'coverage-network',
    type: 'line',
    source: 'coverage-network',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#707a76',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.65, 16, 2.1],
      'line-opacity': 0.48,
    },
  })
  map.addLayer({
    id: 'coverage-routes-halo',
    type: 'line',
    source: 'coverage-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#fffdf6',
      'line-width': ['interpolate', ['linear'], ['zoom'], 11, 4.8, 16, 8],
      'line-opacity': 0.88,
    },
  })
  map.addLayer({
    id: 'coverage-routes',
    type: 'line',
    source: 'coverage-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ['case', ['==', ['get', 'worst'], true], '#d74370', '#2458a5'],
      'line-width': ['case', ['==', ['get', 'worst'], true], 4.2, 2.1],
      'line-opacity': ['case', ['==', ['get', 'worst'], true], 0.98, 0.56],
      'line-dasharray': ['case', ['==', ['get', 'worst'], true], ['literal', [0.7, 0.65]], ['literal', [1, 0]]],
    },
  })
  map.addLayer({
    id: 'coverage-cell-hit',
    type: 'fill',
    source: 'coverage-cells',
    paint: { 'fill-color': '#000', 'fill-opacity': 0.001 },
  })
  map.addLayer({
    id: 'coverage-cell-point-hit',
    type: 'circle',
    source: 'coverage-cells',
    paint: { 'circle-radius': 15, 'circle-color': '#000', 'circle-opacity': 0.001 },
  })
}

function source(map: MapLibreMap, id: string): GeoJSONSource | undefined {
  return map.getSource(id) as GeoJSONSource | undefined
}

function demandFeatures(
  scenario: ServiceCoverageScenario,
  assignments: ServiceCoverageAssignment[],
  witnessCellId?: string,
): FeatureCollection<Point | Polygon | MultiPolygon> {
  const assignmentByCell = new Map(assignments.map((assignment) => [assignment.demand_cell_id, assignment]))
  return {
    type: 'FeatureCollection',
    features: scenario.population_cells.map((cell) => {
      const assignment = assignmentByCell.get(cell.id)
      return {
        ...cell.feature,
        id: cell.id,
        properties: {
          ...(cell.feature.properties ?? {}),
          id: cell.id,
          label: cell.label,
          district: cell.district,
          population: cell.population,
          assigned: Boolean(assignment),
          assigned_site_id: assignment?.site_id ?? '',
          distance_m: assignment?.distance_m ?? null,
          witness: cell.id === witnessCellId,
        },
      }
    }),
  }
}

function routeFeatures(assignments: ServiceCoverageAssignment[]): FeatureCollection<LineString | MultiLineString> {
  const distances = assignments.map((assignment) => assignment.distance_m)
  const worstDistance = distances.length ? Math.max(...distances) : -1
  return {
    type: 'FeatureCollection',
    features: assignments.flatMap((assignment, index) => {
      if (!assignment.route) return []
      return [{
        ...assignment.route,
        id: assignment.route.id ?? `${assignment.demand_cell_id}-${assignment.site_id}-${index}`,
        properties: {
          ...(assignment.route.properties ?? {}),
          demand_cell_id: assignment.demand_cell_id,
          site_id: assignment.site_id,
          distance_m: assignment.distance_m,
          worst: assignment.distance_m === worstDistance,
        },
      }]
    }),
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character] ?? character)
}

function cellPopup(properties: Record<string, unknown>): string {
  const population = Number(properties.population ?? 0).toLocaleString('en')
  const rawDistance = properties.distance_m
  const distance = Number(rawDistance)
  const assignment = rawDistance != null && Number.isFinite(distance)
    ? `${Math.round(distance).toLocaleString('en')} m modelled walking assignment, including snap connectors`
    : 'Not assigned in the visible solver state'
  return `<span>Included population cell</span><strong>${escapeHtml(String(properties.label ?? properties.id ?? 'Demand cell'))}</strong><small>${population} residents · ${escapeHtml(assignment)}</small>`
}

function isOpenStreetMapSource(source: ServiceCoverageAttributionSource): boolean {
  return /openstreetmap|\bosm\b/i.test(`${source.label} ${source.url}`)
}

function compactAttributionLabel(source: ServiceCoverageAttributionSource): string {
  const label = /hsy/i.test(source.label)
    ? 'HSY population grid'
    : /service map/i.test(source.label)
      ? 'Service Map candidates'
      : source.label
  const licence = /creative commons attribution 4\.0/i.test(source.licence)
    ? 'CC BY 4.0'
    : source.licence
  return `${label} · ${licence}`
}

// Exported for focused accessibility tests.
// eslint-disable-next-line react-refresh/only-export-components
export function serviceSiteAriaLabel(
  site: ServiceCandidateSite,
  constraint: ServiceSiteConstraint,
  selected: boolean,
  load?: ServiceSiteLoad,
  interactive = true,
): string {
  const state = constraint === 'forced'
    ? 'forced selected'
    : constraint === 'banned'
      ? 'excluded from the solver'
      : !site.eligible
        ? 'not eligible for selection'
      : selected
        ? 'selected by the current assignment'
        : 'available candidate'
  const capacity = site.capacity_status === 'observed' ? 'recorded capacity' : 'analytical capacity assumption'
  const loadDetail = load
    ? `. ${Math.round(load.assigned_population).toLocaleString('en')} of ${Math.round(load.effective_capacity).toLocaleString('en')} assigned capacity, ${Math.round(load.utilisation * 100)} percent utilised`
    : ''
  const action = interactive ? '. Activate to inspect and change this candidate' : ''
  return `${site.label}, ${site.category}, ${state}. ${Math.round(site.capacity_default).toLocaleString('en')} ${capacity}${loadDetail}${action}`
}

// Exported for focused state-language tests.
// eslint-disable-next-line react-refresh/only-export-components
export function serviceCoverageMapStatus(
  solving: boolean,
  resultStatus: ServiceCoverageStatus | undefined,
  assignmentCount: number,
): { heading: string; tone: 'solving' | 'verified' | 'unsat' | 'indeterminate' | 'candidate' } {
  if (solving) return { heading: 'Solving', tone: 'solving' }
  if (resultStatus === 'verified_optimal') return { heading: 'Verified assignment', tone: 'verified' }
  if (resultStatus === 'verified_unsat') return { heading: 'Infeasible assumptions', tone: 'unsat' }
  if (resultStatus === 'timeout' || resultStatus === 'cancelled' || resultStatus === 'data_error') {
    return { heading: 'Indeterminate', tone: 'indeterminate' }
  }
  return assignmentCount
    ? { heading: 'Candidate assignment', tone: 'candidate' }
    : { heading: 'Analysis status', tone: 'candidate' }
}

export function ServiceCoverageMap({
  scenario,
  assignments = [],
  selectedSiteIds = [],
  siteLoads = [],
  forcedSiteIds = [],
  bannedSiteIds = [],
  witnessCellId,
  view,
  onViewChange,
  onSiteSelect,
  solving = false,
  resultStatus,
  statusMessage,
  iteration,
}: ServiceCoverageMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markersRef = useRef<maplibregl.Marker[]>([])
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [rendered, setRendered] = useState(false)
  const cells = useMemo(
    () => demandFeatures(scenario, view === 'assignment' ? assignments : [], witnessCellId),
    [assignments, scenario, view, witnessCellId],
  )
  const routes = useMemo(
    () => view === 'assignment' ? routeFeatures(assignments) : EMPTY,
    [assignments, view],
  )
  const selectedSet = useMemo(() => new Set(selectedSiteIds), [selectedSiteIds])
  const forcedSet = useMemo(() => new Set(forcedSiteIds), [forcedSiteIds])
  const bannedSet = useMemo(() => new Set(bannedSiteIds), [bannedSiteIds])
  const loadBySite = useMemo(() => new Map(siteLoads.map((load) => [load.site_id, load])), [siteLoads])
  const totalPopulation = scenario.population_cells.reduce((sum, cell) => sum + cell.population, 0)
  const assignedPopulation = assignments.reduce((sum, assignment) => sum + assignment.population, 0)
  const worstDistance = assignments.length ? Math.max(...assignments.map((assignment) => assignment.distance_m)) : undefined
  const mapStatus = serviceCoverageMapStatus(solving, resultStatus, assignments.length)
  const contextualAttribution = scenario.attribution_sources.filter((item) => !isOpenStreetMapSource(item))

  useEffect(() => {
    if (!containerRef.current || typeof WebGLRenderingContext === 'undefined') return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: scenario.center,
      zoom: 12.7,
      minZoom: 9,
      maxZoom: 19,
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 100 }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({
      compact: true,
      customAttribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a>',
    }), 'bottom-right')
    map.once('load', () => {
      addCoverageLayers(map)
      map.fitBounds([[scenario.bbox[0], scenario.bbox[1]], [scenario.bbox[2], scenario.bbox[3]]], {
        padding: { top: 80, right: 70, bottom: 95, left: 70 },
        duration: 0,
      })
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: 'coverage-popup' })
      popupRef.current = popup
      const showCellPopup = (event: maplibregl.MapLayerMouseEvent) => {
        map.getCanvas().style.cursor = 'help'
        const feature = event.features?.[0] as MapGeoJSONFeature | undefined
        if (feature) popup.setLngLat(event.lngLat).setHTML(cellPopup(feature.properties)).addTo(map)
      }
      const hideCellPopup = () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      }
      map.on('mousemove', 'coverage-cell-hit', showCellPopup)
      map.on('mousemove', 'coverage-cell-point-hit', showCellPopup)
      map.on('mouseleave', 'coverage-cell-hit', hideCellPopup)
      map.on('mouseleave', 'coverage-cell-point-hit', hideCellPopup)
      setLoaded(true)
      map.once('idle', () => setRendered(true))
    })
    return () => {
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      popupRef.current?.remove()
      popupRef.current = null
      map.remove()
      mapRef.current = null
      setLoaded(false)
      setRendered(false)
    }
  }, [scenario])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    source(map, 'coverage-buildings')?.setData(scenario.buildings ?? EMPTY)
    source(map, 'coverage-network')?.setData(scenario.network)
    source(map, 'coverage-cells')?.setData(cells)
    source(map, 'coverage-routes')?.setData(routes)
    map.setLayoutProperty('coverage-routes-halo', 'visibility', view === 'assignment' ? 'visible' : 'none')
    map.setLayoutProperty('coverage-routes', 'visibility', view === 'assignment' ? 'visible' : 'none')
  }, [cells, loaded, routes, scenario, view])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    markersRef.current.forEach((marker) => marker.remove())
    markersRef.current = scenario.candidate_sites.map((site) => {
      const selected = selectedSet.has(site.id)
      const constraint: ServiceSiteConstraint = forcedSet.has(site.id)
        ? 'forced'
        : bannedSet.has(site.id)
          ? 'banned'
          : 'free'
      const load = loadBySite.get(site.id)
      const shell = document.createElement('div')
      shell.className = 'coverage-site-marker-shell'
      const button = document.createElement('button')
      button.type = 'button'
      button.className = [
        'coverage-site-marker',
        selected ? 'is-selected' : '',
        constraint === 'forced' ? 'is-forced' : '',
        constraint === 'banned' ? 'is-banned' : '',
        !site.eligible ? 'is-ineligible' : '',
      ].filter(Boolean).join(' ')
      const utilisation = Math.min(1, Math.max(0, load?.utilisation ?? 0))
      button.style.setProperty('--coverage-load', `${Math.round(utilisation * 360)}deg`)
      button.setAttribute('aria-label', serviceSiteAriaLabel(site, constraint, selected, load, Boolean(onSiteSelect)))
      button.disabled = !onSiteSelect
      button.innerHTML = `<span aria-hidden="true">${constraint === 'banned' ? '×' : selected ? '✓' : 'S'}</span>`
      button.addEventListener('click', () => onSiteSelect?.(site))
      shell.append(button)
      return new maplibregl.Marker({ element: shell, anchor: 'center' }).setLngLat(site.point).addTo(map)
    })
  }, [bannedSet, forcedSet, loadBySite, loaded, onSiteSelect, scenario.candidate_sites, selectedSet])

  const recenter = () => mapRef.current?.fitBounds(
    [[scenario.bbox[0], scenario.bbox[1]], [scenario.bbox[2], scenario.bbox[3]]],
    { padding: 70, duration: 500 },
  )

  return (
    <div className="service-coverage-map" data-map-ready={rendered ? 'true' : 'false'}>
      <div ref={containerRef} className="service-coverage-map__canvas" aria-label={`${scenario.name} walking-network service coverage map`} />
      <div className="service-coverage-map__grain" aria-hidden="true" />

      <dl className="service-coverage-map__context" aria-label="Visible map summary">
        <div><dt>Included population</dt><dd>{Math.round(totalPopulation).toLocaleString('en')}</dd></div>
        <div><dt>{view === 'assignment' ? 'Assigned' : 'Grid cells'}</dt><dd>{view === 'assignment' ? Math.round(assignedPopulation).toLocaleString('en') : scenario.population_cells.length}</dd></div>
        <div><dt>Selected sites</dt><dd>{selectedSiteIds.length || '—'}</dd></div>
        <div><dt>Worst distance</dt><dd>{worstDistance == null ? '—' : `${Math.round(worstDistance).toLocaleString('en')} m`}</dd></div>
        <code>{scenario.snapshot_id}</code>
      </dl>

      <div className="service-coverage-map__views" role="group" aria-label="Map evidence view">
        <button type="button" className={view === 'demand' ? 'is-active' : ''} aria-pressed={view === 'demand'} onClick={() => onViewChange('demand')}>Demand</button>
        <button type="button" className={view === 'assignment' ? 'is-active' : ''} aria-pressed={view === 'assignment'} onClick={() => onViewChange('assignment')} disabled={!assignments.length}>Assignments</button>
      </div>

      <button type="button" className="service-coverage-map__recenter" onClick={recenter} aria-label="Recenter study area"><LocateFixed size={16} /></button>

      {(solving || statusMessage) && (
        <div className={`service-coverage-map__status is-${mapStatus.tone}`} role="status" aria-live="polite">
          <span>{mapStatus.tone === 'solving' ? <Crosshair size={16} /> : mapStatus.tone === 'verified' ? <ShieldCheck size={16} /> : mapStatus.tone === 'unsat' || mapStatus.tone === 'indeterminate' ? <TriangleAlert size={16} /> : <UsersRound size={16} />}</span>
          <p><strong>{mapStatus.tone === 'solving' && iteration ? `${mapStatus.heading} · event ${iteration}` : mapStatus.heading}</strong><small>{statusMessage ?? 'Map updated from the latest solver event.'}</small></p>
        </div>
      )}

      <div className="service-coverage-map__legend" aria-label="Map legend">
        <span><i className="coverage-legend__cell" />Population cell</span>
        <span><i className="coverage-legend__site">S</i>Candidate site</span>
        <span><i className="coverage-legend__selected">✓</i>Selected + capacity load</span>
        <span><i className="coverage-legend__route" />Assignment route</span>
        <span><i className="coverage-legend__witness" />Worst / uncovered witness</span>
      </div>

      <div className="service-coverage-map__attribution" aria-label="Derived map data attribution">
        <strong>Derived / modified for this experiment</strong>
        {contextualAttribution.map((item) => (
          <a key={`${item.label}-${item.url}`} href={item.url} target="_blank" rel="noreferrer" aria-label={`${item.label}; licence ${item.licence}`}>
            {compactAttributionLabel(item)}
          </a>
        ))}
      </div>
    </div>
  )
}
