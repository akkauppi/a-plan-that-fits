import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  cancelServiceCoverageSolve,
  normalizeServiceCoverageEvent,
  normalizeServiceCoverageScenario,
  streamServiceCoverageSolve,
} from './ServiceCoverageApi'

afterEach(() => vi.unstubAllGlobals())

describe('service-coverage API normalization', () => {
  it('normalizes the frozen population and candidate-site evidence', () => {
    const scenario = normalizeServiceCoverageScenario({
      scenario_id: 'espoo-service-v1',
      name: 'Espoo service coverage',
      bbox: [24.7, 60.1, 24.9, 60.3],
      population_cells: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: { id: 'd-1', name: 'Grid 1', population: 124, district: 'Tapiola', centroid: [24.8, 60.2] },
          geometry: { type: 'Polygon', coordinates: [[[24.79, 60.19], [24.81, 60.19], [24.81, 60.21], [24.79, 60.21], [24.79, 60.19]]] },
        }],
      },
      candidate_sites: [{ id: 's-1', name: 'Library', point: [24.8, 60.2], capacity: 200, capacity_status: 'declared' }],
      attribution_sources: [
        { label: 'Population grid: Helsinki Region Environmental Services HSY', licence: 'Creative Commons Attribution 4.0', licence_url: 'https://creativecommons.org/licenses/by/4.0/', modifications: 'Cells selected and snapped; population totals retained.', url: 'https://hri.fi/example' },
        { label: 'Walking network: © OpenStreetMap contributors', license: 'Open Data Commons Open Database License 1.0', license_url: 'https://opendatacommons.org/licenses/odbl/1-0/', modifications: 'Walking-permitted edges extracted from the frozen network.', url: 'https://www.openstreetmap.org/copyright' },
      ],
      derived_processing: 'Source identities remain explicit while routes and snap connectors are derived.',
      defaults: { site_budget: 2, max_distance_m: 1000, capacity_multiplier: 1.25, timeout_seconds: 60 },
    })

    expect(scenario.id).toBe('espoo-service-v1')
    expect(scenario.population_cells[0]).toMatchObject({ id: 'd-1', population: 124, district: 'Tapiola' })
    expect(scenario.candidate_sites[0]).toMatchObject({ id: 's-1', label: 'Library', capacity_default: 200 })
    expect(scenario.defaults).toEqual({ site_budget: 2, max_distance_m: 1000, capacity_multiplier: 1.25, timeout_seconds: 60 })
    expect(scenario.attribution_sources).toEqual([
      { label: 'Population grid: Helsinki Region Environmental Services HSY', licence: 'Creative Commons Attribution 4.0', licence_url: 'https://creativecommons.org/licenses/by/4.0/', modifications: 'Cells selected and snapped; population totals retained.', url: 'https://hri.fi/example' },
      { label: 'Walking network: © OpenStreetMap contributors', licence: 'Open Data Commons Open Database License 1.0', licence_url: 'https://opendatacommons.org/licenses/odbl/1-0/', modifications: 'Walking-permitted edges extracted from the frozen network.', url: 'https://www.openstreetmap.org/copyright' },
    ])
    expect(scenario.derived_processing).toBe('Source identities remain explicit while routes and snap connectors are derived.')
  })

  it('accepts the solver core aliases without leaking them into the UI contract', () => {
    const event = normalizeServiceCoverageEvent({
      type: 'verified_optimal',
      open_site_ids: ['s-2'],
      assignments: [{ demand_id: 'd-4', site_id: 's-2', distance_m: 875, population: 93 }],
      objective_values: {
        open_sites: 1,
        worst_distance_m: 875,
        population_weighted_mean_distance_m: 612.5,
      },
      result: {
        status: 'verified_optimal',
        message: 'Verified.',
        open_site_ids: ['s-2'],
        assignments: [{ demand_id: 'd-4', site_id: 's-2', distance_m: 875, population: 93 }],
        objective_values: { open_sites: 1, population_weighted_mean_distance_m: 612.5 },
      },
    })

    expect(event.selected_site_ids).toEqual(['s-2'])
    expect(event.assignments?.[0]?.demand_cell_id).toBe('d-4')
    expect(event.objective_values).toMatchObject({ selected_site_count: 1, population_weighted_distance_m: 612.5 })
    expect(event.result?.selected_site_ids).toEqual(['s-2'])

    const contradiction = normalizeServiceCoverageEvent({
      type: 'unsat_core',
      finding: 'insufficient_capacity_under_budget',
      unsat_core: [{ id: 'site_budget', kind: 'budget', label: 'At most one site.' }],
    })
    expect(contradiction).toMatchObject({
      type: 'unsat_core',
      finding: 'insufficient_capacity_under_budget',
      unsat_core: [{ id: 'site_budget', kind: 'budget', label: 'At most one site.' }],
    })
  })

  it('streams progress, exposes the solve id, and sends cooperative cancellation', async () => {
    const bytes = new TextEncoder().encode([
      'event: progress\r\ndata: {"type":"matrix_compiled","message":"Matrix ready"}\r\n\r\n',
      'event: result\r\ndata: {"type":"verified_optimal","result":{"status":"verified_optimal","message":"Checked","selected_site_ids":[],"assignments":[],"site_loads":[]}}\r\n\r\n',
    ].join(''))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close() } }), {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'X-Solve-ID': 'solve-42' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ accepted: true }), { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)
    const events: string[] = []
    let solveId = ''

    const result = await streamServiceCoverageSolve({
      scenario_id: 'coverage-fixture',
      site_budget: 2,
      max_distance_m: 1200,
      capacity_multiplier: 1,
      forced_site_ids: [],
      banned_site_ids: [],
      timeout_seconds: 30,
    }, (event) => events.push(event.type), undefined, (id) => { solveId = id })
    await cancelServiceCoverageSolve(solveId)

    expect(events).toEqual(['matrix_compiled', 'verified_optimal'])
    expect(result?.status).toBe('verified_optimal')
    expect(solveId).toBe('solve-42')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/service-coverage/solve/cancel', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ solve_id: 'solve-42' }),
    }))
  })
})
