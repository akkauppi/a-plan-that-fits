import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ServiceCoverageResult, ServiceCoverageScenario, ServiceCoverageSolveEvent } from './ServiceCoverageTypes'

const apiMocks = vi.hoisted(() => ({
  getScenario: vi.fn(),
  streamSolve: vi.fn(),
  cancelSolve: vi.fn(),
}))

vi.mock('./ServiceCoverageApi', () => ({
  getServiceCoverageScenario: apiMocks.getScenario,
  streamServiceCoverageSolve: apiMocks.streamSolve,
  cancelServiceCoverageSolve: apiMocks.cancelSolve,
  ServiceCoverageApiError: class ServiceCoverageApiError extends Error {},
}))

vi.mock('./ServiceCoverageMap', () => ({
  ServiceCoverageMap: ({ scenario, onSiteSelect, assignments, view, resultStatus }: any) => (
    <div data-testid="coverage-map">
      <span>{assignments.length} visible routes</span>
      <span>{view} view</span>
      <span>{resultStatus ?? 'no terminal result'}</span>
      <button type="button" onClick={() => onSiteSelect?.(scenario.candidate_sites[0])}>Inspect Library</button>
    </div>
  ),
}))

import { ServiceCoverageExperiment } from './ServiceCoverageExperiment'

const scenario: ServiceCoverageScenario = {
  id: 'coverage-fixture',
  name: 'Tapiola service coverage',
  description: 'Fixture',
  snapshot_id: 'coverage-snapshot-1',
  snapshot_timestamp: '2026-01-01T00:00:00Z',
  bbox: [24.79, 60.17, 24.83, 60.2],
  center: [24.81, 60.185],
  network: { type: 'FeatureCollection', features: [] },
  population_cells: [{
    id: 'cell-1',
    label: 'Tapiola grid 1',
    district: 'Tapiola',
    population: 100,
    centroid: [24.8, 60.18],
    feature: {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[[24.79, 60.17], [24.8, 60.17], [24.8, 60.18], [24.79, 60.18], [24.79, 60.17]]] },
    },
  }],
  candidate_sites: [{
    id: 'site-1',
    label: 'Tapiola library',
    category: 'Library',
    point: [24.81, 60.18],
    eligible: true,
    capacity_default: 150,
    capacity_status: 'declared',
  }],
  defaults: { site_budget: 1, max_distance_m: 1200, capacity_multiplier: 1, timeout_seconds: 30 },
  methodology: 'Walking network matrix.',
  attribution: 'OSM · population fixture',
  attribution_sources: [
    { label: 'Population grid: Helsinki Region Environmental Services HSY', licence: 'Creative Commons Attribution 4.0', licence_url: 'https://example.test/cc-by', modifications: 'Cells were selected and snapped; published totals are unchanged.', url: 'https://example.test/hsy' },
    { label: 'Candidate units: Helsinki metropolitan area Service Map', licence: 'Creative Commons Attribution 4.0', licence_url: 'https://example.test/cc-by', modifications: 'Reviewed source units were snapped; capacity is an analytical assumption.', url: 'https://example.test/service-map' },
    { label: 'Walking network: © OpenStreetMap contributors', licence: 'Open Data Commons Open Database License 1.0', licence_url: 'https://example.test/odbl', modifications: 'Walking-permitted edges were extracted to derive routes.', url: 'https://www.openstreetmap.org/copyright' },
  ],
  derived_processing: 'Source features are selected and snapped; walking routes and connectors are derived for this experiment.',
}

const result: ServiceCoverageResult = {
  status: 'verified_optimal',
  message: 'All included cells were assigned and checked.',
  selected_site_ids: ['site-1'],
  assignments: [{ demand_cell_id: 'cell-1', site_id: 'site-1', distance_m: 620, population: 100 }],
  site_loads: [{ site_id: 'site-1', assigned_population: 100, effective_capacity: 150, utilisation: 2 / 3 }],
  objective_values: { selected_site_count: 1, worst_distance_m: 620, population_weighted_distance_m: 620 },
  verification: { all_cells_assigned: true, capacities_respected: true, distances_respected: true, selected_sites_eligible: true, budget_respected: true },
}

describe('ServiceCoverageExperiment', () => {
  beforeEach(() => {
    apiMocks.getScenario.mockResolvedValue(scenario)
    apiMocks.cancelSolve.mockResolvedValue(undefined)
    apiMocks.streamSolve.mockImplementation(async (_request, onEvent: (event: ServiceCoverageSolveEvent) => void, _signal, onSolveId) => {
      onSolveId?.('solve-1')
      onEvent({ type: 'matrix_compiled', message: '21 feasible pairs compiled.' })
      onEvent({ type: 'feasible_assignment', selected_site_ids: ['site-1'], assignments: result.assignments, site_loads: result.site_loads })
      onEvent({ type: 'objective_improved', message: 'Worst distance improved to 620 m.' })
      onEvent({ type: 'fresh_verification', message: 'Every route checked.' })
      onEvent({ type: 'verified_optimal', result })
      return result
    })
  })

  it('explains the direct GIS-to-Z3 model and renders a verified mapped assignment', async () => {
    const user = userEvent.setup()
    render(<ServiceCoverageExperiment />)

    expect(await screen.findByRole('heading', { name: 'Equitable service coverage' })).toBeInTheDocument()
    expect(screen.getByText(/Network path plus two straight snap connectors/)).toBeInTheDocument()
    expect(screen.getByText(/declared sensitivity input/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Frozen walking matrix/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Helsinki Region Environmental Services HSY source/ })).toHaveAttribute('href', 'https://example.test/hsy')
    expect(screen.getByRole('link', { name: /Service Map source/ })).toHaveAttribute('href', 'https://example.test/service-map')
    expect(screen.getByRole('link', { name: /OpenStreetMap contributors source/ })).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright')
    expect(screen.getAllByRole('link', { name: 'Creative Commons Attribution 4.0 licence' })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: 'Creative Commons Attribution 4.0 licence' })[0]).toHaveAttribute('href', 'https://example.test/cc-by')
    expect(screen.getByRole('link', { name: 'Open Data Commons Open Database License 1.0 licence' })).toHaveAttribute('href', 'https://example.test/odbl')
    expect(screen.getByText('Source features are selected and snapped; walking routes and connectors are derived for this experiment.')).toBeInTheDocument()
    expect(screen.getByText('Cells were selected and snapped; published totals are unchanged.')).toBeInTheDocument()
    expect(screen.getByText('Reviewed source units were snapped; capacity is an analytical assumption.')).toBeInTheDocument()
    expect(screen.getByText('Walking-permitted edges were extracted to derive routes.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Inspect Library' }))
    await user.click(screen.getByRole('button', { name: /Force site/ }))
    await user.click(screen.getByRole('button', { name: /Assign coverage with 1/ }))

    expect(await screen.findByRole('heading', { name: 'Every included cell is assigned' })).toBeInTheDocument()
    expect(screen.getByText(/Worst-served witness/)).toBeInTheDocument()
    expect(screen.getByText('1 visible routes')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Solver stage trace' })).toHaveTextContent('Evidence checked afresh')
    expect(apiMocks.streamSolve).toHaveBeenCalledWith(
      expect.objectContaining({ scenario_id: 'coverage-fixture', forced_site_ids: ['site-1'], max_distance_m: 1200 }),
      expect.any(Function),
      expect.any(AbortSignal),
      expect.any(Function),
    )
  }, 15_000)

  it('cooperatively cancels the backend worker when the experiment becomes inactive', async () => {
    apiMocks.streamSolve.mockImplementation((_request, onEvent, signal: AbortSignal, onSolveId) => {
      onSolveId?.('solve-long')
      onEvent({ type: 'matrix_compiled', message: 'Matrix ready.' })
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
    })
    const user = userEvent.setup()
    const { rerender } = render(<ServiceCoverageExperiment active />)
    await screen.findByRole('heading', { name: 'Equitable service coverage' })
    await user.click(screen.getByRole('button', { name: /Assign coverage with 1/ }))
    await screen.findByRole('button', { name: /Cancel solve/ })

    rerender(<ServiceCoverageExperiment active={false} />)

    await waitFor(() => expect(apiMocks.cancelSolve).toHaveBeenCalledWith('solve-long'))
    expect(await screen.findByText('Solve cancelled')).toBeInTheDocument()
    expect(screen.getByText(/No feasibility conclusion/)).toBeInTheDocument()
  }, 15_000)

  it('closes an open site inspector and requests cooperative cancellation before aborting', async () => {
    const cancellationOrder: string[] = []
    apiMocks.cancelSolve.mockImplementation(async () => { cancellationOrder.push('cooperative cancellation requested') })
    apiMocks.streamSolve.mockImplementation((_request, onEvent, signal: AbortSignal, onSolveId) => {
      onSolveId?.('solve-with-open-inspector')
      onEvent({ type: 'matrix_compiled', message: 'Matrix ready.' })
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => {
        cancellationOrder.push('stream aborted')
        reject(new DOMException('Aborted', 'AbortError'))
      }))
    })
    const user = userEvent.setup()
    render(<ServiceCoverageExperiment />)
    await screen.findByRole('heading', { name: 'Equitable service coverage' })
    await user.click(screen.getByRole('button', { name: 'Inspect Library' }))
    expect(screen.getByRole('button', { name: /Force site/ })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Assign coverage with 1/ }))

    expect(await screen.findByRole('button', { name: /Cancel solve/ })).toBeInTheDocument()
    expect(screen.queryByLabelText('Candidate site: Tapiola library')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Force site/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Cancel solve/ }))

    await waitFor(() => expect(apiMocks.cancelSolve).toHaveBeenCalledWith('solve-with-open-inspector'))
    expect(cancellationOrder).toEqual(['cooperative cancellation requested', 'stream aborted'])
    expect(await screen.findByText('Solve cancelled')).toBeInTheDocument()
    expect(screen.getByText(/0 forced · 0 excluded/)).toBeInTheDocument()
  }, 15_000)

  it('keeps a user reset idle when an old terminal stream abort settles later', async () => {
    apiMocks.streamSolve.mockImplementation((_request, onEvent, signal: AbortSignal, onSolveId) => {
      onSolveId?.('terminal-stream')
      onEvent({ type: 'verified_optimal', result })
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => {
        reject(new DOMException('Aborted', 'AbortError'))
      }))
    })
    const user = userEvent.setup()
    render(<ServiceCoverageExperiment />)
    await screen.findByRole('heading', { name: 'Equitable service coverage' })

    await user.click(screen.getByRole('button', { name: /Assign coverage with 1/ }))
    expect(await screen.findByRole('heading', { name: 'Every included cell is assigned' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /125%.*sensitivity case/i }))

    await waitFor(() => expect(apiMocks.cancelSolve).toHaveBeenCalledWith('terminal-stream'))
    expect(screen.queryByRole('heading', { name: 'Every included cell is assigned' })).not.toBeInTheDocument()
    expect(screen.queryByText('Solve cancelled')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Assign coverage with 1/ })).toBeInTheDocument()
    expect(screen.getByTestId('coverage-map')).toHaveTextContent('demand view')
  }, 15_000)

  it('keeps the demand evidence visible when a direct solve is infeasible', async () => {
    const unsatResult: ServiceCoverageResult = {
      status: 'verified_unsat',
      message: 'One selected site cannot provide enough analytical capacity.',
      selected_site_ids: [],
      assignments: [],
      site_loads: [],
      diagnostics: { finding: 'insufficient_capacity_under_budget' },
    }
    apiMocks.streamSolve.mockImplementation(async (_request, onEvent: (event: ServiceCoverageSolveEvent) => void) => {
      onEvent({ type: 'matrix_compiled', message: 'Frozen matrix ready.' })
      onEvent({ type: 'verified_unsat', result: unsatResult })
      return unsatResult
    })
    const user = userEvent.setup()
    render(<ServiceCoverageExperiment />)
    await screen.findByRole('heading', { name: 'Equitable service coverage' })

    await user.click(screen.getByRole('button', { name: /Assign coverage with 1/ }))

    expect(await screen.findByRole('heading', { name: 'Available analytical capacity is insufficient' })).toBeInTheDocument()
    expect(screen.getByTestId('coverage-map')).toHaveTextContent('demand view')
    expect(screen.getByTestId('coverage-map')).toHaveTextContent('verified_unsat')
    expect(screen.getByTestId('coverage-map')).toHaveTextContent('0 visible routes')
  }, 15_000)
})
