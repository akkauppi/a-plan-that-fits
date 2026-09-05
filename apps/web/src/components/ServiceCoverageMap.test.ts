import { describe, expect, it, vi } from 'vitest'

vi.mock('maplibre-gl', () => ({ default: {} }))

import { serviceCoverageMapStatus, serviceSiteAriaLabel } from './ServiceCoverageMap'

const site = {
  id: 'site-1',
  label: 'Tapiola library',
  category: 'Library',
  point: [24.8, 60.2] as [number, number],
  eligible: true,
  capacity_default: 300,
  capacity_status: 'declared' as const,
}

describe('service-coverage site map accessibility', () => {
  it('announces analytical capacity and the current load without implying observed capacity', () => {
    expect(serviceSiteAriaLabel(site, 'free', true, {
      site_id: 'site-1',
      assigned_population: 225,
      effective_capacity: 300,
      utilisation: 0.75,
    })).toBe(
      'Tapiola library, Library, selected by the current assignment. 300 analytical capacity assumption. 225 of 300 assigned capacity, 75 percent utilised. Activate to inspect and change this candidate',
    )
  })

  it('announces forced and excluded constraint states', () => {
    expect(serviceSiteAriaLabel(site, 'forced', true)).toContain('forced selected')
    expect(serviceSiteAriaLabel(site, 'banned', false)).toContain('excluded from the solver')
  })

  it('distinguishes verified, infeasible, and indeterminate map states', () => {
    expect(serviceCoverageMapStatus(false, 'verified_optimal', 33)).toEqual({ heading: 'Verified assignment', tone: 'verified' })
    expect(serviceCoverageMapStatus(false, 'verified_unsat', 0)).toEqual({ heading: 'Infeasible assumptions', tone: 'unsat' })
    expect(serviceCoverageMapStatus(false, 'timeout', 0)).toEqual({ heading: 'Indeterminate', tone: 'indeterminate' })
  })
})
