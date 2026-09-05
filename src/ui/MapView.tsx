import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import type { FeatureCollection, Geometry } from 'geojson'
import type { NetworkPlan, Scenario } from '../core/types.ts'
import 'maplibre-gl/dist/maplibre-gl.css'

const collection = (features: FeatureCollection['features']): FeatureCollection => ({ type: 'FeatureCollection', features })
const feature = (geometry: Geometry, properties = {}) => ({ type: 'Feature' as const, geometry, properties })

interface Props {
  scenario: Scenario
  plan?: NetworkPlan
  selectedLockers: string[]
  selectedDepots: string[]
  cellId: string
  onCell: (id: string) => void
  onLocker: (id: string) => void
  onDepot: (id: string) => void
  canChooseLockers: boolean
  canChooseDepots: boolean
  maxSelectedLockers: number
  maxSelectedDepots: number
  gameMode: boolean
  showStarterAssignments: boolean
}
export function MapView({ scenario, plan, selectedLockers, selectedDepots, cellId, onCell, onLocker, onDepot, canChooseLockers, canChooseDepots, maxSelectedLockers, maxSelectedDepots, gameMode, showStarterAssignments }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | undefined>(undefined)
  const [loaded, setLoaded] = useState(false)
  const [mapError, setMapError] = useState('')
  const callbacks = useRef({ onCell, onLocker, onDepot })
  callbacks.current = { onCell, onLocker, onDepot }
  const assignments = plan?.assignments ?? (showStarterAssignments ? scenario.starterAssignments : [])
  const activeLockers = plan?.lockerIds ?? selectedLockers
  const activeDepots = plan?.depotIds ?? selectedDepots
  const assignment = assignments.find(a => a.cellId === cellId)
  const previewPair = !assignment && gameMode
    ? scenario.walking.filter(pair => pair.cellId === cellId && activeLockers.includes(pair.lockerId)).sort((a, b) => a.distanceMm - b.distanceMm)[0]
    : undefined
  const pair = previewPair ?? scenario.walking.find(p => p.cellId === cellId && p.lockerId === assignment?.lockerId)
  const supply = plan?.supplies.find(s => s.lockerId === assignment?.lockerId)
  const cell = scenario.cells.find(c => c.id === cellId)!
  const walkCoordinates = useMemo(() => {
    if (!pair) return []
    const edges = new Map(scenario.network.edges.map(e => [e.id, e]))
    const node = scenario.network.nodes.find(n => n.id === cell.nodeId)!
    return [cell.point, node.point, ...pair.edgeIds.flatMap(id => edges.get(id)!.coordinates)]
  }, [scenario, pair, cell])

  useEffect(() => {
    if (!container.current) return
    let instance: maplibregl.Map
    try {
      instance = new maplibregl.Map({ container: container.current, center: scenario.center, zoom: 13.8, attributionControl: false,
        style: { version: 8, sources: {}, layers: [{ id: 'paper', type: 'background', paint: { 'background-color': '#f4f2e9' } }] },
      })
    } catch { setMapError('The map could not start (WebGL is unavailable). The tour, site controls and route details still work.'); return }
    map.current = instance
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    instance.addControl(new maplibregl.ScaleControl({ maxWidth: 100 }), 'bottom-left')
    instance.on('load', () => {
      instance.addSource('streets', { type: 'geojson', data: collection(scenario.network.edges.filter(e => !e.id.endsWith('-r')).map(e => feature({ type: 'LineString', coordinates: e.coordinates }))) })
      instance.addLayer({ id: 'streets', type: 'line', source: 'streets', paint: { 'line-color': '#b9bdb7', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 0.65, 17, 2], 'line-opacity': 0.65 } })
      instance.addSource('cells', { type: 'geojson', data: collection(scenario.cells.map(c => feature({ type: 'Polygon', coordinates: c.polygon }, { id: c.id }))) })
      instance.addLayer({ id: 'cells-fill', type: 'fill', source: 'cells', paint: { 'fill-color': ['case', ['==', ['get', 'covered'], false], '#d46b43', '#228b78'], 'fill-opacity': ['case', ['==', ['get', 'covered'], false], 0.32, 0.13] } })
      instance.addLayer({ id: 'cells-outline', type: 'line', source: 'cells', paint: { 'line-color': '#228b78', 'line-opacity': 0.35, 'line-width': 1 } })
      instance.addSource('selected-cell', { type: 'geojson', data: collection([]) })
      instance.addLayer({ id: 'selected-cell', type: 'line', source: 'selected-cell', paint: { 'line-color': '#155d50', 'line-width': 2.5 } })
      instance.addSource('walk', { type: 'geojson', data: collection([]) })
      instance.addLayer({ id: 'walk-halo', type: 'line', source: 'walk', paint: { 'line-color': '#fff', 'line-width': 8 } })
      instance.addLayer({ id: 'walk', type: 'line', source: 'walk', paint: { 'line-color': '#176bab', 'line-width': 4 } })
      instance.addSource('supply', { type: 'geojson', data: collection([]) })
      instance.addLayer({ id: 'supply', type: 'line', source: 'supply', paint: { 'line-color': '#ac5d30', 'line-width': 2.5, 'line-dasharray': [3, 2] } })
      instance.on('click', 'cells-fill', event => { const id = event.features?.[0]?.properties.id; if (typeof id === 'string') callbacks.current.onCell(id) })
      instance.on('mouseenter', 'cells-fill', () => { instance.getCanvas().style.cursor = 'pointer' })
      instance.on('mouseleave', 'cells-fill', () => { instance.getCanvas().style.cursor = '' })
      const bounds = new maplibregl.LngLatBounds()
      for (const site of [...scenario.depots, ...scenario.lockers]) bounds.extend(site.point)
      for (const c of scenario.cells) for (const p of c.polygon[0]) bounds.extend(p)
      instance.fitBounds(bounds, { padding: { top: 100, bottom: 245, left: 50, right: 55 }, duration: 0 })
      setLoaded(true)
    })
    instance.on('error', () => setMapError('A map layer failed to render. Use the site controls and route details to continue.'))
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(container.current)
    return () => { observer.disconnect(); instance.remove(); map.current = undefined; setLoaded(false) }
  }, [scenario])

  useEffect(() => {
    if (!loaded || !map.current) return
    const instance = map.current
    const markers: maplibregl.Marker[] = []
    for (const locker of scenario.lockers) {
      const selected = activeLockers.includes(locker.id)
      const showSupplyReach = gameMode && activeDepots.length > 0
      const withinSelectedDepotRange = activeDepots.some(depotId => scenario.flights.some(pair => pair.lockerId === locker.id && pair.depotId === depotId && pair.returnDistanceMm <= scenario.defaults.flightLimitMm))
      const reachDescription = activeDepots.length === 0
        ? 'choose a depot to see supply reach'
        : withinSelectedDepotRange ? 'within range of a selected depot' : 'outside all selected depots\' 2 km return range'
      const element = document.createElement('button')
      element.className = `map-locker ${selected ? 'active' : ''} ${showSupplyReach && !withinSelectedDepotRange ? 'out-of-depot-range' : ''}`
      element.textContent = locker.id
      const assignedRoute = assignments.find(a => a.lockerId === locker.id)
      element.disabled = gameMode ? !canChooseLockers || (!selected && activeLockers.length >= maxSelectedLockers) : !assignedRoute
      element.setAttribute('aria-label', gameMode ? `Map locker ${locker.id}: ${selected ? 'selected' : 'not selected'}; ${reachDescription}` : `Map locker ${locker.id}: ${assignedRoute ? 'inspect its collection route' : 'candidate, not open'}`)
      element.setAttribute('aria-pressed', gameMode ? String(selected) : 'false')
      if (showSupplyReach) element.dataset.supplyReach = withinSelectedDepotRange ? 'within-range' : 'out-of-range'
      element.title = `${locker.label}${selected ? ' · open' : ' · candidate'}${gameMode ? ` · ${reachDescription}` : ''}`
      element.onclick = () => {
        if (gameMode) callbacks.current.onLocker(locker.id)
        else if (assignedRoute) callbacks.current.onCell(assignedRoute.cellId)
      }
      markers.push(new maplibregl.Marker({ element }).setLngLat(locker.point).addTo(instance))
    }
    for (const depot of scenario.depots) {
      const element = document.createElement('button')
      element.className = `map-depot ${activeDepots.includes(depot.id) ? 'active' : ''}`
      element.textContent = `◇ ${depot.id}`
      element.setAttribute('aria-label', `Map depot ${depot.id}`)
      element.setAttribute('aria-pressed', String(activeDepots.includes(depot.id)))
      element.disabled = !gameMode || !canChooseDepots || (!activeDepots.includes(depot.id) && activeDepots.length >= maxSelectedDepots)
      element.onclick = () => callbacks.current.onDepot(depot.id)
      markers.push(new maplibregl.Marker({ element }).setLngLat(depot.point).addTo(instance))
    }
    return () => markers.forEach(marker => marker.remove())
  }, [loaded, scenario, activeLockers, activeDepots, assignments, gameMode, canChooseLockers, canChooseDepots, maxSelectedLockers, maxSelectedDepots])

  useEffect(() => {
    if (!loaded || !map.current) return
    const cells = scenario.cells.map(cell => feature({ type: 'Polygon', coordinates: cell.polygon }, {
      id: cell.id,
      covered: !gameMode || scenario.walking.some(pair => pair.cellId === cell.id && activeLockers.includes(pair.lockerId)),
    }))
    ;(map.current.getSource('cells') as maplibregl.GeoJSONSource).setData(collection(cells))
  }, [loaded, scenario, activeLockers, gameMode])

  useEffect(() => {
    if (!loaded || !map.current) return
    const update = (id: string, data: FeatureCollection) => (map.current!.getSource(id) as maplibregl.GeoJSONSource).setData(data)
    update('selected-cell', collection([feature({ type: 'Polygon', coordinates: cell.polygon })]))
    update('walk', collection(walkCoordinates.length ? [feature({ type: 'LineString', coordinates: walkCoordinates })] : []))
    const locker = scenario.lockers.find(l => l.id === supply?.lockerId)
    const depot = scenario.depots.find(d => d.id === supply?.depotId)
    update('supply', collection(locker && depot ? [feature({ type: 'LineString', coordinates: [depot.point, locker.point] })] : []))
  }, [loaded, cell, walkCoordinates, scenario, supply])

  return <section className="map-panel" aria-label="Geographic scenario">
    <div ref={container} className="map-canvas" data-testid="map" />
    <div className="map-caption"><span className="eyebrow">ESPOO, FINLAND</span><strong>Tapiola → Otaniemi</strong><span>Real paths & population · hypothetical sites</span></div>
    <div className="map-key" role="group" aria-label="Map legend"><span><i className="key-cell" />Population cell</span><span><i className="key-locker" />Open locker</span><span><i className="key-candidate" />Candidate</span><span><i className="key-depot" />Supply depot</span>{gameMode && activeDepots.length > 0 && <span><i className="key-out-of-range" />Outside selected depot range</span>}</div>
    {gameMode && <div className="map-game-help" data-testid="map-game-help"><strong>Build directly on the map</strong><span>Click locker circles and depot labels to toggle them. When a budget is full, deselect one before choosing another.</span>{activeDepots.length > 0 && <span className="range-warning">Coral rings mark lockers outside every selected depot’s exact 2 km return-flight range.</span>}</div>}
    {mapError && <p className="map-error" role="alert">{mapError}</p>}
    <div className="route-card">
      <label htmlFor="cell">Inspect a collection journey</label>
      <select id="cell" value={cellId} onChange={event => onCell(event.target.value)}>{scenario.cells.map(c => <option key={c.id} value={c.id}>Cell {c.id.replace('hsy-grid-', '')} · {c.parcels} parcels/day</option>)}</select>
      {pair ? <><div className="journey"><span className="walk-dot" />{previewPair ? 'Possible: ' : ''}{Math.ceil(pair.distanceMm / 1000)} m walk to locker {pair.lockerId}<span className="within-limit">≤ 500 m</span></div>
        <p>Includes a {(cell.connectorMm / 1000).toFixed(1)} m straight connector to the mapped path.</p>
        {supply ? <p className="flight-detail">↔ Supplied by {supply.depotId} · {(scenario.flights.find(f => f.lockerId === supply.lockerId && f.depotId === supply.depotId)!.returnDistanceMm / 1000000).toFixed(2)} km return flight</p> : <p className="not-checked">{previewPair ? 'Possible walk only. The full plan has not been checked.' : 'Collection plan only. Drone supply is not verified.'}</p>}
      </> : <p className="uncovered-route">No selected locker is within 500 m of this cell.</p>}
    </div>
    <div className="attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a><span> · </span><a href="https://hri.fi/data/en/dataset/vaestotietoruudukko" target="_blank" rel="noreferrer">HSY population 2025 · CC BY 4.0</a></div>
  </section>
}
