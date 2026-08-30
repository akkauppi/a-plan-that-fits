import { useEffect, useRef } from 'react'
import type { Feature, FeatureCollection, Point, Polygon } from 'geojson'
import type {
  GeoJSONSource,
  Map as MapLibreMap,
  StyleSpecification,
} from 'maplibre-gl'

const EARTH_RADIUS_M = 6_371_008.8

const LOCATOR_STYLE: StyleSpecification = {
  version: 8,
  name: 'Four Planters location picker',
  sources: {},
  layers: [
    { id: 'locator-paper', type: 'background', paint: { 'background-color': '#e5e5de' } },
  ],
}

interface LocationPickerMapProps {
  longitude: number
  latitude: number
  radiusM: number
  onPick: (longitude: number, latitude: number) => void
}

function selectionData(
  longitude: number,
  latitude: number,
  radiusM: number,
): FeatureCollection<Polygon | Point> {
  const angularDistance = radiusM / EARTH_RADIUS_M
  const latitudeRadians = latitude * Math.PI / 180
  const longitudeRadians = longitude * Math.PI / 180
  const ring: number[][] = []
  for (let index = 0; index <= 64; index += 1) {
    const bearing = index / 64 * Math.PI * 2
    const nextLatitude = Math.asin(
      Math.sin(latitudeRadians) * Math.cos(angularDistance)
      + Math.cos(latitudeRadians) * Math.sin(angularDistance) * Math.cos(bearing),
    )
    const nextLongitude = longitudeRadians + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitudeRadians),
      Math.cos(angularDistance) - Math.sin(latitudeRadians) * Math.sin(nextLatitude),
    )
    ring.push([nextLongitude * 180 / Math.PI, nextLatitude * 180 / Math.PI])
  }
  const area: Feature<Polygon> = {
    type: 'Feature',
    properties: { radius_m: radiusM },
    geometry: { type: 'Polygon', coordinates: [ring] },
  }
  const centre: Feature<Point> = {
    type: 'Feature',
    properties: { role: 'centre' },
    geometry: { type: 'Point', coordinates: [longitude, latitude] },
  }
  return { type: 'FeatureCollection', features: [area, centre] }
}

export function LocationPickerMap({
  longitude,
  latitude,
  radiusM,
  onPick,
}: LocationPickerMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onPickRef = useRef(onPick)

  useEffect(() => {
    onPickRef.current = onPick
  }, [onPick])

  useEffect(() => {
    if (!containerRef.current || typeof WebGLRenderingContext === 'undefined') return
    let disposed = false
    let map: MapLibreMap | null = null
    void import('maplibre-gl').then(({ default: maplibregl }) => {
      if (disposed || !containerRef.current) return
      map = new maplibregl.Map({
        container: containerRef.current,
        style: LOCATOR_STYLE,
        center: [longitude, latitude],
        zoom: 12.3,
        minZoom: 4,
        maxZoom: 17,
        attributionControl: false,
        pitchWithRotate: false,
        dragRotate: false,
      })
      mapRef.current = map
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }),
        'top-right',
      )
      map.on('load', () => {
        map?.addSource('selection', {
          type: 'geojson',
          data: selectionData(longitude, latitude, radiusM),
        })
        map?.addLayer({
          id: 'selection-area',
          type: 'fill',
          source: 'selection',
          filter: ['==', ['geometry-type'], 'Polygon'],
          paint: { 'fill-color': '#397f79', 'fill-opacity': 0.18 },
        })
        map?.addLayer({
          id: 'selection-edge',
          type: 'line',
          source: 'selection',
          filter: ['==', ['geometry-type'], 'Polygon'],
          paint: { 'line-color': '#286e68', 'line-width': 2, 'line-dasharray': [2, 1.5] },
        })
        map?.addLayer({
          id: 'selection-centre',
          type: 'circle',
          source: 'selection',
          filter: ['==', ['geometry-type'], 'Point'],
          paint: {
            'circle-radius': 5,
            'circle-color': '#f06b2d',
            'circle-stroke-color': '#fffdf8',
            'circle-stroke-width': 2,
          },
        })
      })
      map.on('click', (event) => {
        onPickRef.current(
          Number(event.lngLat.lng.toFixed(6)),
          Number(event.lngLat.lat.toFixed(6)),
        )
      })
    })
    return () => {
      disposed = true
      mapRef.current = null
      map?.remove()
    }
    // The map is created once. Prop changes update its source below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const update = () => {
      const source = map.getSource('selection') as GeoJSONSource | undefined
      source?.setData(selectionData(longitude, latitude, radiusM))
    }
    if (map.isStyleLoaded()) update()
    else map.once('load', update)
  }, [latitude, longitude, radiusM])

  return (
    <div className="location-picker-map-shell">
      <div
        ref={containerRef}
        className="location-picker-map"
        role="img"
        aria-label={`Location map centred at ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`}
      />
      <span className="location-picker-map__hint">Click map to move centre</span>
      <span className="location-picker-map__scope">Offline coordinate canvas</span>
    </div>
  )
}
