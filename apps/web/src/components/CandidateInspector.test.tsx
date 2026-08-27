import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CandidateInspector } from './CandidateInspector'

describe('CandidateInspector', () => {
  it('labels the projected marker-midpoint distance without rounding it onto the setback', () => {
    render(
      <CandidateInspector
        candidate={{
          id: 'c-1',
          edge_ids: ['e-1'],
          name: 'Testikatu',
          street_name: 'Testikatu',
          point: [24.95, 60.19],
          cross_geometry: {
            type: 'LineString',
            coordinates: [[24.9499, 60.19], [24.9501, 60.19]],
          },
          cost: 1,
          eligible: true,
          boundary_distance_m: 60.4,
          boundary_distance_metric: 'projected_candidate_display_point_to_study_boundary',
          nearest_primary_portal_distance_m: 126.6,
          nearest_primary_portal_distance_metric: 'projected_candidate_display_point_to_nearest_primary_portal_crossing',
          nearest_primary_portal_id: 'p-north-07',
          nearest_primary_portal_crossing_id: 'x-north-07',
        }}
        forced={false}
        locked={false}
        onForce={vi.fn()}
        onLock={vi.fn()}
        onClear={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText(/Filter marker midpoint is 60\.4 m from the analysis boundary and 126\.6 m from the nearest selectable portal crossing/)).toBeInTheDocument()
  })
})
