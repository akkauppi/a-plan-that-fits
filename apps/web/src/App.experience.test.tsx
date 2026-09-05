import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

vi.mock('./components/MapView', () => ({
  MapView: () => <div aria-label="Baseline map">Kallio analytical map</div>,
}))

vi.mock('./components/ResilienceAnalysisMap', () => ({
  ResilienceAnalysisMap: () => <div aria-label="Resilience analytical map">Otaniemi analytical map</div>,
}))

vi.mock('./components/ServiceCoverageMap', () => ({
  ServiceCoverageMap: () => <div aria-label="Service coverage analytical map">Otaniemi–Tapiola allocation map</div>,
}))

const polygon = {
  type: 'Feature',
  properties: {},
  geometry: {
    type: 'Polygon',
    coordinates: [[[24.94, 60.18], [24.97, 60.18], [24.97, 60.2], [24.94, 60.2], [24.94, 60.18]]],
  },
}

const scenario = {
  id: 'helsinki-kallio-vallila',
  name: 'Kallio--Vallila',
  description: 'Frozen modal-filter baseline.',
  snapshot_id: 'kallio-test-v1',
  snapshot_timestamp: '2026-08-30T00:00:00Z',
  bbox: [24.94, 60.18, 24.97, 60.2],
  center: [24.955, 60.19],
  boundary: polygon,
  terminal_zone: { ...polygon, properties: { setback_m: 70 } },
  portal_approach_zones: { ...polygon, properties: { setback_m: 120 } },
  streets: { type: 'FeatureCollection', features: [] },
  buildings: { type: 'FeatureCollection', features: [] },
  protected_corridors: { type: 'FeatureCollection', features: [] },
  portals: [
    { id: 'west', label: 'West', direction: 'W', node_ids: ['w'], point: [24.94, 60.19] },
    { id: 'east', label: 'East', direction: 'E', node_ids: ['e'], point: [24.97, 60.19] },
  ],
  candidates: [],
  address_clusters: [],
  default_portal_pairs: [{ a: 'west', b: 'east', label: 'West to east' }],
  assumptions: {},
  attribution: '© OpenStreetMap contributors',
  license: 'ODbL',
  source: 'OpenStreetMap',
}

const emptyCollection = { type: 'FeatureCollection', features: [] }
const emptyAnalysis = {
  status: 'verified',
  claim_scope: 'Frozen directed private-car graph only.',
  assumption: {
    flood_return_period_years: 1000,
    treat_flood_exposure_as_unavailable: true,
    roadworks_segment_ids: [],
    unavailable_segment_ids: ['segment-flooded'],
    analytically_passable_segment_ids: [],
  },
  summary: {
    origins: 1,
    retained: 0,
    stranded: 1,
    baseline_unreachable: 0,
    unavailable_segments: 1,
    weak_components: 2,
  },
  access: [],
}
const resilienceScenario = {
  schema_version: '1.0',
  id: 'otaniemi-access-v1',
  name: 'Otaniemi coastal access',
  description: 'Frozen private-car access stress test.',
  snapshot_id: 'otaniemi-test-v1',
  center: [24.828, 60.184],
  bbox: [24.8, 60.16, 24.85, 60.2],
  core_boundary: polygon.geometry,
  network_context_boundary: polygon.geometry,
  base_network: emptyCollection,
  buildings: emptyCollection,
  flood_exposure: emptyCollection,
  origins: [{
    id: 'origin-1', label: 'Otaranta representative cell', node_id: 'node-1',
    point: [24.83, 60.18], requested_point: [24.83, 60.18], snap_distance_m: 12,
    address_count: 5, street_names: ['Otaranta'], source: 'Espoo', aggregation: '500 m cell',
  }],
  gateway_groups: [{
    id: 'gateway-east', label: 'East · Kuusisaarentie', direction: 'east',
    point: [24.85, 60.18], destination_count: 1, destination_ids: ['node-east'],
    definition: 'Reviewed outbound context endpoint.',
  }],
  decision_groups_by_return_period: { 100: [], 1000: [] },
  default_disruption_analysis: emptyAnalysis,
  analysis_presets: {
    teaching_focus: { label: 'Teaching focus', origin_ids: ['origin-1'], gateway_group_ids: ['gateway-east'], purpose: 'Fast trace.' },
    all_origins_sensitivity: { label: 'All cells', origin_ids: ['origin-1'], gateway_group_ids: ['gateway-east'], purpose: 'Sensitivity.' },
  },
  defaults: {
    flood_return_period_years: 1000, treat_flood_exposure_as_unavailable: true,
    origin_ids: ['origin-1'], gateway_group_ids: ['gateway-east'], analytical_repair_budget: 4, timeout_seconds: 30,
  },
  counts: {
    nodes: 10, directed_edges: 12, physical_segments: 8, private_car_physical_segments: 8,
    municipal_address_points_in_core: 297, origin_clusters: 15, gateway_groups: 4,
    municipal_buildings: 20, private_car_exposed_segments: { 100: 241, 1000: 528 },
    source_exposed_segments: { 100: 892, 1000: 1608 },
  },
  semantics: {},
  attribution: 'OSM · SYKE · Espoo',
}

const serviceCoverageScenario = {
  id: 'otaniemi-tapiola-service-coverage-v1',
  name: 'Otaniemi–Tapiola service coverage',
  description: 'Frozen walking-network allocation evidence.',
  snapshot_id: 'service-coverage-test-v1',
  snapshot_timestamp: '2026-09-01T00:00:00Z',
  bbox: [24.79, 60.16, 24.86, 60.21],
  center: [24.825, 60.185],
  network: emptyCollection,
  population_cells: [{
    id: 'cell-1', label: 'Population cell 1', district: 'Otaniemi', population: 300,
    centroid: [24.82, 60.18], feature: polygon,
  }],
  candidate_sites: [{
    id: 'site-1', label: 'Reviewed public facility', category: 'Library',
    point: [24.821, 60.181], eligible: true, capacity_default: 500,
    capacity_status: 'declared',
  }],
  defaults: { site_budget: 1, max_distance_m: 1200, capacity_multiplier: 1, timeout_seconds: 30 },
  methodology: 'NetworkX distances, Z3 assignment, fresh verification.',
  attribution: 'Test evidence',
}

const catalog = {
  schema_version: '1.0',
  profile_id: 'finland-resilient-access-v1',
  default_preset_id: 'otaniemi-coastal-v1',
  presets: [{
    id: 'otaniemi-coastal-v1',
    name: 'Otaniemi coast, Espoo',
    description: 'Frozen coastal study area.',
    frozen: true,
    default_successor: true,
  }],
  location_limits: {
    coordinate_crs: 'EPSG:4326',
    finland_preflight_envelope: [19, 59, 32, 70.5],
    radius_m: { minimum: 100, maximum: 2500, default: 1000 },
    network_context_buffer_m: 750,
  },
  active_solver: { scenario: 'Kallio--Vallila', unchanged: true, message: 'Unchanged.' },
}

const preflight = {
  schema_version: '1.0',
  selection: { preset_id: 'otaniemi-coastal-v1' },
  recipe: {
    scenario_id: 'espoo-otaniemi-coastal-base-v1',
    name: 'Otaniemi coast',
    sha256: 'a'.repeat(64),
    analysis_crs: 'EPSG:3067',
    network_context_buffer_m: 750,
  },
  area: {
    coordinate_crs: 'EPSG:4326',
    core_geometry: { type: 'Polygon', coordinates: [] },
    core_bbox: [24.81, 60.17, 24.84, 60.19],
    core_area_km2: 2.743,
    network_context_bbox: [24.8, 60.16, 24.85, 60.2],
  },
  sources: [
    {
      adapter_id: 'osm',
      name: 'OpenStreetMap road network',
      role: 'base_network',
      readiness: 'archived',
      available_offline: true,
      feature_count: 25390,
      spatial_coverage: 'unknown',
      message: 'Completeness is not asserted.',
    },
    {
      adapter_id: 'mml_elevation',
      name: 'National Land Survey elevation',
      role: 'elevation',
      readiness: 'archived',
      available_offline: true,
      feature_count: null,
      spatial_coverage: 'full',
      message: 'Archived terrain raster; flood and passability are not inferred.',
    },
    {
      adapter_id: 'syke',
      name: 'SYKE coastal flood zones',
      role: 'flood_hazard',
      readiness: 'archived',
      available_offline: true,
      feature_count: 4,
      spatial_coverage: 'full',
      message: 'Frozen coastal-flood evidence.',
    },
    {
      adapter_id: 'espoo_wfs',
      name: 'City of Espoo municipal context',
      role: 'municipal_context',
      readiness: 'archived',
      available_offline: true,
      feature_count: 18,
      spatial_coverage: 'full',
      message: 'Frozen municipal evidence.',
    },
  ],
  analysis_artifacts: {
    flood_exposure: {
      status: 'verified_exposure',
      scope: 'exposure_only',
      passability_inferred: false,
      snapshot_id: 'flood-test',
      return_periods: {
        100: { exposed_segments: 40, exposed_length_m: 1100, vertical_review_segments: 2 },
        1000: { exposed_segments: 70, exposed_length_m: 1900, vertical_review_segments: 4 },
      },
      message: 'Horizontal exposure only.',
    },
  },
  offline_build_ready: true,
  build: { status: 'verified_snapshot', snapshot_id: 'base-test' },
  semantics: {
    coverage_is_not_completeness: true,
    base_network_only: true,
    active_solver_unchanged: true,
    flood_passability_inferred: false,
    message: 'No safety claim.',
  },
}

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installApiMock(): void {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/resilience/scenario')) return json(resilienceScenario)
    if (url.endsWith('/service-coverage/scenario')) return json(serviceCoverageScenario)
    if (url.endsWith('/scenario')) return json(scenario)
    if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
    if (url.endsWith('/scenario-builder/preflight')) return json(preflight)
    throw new Error(`Unexpected request ${url}`)
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('application experience hierarchy', () => {
  it('opens on a neutral experiment index with all studies at equal prominence', async () => {
    installApiMock()
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Spatial questions become choices, rules and checked routes.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Geospatial Constraint Lab experiment index' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open Four Planters/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open resilient access/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open service coverage/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'How solvers work' })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps default portal pairs when baseline is opened before scenario loading finishes', async () => {
    let resolveScenario!: (response: Response) => void
    const pendingScenario = new Promise<Response>((resolve) => {
      resolveScenario = resolve
    })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/scenario')) return pendingScenario
      throw new Error(`Unexpected request ${String(input)}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('link', { name: /Open Four Planters/i }))
    expect(screen.getByRole('heading', { name: 'Loading modal-filter placement' })).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).has('pairs')).toBe(false)

    await act(async () => {
      resolveScenario(json(scenario))
      await pendingScenario
    })

    expect(await screen.findByRole('button', { name: /Solve with four/i })).toBeEnabled()
    expect(new URLSearchParams(window.location.search).get('pairs')).toBe('east::west')
  })

  it('opens either experiment from the shared index and returns to the collection', async () => {
    installApiMock()
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('heading', { name: /Spatial questions become choices/i })
    await user.click(screen.getByRole('link', { name: /Open Four Planters/i }))

    expect(await screen.findByRole('button', { name: /Solve with four/i })).toBeInTheDocument()
    expect(screen.getByText(/Experiment 01 · frozen Kallio–Vallila/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Baseline map')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Experiments' }))

    expect(await screen.findByRole('heading', { name: /Spatial questions become choices/i })).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: /Open resilient access/i }))
    expect(await screen.findByRole('heading', { name: /See what stays reachable/i })).toBeInTheDocument()
    expect(screen.getByText(/Experiment 02 · frozen Otaniemi/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Resilience analytical map')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Decrease continuity budget' }))
    expect(screen.getByLabelText('3 continuity commitments')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Experiments' }))
    await user.click(screen.getByRole('link', { name: /Open resilient access/i }))
    expect(screen.getByLabelText('3 continuity commitments')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Experiments' }))
    await user.click(screen.getByRole('link', { name: /Open service coverage/i }))
    expect(await screen.findByRole('heading', { name: 'Equitable service coverage' })).toBeInTheDocument()
    expect(screen.getByLabelText('Service coverage analytical map')).toBeInTheDocument()
  })

  it('opens the shared solver guide from the experiment index and returns', async () => {
    installApiMock()
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('heading', { name: /Spatial questions become choices/i })
    await user.click(screen.getByRole('button', { name: 'How solvers work' }))

    expect(screen.getByRole('heading', { name: /route finder searches a network/i })).toBeInTheDocument()
    expect(screen.getByText(/network analysis supplies geographic relationships/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Experiments' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Experiments' }))
    expect(await screen.findByRole('heading', { name: /Spatial questions become choices/i })).toBeInTheDocument()
  })

  it('restores a shared baseline URL and preserves the experiment when settings change', async () => {
    window.history.replaceState(null, '', '/?experience=baseline&budget=6')
    installApiMock()
    render(<App />)

    expect(await screen.findByRole('button', { name: /Solve with 6/i })).toBeInTheDocument()
    expect(screen.getByText(/Experiment 01 · frozen Kallio–Vallila/i)).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('experience')).toBe('baseline')
    expect(new URLSearchParams(window.location.search).get('budget')).toBe('6')
  })

  it('restores a shared resilient-access URL directly', async () => {
    window.history.replaceState(null, '', '/?experience=resilience')
    installApiMock()
    render(<App />)

    expect(await screen.findByRole('heading', { name: /See what stays reachable/i })).toBeInTheDocument()
    expect(screen.getByText(/Experiment 02 · frozen Otaniemi/i)).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('experience')).toBe('resilience')
  })

  it('restores a shared service-coverage URL directly', async () => {
    window.history.replaceState(null, '', '/?experience=coverage')
    installApiMock()
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Equitable service coverage' })).toBeInTheDocument()
    expect(screen.getByText(/Experiment 03 · service location/i)).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('experience')).toBe('coverage')
  })
})
