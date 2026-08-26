import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap, type MapMouseEvent, type StyleSpecification } from 'maplibre-gl'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import { Crosshair, Layers3, LocateFixed } from 'lucide-react'
import type { Candidate, Scenario, SolveResult } from '../types'

const BLANK_STYLE: StyleSpecification = {
  version: 8,
  name: 'Four Planters analytical canvas',
  sources: {},
  layers: [{ id: 'paper', type: 'background', paint: { 'background-color': '#f3f0e9' } }],
}

function fc(features: Feature[]): FeatureCollection {
  return { type: 'FeatureCollection', features }
}

function pointFeatures(scenario: Scenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: scenario.candidates.map((candidate) => ({
      type: 'Feature',
      id: candidate.id,
      properties: {
        id: candidate.id,
        street: candidate.street_name,
        eligible: candidate.eligible,
      },
      geometry: { type: 'Point', coordinates: candidate.point },
    })),
  }
}

function candidateFeatures(
  scenario: Scenario,
  selected: Set<string>,
  forced: Set<string>,
  locked: Set<string>,
  comparison: Set<string>,
): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: scenario.candidates.map((candidate) => ({
      type: 'Feature',
      id: candidate.id,
      properties: {
        id: candidate.id,
        street: candidate.street_name,
        eligible: candidate.eligible,
        selected: selected.has(candidate.id) || forced.has(candidate.id),
        forced: forced.has(candidate.id),
        locked: locked.has(candidate.id),
        comparison: comparison.has(candidate.id),
      },
      geometry: candidate.cross_geometry,
    })),
  }
}

function portalFeatures(scenario: Scenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: scenario.portals.map((portal, index) => ({
      type: 'Feature',
      id: portal.id,
      properties: { id: portal.id, label: portal.label, direction: portal.direction, number: index + 1 },
      geometry: { type: 'Point', coordinates: portal.point },
    })),
  }
}

function addressFeatures(scenario: Scenario, unserved: Set<string>): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: scenario.address_clusters.map((cluster) => ({
      type: 'Feature',
      id: cluster.id,
      properties: {
        id: cluster.id,
        label: cluster.label,
        unserved: unserved.has(cluster.id),
      },
      geometry: { type: 'Point', coordinates: cluster.point },
    })),
  }
}

function routeFeature(value?: Feature<LineString> | LineString | number[][]): FeatureCollection<LineString> {
  if (!value) return { type: 'FeatureCollection', features: [] }
  if (Array.isArray(value)) {
    return fc([{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: value } }]) as FeatureCollection<LineString>
  }
  if (value.type === 'Feature') return fc([value]) as FeatureCollection<LineString>
  return fc([{ type: 'Feature', properties: {}, geometry: value }]) as FeatureCollection<LineString>
}

function setSourceData(map: MapLibreMap, name: string, data: FeatureCollection | Feature): void {
  const source = map.getSource(name) as GeoJSONSource | undefined
  if (source) source.setData(data)
}

function sourceFeatureCollection(value?: FeatureCollection): FeatureCollection {
  return value ?? { type: 'FeatureCollection', features: [] }
}

function addAnalysisLayers(map: MapLibreMap, scenario: Scenario): void {
  map.addSource('boundary', { type: 'geojson', data: scenario.boundary })
  map.addSource('buildings', { type: 'geojson', data: scenario.buildings })
  map.addSource('streets', { type: 'geojson', data: scenario.streets })
  map.addSource('protected', { type: 'geojson', data: scenario.protected_corridors })
  map.addSource('addresses', { type: 'geojson', data: addressFeatures(scenario, new Set()) })
  map.addSource('portals', { type: 'geojson', data: portalFeatures(scenario) })
  map.addSource('candidate-bars', { type: 'geojson', data: fc([]) })
  map.addSource('candidate-points', { type: 'geojson', data: pointFeatures(scenario) })
  map.addSource('counterexample', { type: 'geojson', data: fc([]), lineMetrics: true })
  map.addSource('access-routes', { type: 'geojson', data: fc([]) })
  map.addSource('components', { type: 'geojson', data: fc([]) })

  map.addLayer({
    id: 'boundary-wash',
    type: 'fill',
    source: 'boundary',
    paint: { 'fill-color': '#e8e4da', 'fill-opacity': 0.3 },
  })
  map.addLayer({
    id: 'buildings-fill',
    type: 'fill',
    source: 'buildings',
    minzoom: 12,
    paint: {
      'fill-color': '#d8d3c8',
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 12, 0.32, 16, 0.7],
      'fill-outline-color': 'rgba(95,92,84,.16)',
    },
  })
  map.addLayer({
    id: 'network-components',
    type: 'line',
    source: 'components',
    paint: {
      'line-color': ['coalesce', ['get', 'color'], '#4b9991'],
      'line-opacity': 0.28,
      'line-width': 8,
    },
  })
  map.addLayer({
    id: 'streets-casing',
    type: 'line',
    source: 'streets',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#f8f6f0',
      'line-width': [
        'interpolate', ['linear'], ['zoom'], 12, 2.2, 16, 8,
      ],
      'line-opacity': 0.94,
    },
  })
  map.addLayer({
    id: 'streets-line',
    type: 'line',
    source: 'streets',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': [
        'match',
        ['coalesce', ['get', 'highway'], ['get', 'road_class'], ['get', 'class'], 'local'],
        ['primary', 'secondary'], '#77766f',
        ['tertiary'], '#8e8c83',
        ['pedestrian', 'footway', 'path'], '#bbb6aa',
        '#a8a49b',
      ],
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        12, [
          'match', ['coalesce', ['get', 'highway'], ['get', 'road_class'], 'local'],
          ['primary', 'secondary'], 1.8,
          ['tertiary'], 1.35,
          0.8,
        ],
        16, [
          'match', ['coalesce', ['get', 'highway'], ['get', 'road_class'], 'local'],
          ['primary', 'secondary'], 5,
          ['tertiary'], 3.8,
          2.4,
        ],
      ],
      'line-opacity': 0.94,
    },
  })
  map.addLayer({
    id: 'access-routes-line',
    type: 'line',
    source: 'access-routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#34827b', 'line-width': 3, 'line-opacity': 0.72, 'line-dasharray': [1.5, 1.2] },
  })
  map.addLayer({
    id: 'protected-halo',
    type: 'line',
    source: 'protected',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#f3f0e9', 'line-width': 7, 'line-opacity': 0.82 },
  })
  map.addLayer({
    id: 'protected-line',
    type: 'line',
    source: 'protected',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#2358a6', 'line-width': 3.2, 'line-opacity': 0.92 },
  })
  map.addLayer({
    id: 'addresses-dot',
    type: 'circle',
    source: 'addresses',
    minzoom: 14.2,
    paint: {
      'circle-radius': ['case', ['boolean', ['get', 'unserved'], false], 4.5, 2.3],
      'circle-color': ['case', ['boolean', ['get', 'unserved'], false], '#b8453e', '#38847d'],
      'circle-stroke-color': '#f7f4ed',
      'circle-stroke-width': 1.2,
      'circle-opacity': 0.82,
    },
  })
  map.addLayer({
    id: 'counterexample-halo',
    type: 'line',
    source: 'counterexample',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#fffaf1', 'line-width': 8, 'line-opacity': 0.82 },
  })
  map.addLayer({
    id: 'counterexample-line',
    type: 'line',
    source: 'counterexample',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#d84371',
      'line-width': 4,
      'line-opacity': 0.92,
      'line-dasharray': [0.4, 1.15],
    },
  })
  map.addLayer({
    id: 'candidate-hit',
    type: 'circle',
    source: 'candidate-points',
    paint: { 'circle-radius': 12, 'circle-opacity': 0 },
  })
  map.addLayer({
    id: 'candidate-subtle',
    type: 'line',
    source: 'candidate-bars',
    filter: ['all', ['==', ['get', 'selected'], false], ['==', ['get', 'forced'], false], ['==', ['get', 'locked'], false], ['==', ['get', 'comparison'], false]],
    layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#777a74', 'line-width': 2, 'line-opacity': 0.42 },
  })
  map.addLayer({
    id: 'candidate-comparison',
    type: 'line',
    source: 'candidate-bars',
    filter: ['==', ['get', 'comparison'], true],
    layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#276f78', 'line-width': 5.2, 'line-opacity': 0.88, 'line-dasharray': [0.6, 0.45] },
  })
  map.addLayer({
    id: 'candidate-locked-halo',
    type: 'line',
    source: 'candidate-bars',
    filter: ['==', ['get', 'locked'], true],
    layout: { 'line-cap': 'square' },
    paint: { 'line-color': '#f7f4ed', 'line-width': 8, 'line-opacity': 0.96 },
  })
  map.addLayer({
    id: 'candidate-locked',
    type: 'line',
    source: 'candidate-bars',
    filter: ['==', ['get', 'locked'], true],
    layout: { 'line-cap': 'square' },
    paint: { 'line-color': '#272b2d', 'line-width': 2.2, 'line-opacity': 0.92, 'line-dasharray': [1.2, 1.1] },
  })
  map.addLayer({
    id: 'candidate-selected-halo',
    type: 'line',
    source: 'candidate-bars',
    filter: ['==', ['get', 'selected'], true],
    layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#fffaf1', 'line-width': 10, 'line-opacity': 0.96 },
  })
  map.addLayer({
    id: 'candidate-selected',
    type: 'line',
    source: 'candidate-bars',
    filter: ['==', ['get', 'selected'], true],
    layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#ed6a2c', 'line-width': 5.4, 'line-opacity': 1 },
  })
  map.addLayer({
    id: 'boundary-line',
    type: 'line',
    source: 'boundary',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#555a59', 'line-width': 1.6, 'line-opacity': 0.78, 'line-dasharray': [2, 1.5] },
  })
}

interface MapViewProps {
  scenario: Scenario
  selectedIds: string[]
  forcedIds: string[]
  lockedIds: string[]
  highlightedPortalIds: string[]
  comparisonIds?: string[]
  counterexample?: Feature<LineString> | LineString | number[][]
  result?: SolveResult
  selectedCandidate?: Candidate
  onCandidateSelect: (candidate?: Candidate) => void
  viewMode: 'before' | 'after'
  showAccess: boolean
  onShowAccessChange: (value: boolean) => void
  solving: boolean
}

export function MapView({
  scenario,
  selectedIds,
  forcedIds,
  lockedIds,
  highlightedPortalIds,
  comparisonIds = [],
  counterexample,
  result,
  selectedCandidate,
  onCandidateSelect,
  viewMode,
  showAccess,
  onShowAccessChange,
  solving,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | undefined>(undefined)
  const popupRef = useRef<maplibregl.Popup | undefined>(undefined)
  const portalMarkersRef = useRef<maplibregl.Marker[]>([])
  const [loaded, setLoaded] = useState(false)
  const selectedSet = useMemo(() => new Set(viewMode === 'after' ? selectedIds : []), [selectedIds, viewMode])
  const forcedSet = useMemo(() => new Set(forcedIds), [forcedIds])
  const lockedSet = useMemo(() => new Set(lockedIds), [lockedIds])
  const comparisonSet = useMemo(() => new Set(comparisonIds), [comparisonIds])
  const highlightedPortalSet = useMemo(() => new Set(highlightedPortalIds), [highlightedPortalIds])

  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BLANK_STYLE,
      center: scenario.center,
      zoom: 13.8,
      minZoom: 11,
      maxZoom: 19,
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
    })
    mapRef.current = map
    if (import.meta.env.DEV) window.__FOUR_PLANTERS_MAP__ = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 100 }), 'bottom-right')
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a>',
      }),
      'bottom-right',
    )
    map.once('load', () => {
      addAnalysisLayers(map, scenario)
      portalMarkersRef.current = scenario.portals.map((portal, index) => {
        const element = document.createElement('div')
        element.className = 'portal-marker is-minor'
        element.textContent = ''
        element.dataset.portalId = portal.id
        element.title = `${portal.label}${portal.direction ? ` · ${portal.direction}` : ''}`
        element.setAttribute('aria-label', `Portal ${index + 1}: ${portal.label}`)
        return new maplibregl.Marker({ element, anchor: 'center' }).setLngLat(portal.point).addTo(map)
      })
      map.fitBounds([[scenario.bbox[0], scenario.bbox[1]], [scenario.bbox[2], scenario.bbox[3]]], {
        padding: { top: 56, bottom: 64, left: 50, right: 50 },
        duration: 0,
      })
      setLoaded(true)
    })
    return () => {
      popupRef.current?.remove()
      portalMarkersRef.current.forEach((marker) => marker.remove())
      portalMarkersRef.current = []
      map.remove()
      mapRef.current = undefined
      if (import.meta.env.DEV) window.__FOUR_PLANTERS_MAP__ = undefined
      setLoaded(false)
    }
  }, [scenario])

  useEffect(() => {
    portalMarkersRef.current.forEach((marker, index) => {
      const element = marker.getElement()
      const id = element.dataset.portalId ?? ''
      const active = highlightedPortalSet.has(id)
      element.classList.toggle('is-active', active)
      element.classList.toggle('is-minor', !active)
      element.textContent = active ? String(index + 1) : ''
    })
  }, [highlightedPortalSet, loaded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    setSourceData(map, 'candidate-bars', candidateFeatures(scenario, selectedSet, forcedSet, lockedSet, comparisonSet))
  }, [scenario, selectedSet, forcedSet, lockedSet, comparisonSet, loaded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const fallbackRoute = viewMode === 'before' ? scenario.initial_through_route : undefined
    const visibleRoute = counterexample ?? fallbackRoute
    setSourceData(map, 'counterexample', routeFeature(visibleRoute))
    let frame = 0
    if (visibleRoute && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const started = performance.now()
      const draw = (time: number) => {
        const progress = Math.min(1, (time - started) / 620)
        map.setPaintProperty('counterexample-line', 'line-gradient', [
          'step', ['line-progress'], '#d84371', progress, 'rgba(215,67,112,0)',
        ])
        if (progress < 1) frame = window.requestAnimationFrame(draw)
      }
      frame = window.requestAnimationFrame(draw)
    } else {
      map.setPaintProperty('counterexample-line', 'line-gradient', '#d84371')
    }
    return () => window.cancelAnimationFrame(frame)
  }, [counterexample, scenario.initial_through_route, viewMode, loaded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const unserved = new Set(result?.address_access_summary?.unserved_ids ?? [])
    setSourceData(map, 'addresses', addressFeatures(scenario, unserved))
    setSourceData(map, 'access-routes', showAccess ? sourceFeatureCollection(result?.access_routes) : fc([]))
    setSourceData(map, 'components', viewMode === 'after' ? sourceFeatureCollection(result?.components) : fc([]))
  }, [result, scenario, showAccess, viewMode, loaded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const canvas = map.getCanvas()
    const onMove = (event: MapMouseEvent) => {
      const hit = map.queryRenderedFeatures(event.point, { layers: ['candidate-hit'] })[0]
      canvas.style.cursor = hit ? 'pointer' : ''
      if (!hit) {
        popupRef.current?.remove()
        return
      }
      const id = String(hit.properties?.id ?? '')
      const candidate = scenario.candidates.find((item) => item.id === id)
      if (!candidate) return
      popupRef.current?.remove()
      const state = forcedSet.has(id) ? 'Forced filter' : lockedSet.has(id) ? 'Locked open' : selectedSet.has(id) ? 'Selected filter' : 'Candidate'
      popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 15, className: 'fp-map-tooltip' })
        .setLngLat(candidate.point)
        .setHTML(`<strong>${escapeHtml(candidate.street_name)}</strong><span>${state}</span>`)
        .addTo(map)
    }
    const onClick = (event: MapMouseEvent) => {
      const hit = map.queryRenderedFeatures(event.point, { layers: ['candidate-hit'] })[0]
      if (!hit) {
        onCandidateSelect(undefined)
        return
      }
      const id = String(hit.properties?.id ?? '')
      onCandidateSelect(scenario.candidates.find((candidate) => candidate.id === id))
    }
    map.on('mousemove', onMove)
    map.on('click', onClick)
    return () => {
      map.off('mousemove', onMove)
      map.off('click', onClick)
    }
  }, [forcedSet, loaded, lockedSet, onCandidateSelect, scenario.candidates, selectedSet])

  const recenter = () => {
    mapRef.current?.fitBounds([[scenario.bbox[0], scenario.bbox[1]], [scenario.bbox[2], scenario.bbox[3]]], {
      padding: 52,
      duration: 550,
    })
  }

  return (
    <div className="map-shell" aria-label={`Interactive map of ${scenario.name}`}>
      <div className="map-canvas" ref={containerRef} />
      <div className="map-grain" aria-hidden="true" />
      <div className="map-context" aria-live="polite">
        <span className="map-context__eyebrow">Study area · Helsinki</span>
        <strong>{scenario.name}</strong>
        <span>{scenario.candidates.filter((candidate) => candidate.eligible).length} eligible street segments</span>
      </div>
      <div className="map-tools" aria-label="Map display controls">
        <button type="button" className="map-tool" onClick={recenter} aria-label="Recenter study area" title="Recenter study area">
          <LocateFixed size={17} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`map-tool ${showAccess ? 'is-active' : ''}`}
          onClick={() => onShowAccessChange(!showAccess)}
          aria-pressed={showAccess}
          aria-label="Show verified local access routes"
          title="Local access routes"
          disabled={!result}
        >
          <Layers3 size={17} aria-hidden="true" />
        </button>
      </div>
      {solving && (
        <div className="map-solving" role="status">
          <span className="map-solving__mark"><Crosshair size={15} aria-hidden="true" /></span>
          Verifying network paths
        </div>
      )}
      {selectedCandidate && (
        <div className="map-selection-label" aria-live="polite">
          <span>Selected street</span>
          <strong>{selectedCandidate.street_name}</strong>
        </div>
      )}
    </div>
  )
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
