import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ScenarioBuilderDrawer } from './ScenarioBuilderDrawer'

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

function preflight(offline = true) {
  return {
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
    sources: [{
      adapter_id: 'osm',
      name: 'OpenStreetMap road network',
      role: 'base_network',
      readiness: offline ? 'archived' : 'refresh_required',
      available_offline: offline,
      feature_count: offline ? 25390 : null,
      spatial_coverage: 'unknown',
      message: 'Completeness is not asserted.',
    }],
    offline_build_ready: offline,
    build: { status: offline ? 'verified_snapshot' : 'not_built', snapshot_id: offline ? 'base-old' : null },
    semantics: {
      coverage_is_not_completeness: true,
      base_network_only: true,
      active_solver_unchanged: true,
      flood_passability_inferred: false,
      message: 'No safety claim.',
    },
  }
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('ScenarioBuilderDrawer', () => {
  it('opens on frozen Otaniemi and reports offline source readiness', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight())
      throw new Error(`Unexpected request ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ScenarioBuilderDrawer onClose={vi.fn()} />)

    expect(await screen.findByText('Source readiness')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Otaniemi coast/i })).toBeChecked()
    expect(screen.getByText('25,390 features · coverage unknown')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Rebuild from frozen archive/i })).toBeEnabled()
    expect(screen.getByText(/does not replace the open Kallio/i)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('preflights custom coordinates without starting a source refresh', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight(false))
      throw new Error(`Unexpected request ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ScenarioBuilderDrawer onClose={vi.fn()} />)
    await screen.findByText('Source readiness')

    await user.click(screen.getByRole('radio', { name: /Custom Finland location/i }))
    const longitude = screen.getByRole('spinbutton', { name: 'Longitude' })
    await user.clear(longitude)
    await user.type(longitude, '25.01')
    await user.click(screen.getByRole('button', { name: /Check bounds & sources/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const request = fetchMock.mock.calls[2]
    const init = request?.[1]
    if (!init) throw new Error('Expected a preflight request body')
    expect(JSON.parse(String(init.body))).toEqual({
      area: { kind: 'point_radius', longitude: 25.01, latitude: 60.184, radius_m: 1000 },
    })
    expect(screen.getByRole('button', { name: /Live refresh required/i })).toBeDisabled()
  })

  it('requires an explicit acknowledgement before a live build request', async () => {
    const user = userEvent.setup()
    const verifiedJob = {
      job_id: 'job-1',
      status: 'verified',
      created_at: '2026-08-30T12:00:00Z',
      updated_at: '2026-08-30T12:00:01Z',
      scenario_id: 'espoo-otaniemi-coastal-base-v1',
      refresh: true,
      result: { snapshot_id: 'base-new', node_count: 120, directed_edge_count: 250 },
      error: null,
      events: [{
        sequence: 1,
        type: 'complete',
        message: 'Verified base-network artifact is ready.',
        timestamp: '2026-08-30T12:00:01Z',
        details: {},
      }],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight(false))
      if (url.endsWith('/scenario-builder/jobs')) return json(verifiedJob, 202)
      throw new Error(`Unexpected request ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ScenarioBuilderDrawer onClose={vi.fn()} />)
    await screen.findByText('Source readiness')

    await user.click(screen.getByText('Need a new OSM archive?'))
    await user.click(screen.getByRole('checkbox', { name: /Allow one live OSM refresh/i }))
    await user.click(screen.getByRole('button', { name: /Fetch & build base network/i }))

    expect(await screen.findByText('Base network ready')).toBeInTheDocument()
    const request = fetchMock.mock.calls.at(-1)
    const init = request?.[1]
    if (!init) throw new Error('Expected a build request body')
    expect(JSON.parse(String(init.body))).toMatchObject({
      preset_id: 'otaniemi-coastal-v1',
      refresh: true,
      confirm_live_source_refresh: 'REFRESH_OSM',
    })
    expect(screen.getByText('base-new')).toBeInTheDocument()
  })
})
