import { useState } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
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
    sources: offline
      ? [
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
        ]
      : [{
          adapter_id: 'osm',
          name: 'OpenStreetMap road network',
          role: 'base_network',
          readiness: 'refresh_required',
          available_offline: false,
          feature_count: null,
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

function DrawerHarness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open network builder</button>
      {open && <ScenarioBuilderDrawer onClose={() => setOpen(false)} />}
    </>
  )
}

describe('ScenarioBuilderDrawer', () => {
  it('moves focus into the modal, contains Tab navigation, and restores the opener', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight())
      throw new Error(`Unexpected request ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<DrawerHarness />)

    const opener = screen.getByRole('button', { name: 'Open network builder' })
    await user.click(opener)
    const dialog = await screen.findByRole('dialog', { name: 'Choose the network' })
    const title = within(dialog).getByRole('heading', { name: 'Choose the network' })
    await waitFor(() => expect(title).toHaveFocus())

    await user.tab()
    const close = within(dialog).getByRole('button', { name: 'Close study-area builder' })
    expect(close).toHaveFocus()

    await screen.findByText('Source readiness')
    const links = within(dialog).getAllByRole('link')
    const lastLink = links.at(-1)
    if (!lastLink) throw new Error('Expected a final attribution link')
    lastLink.focus()
    await user.tab()
    expect(close).toHaveFocus()

    await user.tab({ shift: true })
    expect(lastLink).toHaveFocus()

    await user.click(close)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes an idle drawer with Escape and restores focus', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight())
      throw new Error(`Unexpected request ${url}`)
    }))
    render(<DrawerHarness />)

    const opener = screen.getByRole('button', { name: 'Open network builder' })
    await user.click(opener)
    await screen.findByRole('dialog', { name: 'Choose the network' })
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('does not let Escape dismiss a drawer while a build is active', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const activeJob = {
      job_id: 'job-active',
      status: 'building',
      created_at: '2026-08-30T12:00:00Z',
      updated_at: '2026-08-30T12:00:01Z',
      scenario_id: 'espoo-otaniemi-coastal-base-v1',
      refresh: false,
      result: null,
      error: null,
      events: [{
        sequence: 1,
        type: 'build_started',
        message: 'Building directed graph.',
        timestamp: '2026-08-30T12:00:01Z',
        details: {},
      }],
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/scenario-builder/catalog')) return json(catalog)
      if (url.endsWith('/scenario-builder/preflight')) return json(preflight())
      if (url.endsWith('/scenario-builder/jobs')) return json(activeJob, 202)
      if (url.endsWith('/scenario-builder/jobs/job-active')) return json(activeJob)
      throw new Error(`Unexpected request ${url}`)
    }))
    render(<ScenarioBuilderDrawer onClose={onClose} />)

    await screen.findByText('Source readiness')
    await user.click(screen.getByRole('button', { name: /Rebuild from frozen archive/i }))
    expect(await screen.findByRole('button', { name: /Cancel build/i })).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Choose the network' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close study-area builder' })).toBeDisabled()
  })

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
    expect(screen.getAllByText('National Land Survey of Finland Elevation Model 2 m')).toHaveLength(2)
    expect(screen.getByText('Raster archived')).toBeInTheDocument()
    expect(screen.getByLabelText('Readiness: Raster archived')).toBeInTheDocument()
    expect(screen.getByText('4 archived')).toBeInTheDocument()
    expect(screen.queryByText('Key needed')).not.toBeInTheDocument()
    expect(screen.getByText(/Source presence does not establish flooding, road closure, or passability/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'National Land Survey of Finland Elevation Model 2 m' })).toHaveAttribute('href', expect.stringContaining('elevation-model-2-m'))
    expect(screen.getByRole('link', { name: 'CC BY 4.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/')
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
