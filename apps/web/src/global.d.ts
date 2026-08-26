import type { Map as MapLibreMap } from 'maplibre-gl'

declare global {
  interface Window {
    __FOUR_PLANTERS_MAP__?: MapLibreMap
  }
}

export {}
