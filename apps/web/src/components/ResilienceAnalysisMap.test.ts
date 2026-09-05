import { describe, expect, it, vi } from 'vitest'

vi.mock('maplibre-gl', () => ({ default: {} }))

import {
  resilienceLocationAriaLabel,
  type ResilienceMapLocation,
} from './ResilienceAnalysisMap'

const selectedOrigin: ResilienceMapLocation = {
  id: 'origin-1',
  label: 'Keilaniemi address cluster',
  point: [24.828, 60.184],
  kind: 'origin',
  selected: true,
  status: 'stranded',
  detail: '12 address points',
}

describe('resilience map location accessibility', () => {
  it('announces selected state, graph status, evidence detail and toggle action', () => {
    expect(resilienceLocationAriaLabel(selectedOrigin, true)).toBe(
      'Origin: Keilaniemi address cluster, selected for this analysis, stranded in current scenario. 12 address points. Activate to remove this origin from the analysis',
    )
  })

  it('announces how an unselected destination can be added', () => {
    expect(resilienceLocationAriaLabel({
      id: 'gateway-1',
      label: 'Western gateway',
      point: [24.82, 60.18],
      kind: 'destination',
      selected: false,
    }, true)).toBe(
      'Destination: Western gateway, not selected for this analysis. Activate to add this destination to the analysis',
    )
  })

  it('does not invent selection state for legacy location records', () => {
    expect(resilienceLocationAriaLabel({
      id: 'origin-2',
      label: 'Campus origin',
      point: [24.83, 60.18],
      kind: 'origin',
      status: 'reachable',
    })).toBe('Origin: Campus origin, reachable in current scenario')
  })
})
