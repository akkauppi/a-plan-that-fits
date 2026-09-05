import type { Map as MapLibreMap } from 'maplibre-gl'

declare global {
  interface Window {
    __GEOSPATIAL_LAB_MAP__?: MapLibreMap
  }
}

export {}
