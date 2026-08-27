import { describe, expect, it, vi } from 'vitest'
import { normalizeScenario, parseEventStream } from './api'

describe('scenario normalization', () => {
  it('preserves stable scenario identifiers and derives canonical candidates', () => {
    const scenario = normalizeScenario({
      id: 'kallio-2026',
      name: 'Kallio',
      bbox: [24.94, 60.18, 24.97, 60.2],
      terminal_zone: {
        type: 'Feature',
        properties: {
          setback_m: 72,
          boundary_distance_metric: 'projected_candidate_display_point_to_study_boundary',
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [24.94, 60.18], [24.97, 60.18], [24.97, 60.2], [24.94, 60.2], [24.94, 60.18],
          ], [
            [24.941, 60.181], [24.941, 60.199], [24.969, 60.199], [24.969, 60.181], [24.941, 60.181],
          ]],
        },
      },
      portal_approach_zones: {
        type: 'Feature',
        properties: {
          setback_m: 120,
          nearest_primary_portal_distance_metric: 'projected_candidate_display_point_to_nearest_primary_portal_crossing',
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [24.94, 60.18], [24.945, 60.18], [24.945, 60.185], [24.94, 60.185], [24.94, 60.18],
          ]],
        },
      },
      portals: [{ id: 'n', label: 'North', direction: 'N', point: [24.95, 60.2] }],
      candidates: [{
        edge_id: 'e-1',
        street_name: 'Testikatu',
        point: [24.95, 60.19],
        boundary_distance_m: 72.4,
        boundary_distance_metric: 'projected_candidate_display_point_to_study_boundary',
        nearest_primary_portal_distance_m: 143.7,
        nearest_primary_portal_distance_metric: 'projected_candidate_display_point_to_nearest_primary_portal_crossing',
        nearest_primary_portal_id: 'n',
        nearest_primary_portal_crossing_id: 'x-n',
      }],
      default_portal_pairs: [['n', 's']],
    })

    expect(scenario.id).toBe('kallio-2026')
    expect(scenario.candidates[0]).toMatchObject({ id: 'e-1', street_name: 'Testikatu', eligible: true })
    expect(scenario.candidates[0]?.cross_geometry.coordinates).toHaveLength(2)
    expect(scenario.candidates[0]?.boundary_distance_m).toBe(72.4)
    expect(scenario.candidates[0]?.nearest_primary_portal_distance_m).toBe(143.7)
    expect(scenario.terminal_zone.properties.setback_m).toBe(72)
    expect(scenario.portal_approach_zones.properties.setback_m).toBe(120)
    expect(scenario.default_portal_pairs[0]).toMatchObject({ a: 'n', b: 's' })
  })

  it('rejects a scenario that omits the boundary-setback geometry', () => {
    expect(() => normalizeScenario({ id: 'incomplete' })).toThrow(
      'Scenario data is missing a valid candidate boundary-setback zone.',
    )
  })
})

describe('solver event stream', () => {
  it('flattens nested payloads and returns the final verified result', async () => {
    const onEvent = vi.fn()
    const body = [
      'event: solve_event\ndata: {"type":"candidate_found","iteration":1,"payload":{"selected_intervention_ids":["c1"]}}\n\n',
      'event: solve_event\ndata: {"type":"counterexample_found","iteration":1,"payload":{"route":{"geometry":{"type":"LineString","coordinates":[[24.9,60.1],[25,60.2]]}}}}\n\n',
      'event: solve_event\ndata: {"type":"complete","payload":{"result":{"status":"verified_optimal","selected_intervention_ids":["c1"],"verification_status":"verified","address_access_summary":{"included_clusters":4,"served_clusters":4,"all_served":true},"iteration_count":2,"timing_ms":25,"solve_id":"solve-1"}}}\n\n',
    ].join('')
    const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })

    const result = await parseEventStream(response, onEvent)

    expect(onEvent).toHaveBeenCalledTimes(3)
    expect(onEvent.mock.calls[0]?.[0].selected_intervention_ids).toEqual(['c1'])
    expect(onEvent.mock.calls[1]?.[0].route).toMatchObject({ type: 'LineString' })
    expect(result?.address_access_summary).toMatchObject({ total: 4, served: 4, all_accessible: true })
    expect(result?.status).toBe('verified_optimal')
  })

  it('normalizes object-shaped UNSAT cores to readable labels', async () => {
    const response = new Response(JSON.stringify({
      status: 'verified_unsat',
      unsat_core: [{ key: 'budget', label: 'Budget is at most four' }, { key: 'locked:e1' }],
    }), { headers: { 'Content-Type': 'application/json' } })
    const result = await parseEventStream(response, vi.fn())
    expect(result?.unsat_core).toEqual(['Budget is at most four', 'locked:e1'])
  })

  it('preserves typed targets in human-readable UNSAT suggestions', async () => {
    const response = new Response(JSON.stringify({
      status: 'verified_unsat',
      suggested_relaxations: [
        { type: 'unlock_street', candidate_id: 42, label: 'Unlock Testikatu' },
        { action: 'remove_portal_pair', pair: { a: 1, b: 'south' }, label: 'Remove the pair' },
        { type: 'increase_budget', value: '6', label: 'Try six' },
      ],
    }), { headers: { 'Content-Type': 'application/json' } })

    const result = await parseEventStream(response, vi.fn())

    expect(result?.suggested_relaxations).toEqual([
      { type: 'unlock_street', candidate_id: '42', label: 'Unlock Testikatu' },
      { action: 'remove_portal_pair', pair: { a: '1', b: 'south' }, label: 'Remove the pair' },
      { type: 'increase_budget', value: 6, label: 'Try six' },
    ])
  })
})
