import type {
  Feature,
  FeatureCollection,
  Geometry,
  LineString,
  MultiLineString,
  MultiPolygon,
  Point,
  Polygon,
} from 'geojson'
import type {
  ServiceCandidateSite,
  ServiceCoverageAttributionSource,
  ServiceCoverageAssignment,
  ServiceCoverageResult,
  ServiceCoverageScenario,
  ServiceCoverageSolveEvent,
  ServiceCoverageSolveRequest,
  ServiceDemandCell,
  ServiceSiteLoad,
} from './ServiceCoverageTypes'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? '/api'

export class ServiceCoverageApiError extends Error {
  constructor(message: string, readonly status?: number, readonly body?: string) {
    super(message)
    this.name = 'ServiceCoverageApiError'
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function coordinate(value: unknown, fallback: [number, number]): [number, number] {
  if (Array.isArray(value) && value.length >= 2) {
    const longitude = Number(value[0])
    const latitude = Number(value[1])
    if (Number.isFinite(longitude) && Number.isFinite(latitude)) return [longitude, latitude]
  }
  return fallback
}

function collection<G extends Geometry>(value: unknown): FeatureCollection<G> {
  const raw = record(value)
  if (raw.type === 'FeatureCollection' && Array.isArray(raw.features)) {
    return raw as unknown as FeatureCollection<G>
  }
  if (Array.isArray(value)) return { type: 'FeatureCollection', features: value as Feature<G>[] }
  return { type: 'FeatureCollection', features: [] }
}

function centroidFeature(id: string, center: [number, number]): Feature<Point> {
  return {
    type: 'Feature',
    id,
    properties: { id, geometry_evidence: 'representative centroid; source polygon unavailable' },
    geometry: { type: 'Point', coordinates: center },
  }
}

function cellFrom(value: unknown, index: number, fallback: [number, number]): ServiceDemandCell {
  const item = record(value)
  const embeddedFeature = record(item.feature)
  const featureLike = item.type === 'Feature' ? item : embeddedFeature
  const properties = { ...record(featureLike.properties), ...item }
  const id = String(properties.id ?? properties.cell_id ?? `cell-${index + 1}`)
  const geometry = record(featureLike.geometry)
  const centroid = coordinate(
    properties.centroid ?? properties.point ?? properties.coordinates,
    fallback,
  )
  const feature = geometry.type === 'Polygon' || geometry.type === 'MultiPolygon'
    ? featureLike as unknown as Feature<Polygon | MultiPolygon>
    : centroidFeature(id, centroid)
  return {
    id,
    label: String(properties.label ?? properties.name ?? `Population cell ${index + 1}`),
    district: String(properties.district ?? properties.area ?? 'Study area'),
    population: Math.max(0, Number(properties.population ?? properties.demand ?? 0)),
    centroid,
    feature: {
      ...feature,
      id: feature.id ?? id,
      properties: { ...(feature.properties ?? {}), id },
    },
  }
}

function rawItems(value: unknown): unknown[] {
  const raw = record(value)
  if (raw.type === 'FeatureCollection' && Array.isArray(raw.features)) return raw.features
  return Array.isArray(value) ? value : []
}

function siteFrom(value: unknown, index: number, fallback: [number, number]): ServiceCandidateSite {
  const item = record(value)
  const embeddedFeature = record(item.feature)
  const featureLike = item.type === 'Feature' ? item : embeddedFeature
  const properties = { ...record(featureLike.properties), ...item }
  const geometry = record(featureLike.geometry)
  const point = coordinate(
    properties.point ?? properties.coordinates ?? geometry.coordinates,
    fallback,
  )
  const capacity = Number(properties.capacity_default ?? properties.capacity ?? 0)
  const capacityStatus = String(properties.capacity_status ?? properties.capacity_source_status ?? 'declared')
  return {
    id: String(properties.id ?? properties.site_id ?? `site-${index + 1}`),
    label: String(properties.label ?? properties.name ?? `Candidate site ${index + 1}`),
    category: String(properties.category ?? properties.service_type ?? 'Reviewed service candidate'),
    point,
    eligible: properties.eligible !== false,
    capacity_default: Number.isFinite(capacity) ? Math.max(0, capacity) : 0,
    capacity_status: capacityStatus === 'observed' || capacityStatus === 'unknown'
      ? capacityStatus
      : 'declared',
    capacity_note: properties.capacity_note ? String(properties.capacity_note) : undefined,
    feature: geometry.type === 'Point'
      ? featureLike as unknown as Feature<Point>
      : undefined,
  }
}

function attributionSourceFrom(value: unknown, index: number): ServiceCoverageAttributionSource {
  const raw = record(value)
  return {
    label: String(raw.label ?? raw.name ?? `Source ${index + 1}`),
    licence: String(raw.licence ?? raw.license ?? 'Licence not stated'),
    licence_url: String(raw.licence_url ?? raw.license_url ?? ''),
    modifications: String(raw.modifications ?? raw.derived_processing ?? 'Selected and transformed for this experiment.'),
    url: String(raw.url ?? ''),
  }
}

export function normalizeServiceCoverageScenario(value: unknown): ServiceCoverageScenario {
  const raw = record(value)
  const bboxValues = Array.isArray(raw.bbox) ? raw.bbox.map(Number) : []
  const bbox: [number, number, number, number] = bboxValues.length >= 4
    ? [bboxValues[0]!, bboxValues[1]!, bboxValues[2]!, bboxValues[3]!]
    : [24.78, 60.16, 24.86, 60.22]
  const center = coordinate(raw.center, [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2])
  const defaults = record(raw.defaults)
  const cells = rawItems(raw.population_cells ?? raw.demand_cells ?? raw.population_grid)
    .map((item, index) => cellFrom(item, index, center))
  const sites = rawItems(raw.candidate_sites ?? raw.sites)
    .map((item, index) => siteFrom(item, index, center))
  return {
    id: String(raw.id ?? raw.scenario_id ?? 'service-coverage-scenario'),
    name: String(raw.name ?? 'Equitable service coverage'),
    description: String(raw.description ?? 'Frozen population, candidate-service and walking-network scenario.'),
    snapshot_id: String(raw.snapshot_id ?? 'unknown-snapshot'),
    snapshot_timestamp: String(raw.snapshot_timestamp ?? raw.timestamp ?? 'unknown'),
    bbox,
    center,
    network: collection<LineString | MultiLineString>(raw.network ?? raw.walking_network),
    buildings: raw.buildings ? collection<Polygon | MultiPolygon>(raw.buildings) : undefined,
    population_cells: cells,
    candidate_sites: sites,
    defaults: {
      site_budget: Math.max(1, Number(defaults.site_budget ?? 4)),
      max_distance_m: Math.max(100, Number(defaults.max_distance_m ?? 1200)),
      capacity_multiplier: Math.max(0.1, Number(defaults.capacity_multiplier ?? 1)),
      timeout_seconds: Math.max(1, Number(defaults.timeout_seconds ?? 30)),
    },
    methodology: String(raw.methodology ?? 'Network paths and their straight snap connectors are compiled before Z3 assigns every included demand cell to one eligible selected site.'),
    attribution: String(raw.attribution ?? '© OpenStreetMap contributors · population and service sources listed in scenario metadata'),
    attribution_sources: rawItems(raw.attribution_sources).map(attributionSourceFrom),
    derived_processing: String(raw.derived_processing ?? 'Source data are selected and transformed for this experiment; see the per-source notes.'),
  }
}

function assignmentFrom(value: unknown): ServiceCoverageAssignment {
  const raw = record(value)
  const route = record(raw.route)
  return {
    demand_cell_id: String(raw.demand_cell_id ?? raw.demand_id ?? raw.cell_id ?? ''),
    site_id: String(raw.site_id ?? ''),
    distance_m: Number(raw.distance_m ?? 0),
    population: Number(raw.population ?? raw.demand ?? 0),
    route: route.type === 'Feature' ? route as unknown as ServiceCoverageAssignment['route'] : undefined,
  }
}

function loadFrom(value: unknown, siteId?: string): ServiceSiteLoad {
  const raw = record(value)
  const assigned = Number(raw.assigned_population ?? raw.load ?? 0)
  const capacity = Number(raw.effective_capacity ?? raw.capacity ?? 0)
  const utilisation = Number(raw.utilisation ?? raw.utilization ?? (capacity > 0 ? assigned / capacity : 0))
  return {
    site_id: String(raw.site_id ?? siteId ?? ''),
    assigned_population: assigned,
    effective_capacity: capacity,
    utilisation,
    assigned_cell_count: raw.assigned_cell_count == null ? undefined : Number(raw.assigned_cell_count),
  }
}

function loadsFrom(value: unknown): ServiceSiteLoad[] {
  if (Array.isArray(value)) return value.map((item) => loadFrom(item))
  return Object.entries(record(value)).map(([siteId, item]) => loadFrom(item, siteId))
}

function resultFrom(value: unknown): ServiceCoverageResult | undefined {
  const raw = record(value)
  if (!raw.status) return undefined
  return {
    status: raw.status as ServiceCoverageResult['status'],
    message: String(raw.message ?? 'Analysis completed.'),
    selected_site_ids: Array.isArray(raw.selected_site_ids ?? raw.open_site_ids)
      ? ((raw.selected_site_ids ?? raw.open_site_ids) as unknown[]).map(String)
      : [],
    assignments: (Array.isArray(raw.assignments) ? raw.assignments : []).map(assignmentFrom),
    site_loads: loadsFrom(raw.site_loads),
    objective_values: objectiveValues(raw.objective_values),
    verification: record(raw.verification) as ServiceCoverageResult['verification'],
    diagnostics: record(raw.diagnostics),
    solver_timing_ms: raw.solver_timing_ms == null ? undefined : Number(raw.solver_timing_ms),
    iteration_count: raw.iteration_count == null ? undefined : Number(raw.iteration_count),
    snapshot_id: raw.snapshot_id == null ? undefined : String(raw.snapshot_id),
  }
}

export function normalizeServiceCoverageEvent(value: unknown): ServiceCoverageSolveEvent {
  const raw = record(value)
  return {
    type: String(raw.type ?? 'data_error') as ServiceCoverageSolveEvent['type'],
    iteration: raw.iteration == null ? undefined : Number(raw.iteration),
    message: raw.message == null ? undefined : String(raw.message),
    solve_id: raw.solve_id == null ? undefined : String(raw.solve_id),
    selected_site_ids: Array.isArray(raw.selected_site_ids ?? raw.open_site_ids)
      ? ((raw.selected_site_ids ?? raw.open_site_ids) as unknown[]).map(String)
      : undefined,
    assignments: Array.isArray(raw.assignments) ? raw.assignments.map(assignmentFrom) : undefined,
    site_loads: raw.site_loads == null ? undefined : loadsFrom(raw.site_loads),
    objective_values: raw.objective_values == null ? undefined : objectiveValues(raw.objective_values),
    witness_cell_id: raw.witness_cell_id == null ? undefined : String(raw.witness_cell_id),
    unsat_core: Array.isArray(raw.unsat_core)
      ? raw.unsat_core.map((item) => {
        const constraint = record(item)
        return {
          id: String(constraint.id ?? ''),
          kind: String(constraint.kind ?? ''),
          label: String(constraint.label ?? ''),
        }
      })
      : undefined,
    finding: raw.finding == null ? undefined : String(raw.finding),
    result: resultFrom(raw.result),
  }
}

function objectiveValues(value: unknown): ServiceCoverageResult['objective_values'] {
  const raw = record(value)
  const selectedSiteCount = raw.selected_site_count ?? raw.open_sites
  const weightedDistance = raw.population_weighted_distance_m ?? raw.population_weighted_mean_distance_m
  return {
    ...raw,
    ...(selectedSiteCount == null ? {} : { selected_site_count: Number(selectedSiteCount) }),
    ...(weightedDistance == null ? {} : { population_weighted_distance_m: Number(weightedDistance) }),
  } as ServiceCoverageResult['objective_values']
}

export async function getServiceCoverageScenario(signal?: AbortSignal): Promise<ServiceCoverageScenario> {
  const response = await fetch(`${API_BASE}/service-coverage/scenario`, { signal })
  if (!response.ok) {
    const body = await response.text()
    throw new ServiceCoverageApiError('The frozen service-coverage scenario could not be loaded.', response.status, body)
  }
  return normalizeServiceCoverageScenario(await response.json())
}

function parseSseBlock(block: string): ServiceCoverageSolveEvent | undefined {
  const data = block.split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
  if (!data) return undefined
  return normalizeServiceCoverageEvent(JSON.parse(data) as unknown)
}

export async function streamServiceCoverageSolve(
  request: ServiceCoverageSolveRequest,
  onEvent: (event: ServiceCoverageSolveEvent) => void,
  signal?: AbortSignal,
  onSolveId?: (solveId: string) => void,
): Promise<ServiceCoverageResult | undefined> {
  const response = await fetch(`${API_BASE}/service-coverage/solve`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new ServiceCoverageApiError('The service-coverage solve could not be started.', response.status, body)
  }
  const solveId = response.headers.get('X-Solve-ID')
  if (solveId) onSolveId?.(solveId)
  if (!response.body) throw new ServiceCoverageApiError('The service-coverage stream returned no readable body.')

  const decoder = new TextDecoder()
  const reader = response.body.getReader()
  let buffer = ''
  let finalResult: ServiceCoverageResult | undefined
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = parseSseBlock(block)
      if (!event) continue
      onEvent(event)
      if (event.result) finalResult = event.result
    }
    if (done) break
  }
  if (buffer.trim()) {
    const event = parseSseBlock(buffer)
    if (event) {
      onEvent(event)
      if (event.result) finalResult = event.result
    }
  }
  return finalResult
}

export async function cancelServiceCoverageSolve(solveId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/service-coverage/solve/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ solve_id: solveId }),
  })
  if (!response.ok && response.status !== 404) {
    const body = await response.text()
    throw new ServiceCoverageApiError('The service-coverage solve could not be cancelled cooperatively.', response.status, body)
  }
}
