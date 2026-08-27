import type { Feature, FeatureCollection, LineString, MultiPolygon, Polygon } from 'geojson'
import type {
  AddressCluster,
  Candidate,
  Coordinate,
  Portal,
  PortalPair,
  Scenario,
  SolveEvent,
  SolveRequest,
  SolveResult,
  SuggestedRelaxation,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly body?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function coordinate(value: unknown, fallback: Coordinate = [24.95, 60.19]): Coordinate {
  if (Array.isArray(value) && value.length >= 2) {
    const x = Number(value[0])
    const y = Number(value[1])
    if (Number.isFinite(x) && Number.isFinite(y)) return [x, y]
  }
  return fallback
}

function featureCollection(value: unknown): FeatureCollection {
  if (value && typeof value === 'object' && (value as FeatureCollection).type === 'FeatureCollection') {
    return value as FeatureCollection
  }
  if (Array.isArray(value)) return { type: 'FeatureCollection', features: value as Feature[] }
  return { type: 'FeatureCollection', features: [] }
}

function portal(raw: Record<string, unknown>, index: number): Portal {
  return {
    id: String(raw.id ?? `portal-${index + 1}`),
    label: String(raw.label ?? `Portal ${index + 1}`),
    direction: String(raw.direction ?? raw.side ?? ''),
    node_ids: Array.isArray(raw.node_ids) ? raw.node_ids.map(String) : [],
    point: coordinate(raw.point ?? raw.coordinates),
  }
}

function lineString(value: unknown, point: Coordinate): LineString {
  const candidate = value as LineString | undefined
  if (candidate?.type === 'LineString' && Array.isArray(candidate.coordinates)) return candidate
  const latitudeScale = Math.max(Math.cos((point[1] * Math.PI) / 180), 0.1)
  const dx = 0.000045 / latitudeScale
  return {
    type: 'LineString',
    coordinates: [
      [point[0] - dx, point[1]],
      [point[0] + dx, point[1]],
    ],
  }
}

function candidate(raw: Record<string, unknown>, index: number): Candidate {
  const point = coordinate(raw.point ?? raw.display_point)
  return {
    id: String(raw.id ?? raw.edge_id ?? `candidate-${index + 1}`),
    edge_ids: Array.isArray(raw.edge_ids)
      ? raw.edge_ids.map(String)
      : raw.edge_id
        ? [String(raw.edge_id)]
        : [],
    name: String(raw.name ?? raw.street_name ?? `Candidate ${index + 1}`),
    street_name: String(raw.street_name ?? raw.name ?? 'Unnamed local street'),
    point,
    cross_geometry: lineString(raw.cross_geometry, point),
    cost: Number(raw.cost ?? 1),
    eligible: raw.eligible !== false,
    reason: raw.reason ? String(raw.reason) : undefined,
  }
}

function addressCluster(raw: Record<string, unknown>, index: number): AddressCluster {
  return {
    id: String(raw.id ?? `address-${index + 1}`),
    label: String(raw.label ?? `Address cluster ${index + 1}`),
    node_id: String(raw.node_id ?? ''),
    point: coordinate(raw.point),
    allowed_portal_ids: Array.isArray(raw.allowed_portal_ids) ? raw.allowed_portal_ids.map(String) : [],
    building_count: raw.building_count == null ? undefined : Number(raw.building_count),
  }
}

function portalPair(raw: unknown): PortalPair {
  const item = raw as Record<string, unknown>
  const values = Array.isArray(raw) ? raw : [item.a, item.b]
  const a = String(values[0] ?? '')
  const b = String(values[1] ?? '')
  return { a, b, label: String(item.label ?? `Portal ${a} — ${b}`) }
}

function suggestedRelaxation(value: unknown): SuggestedRelaxation | string {
  if (typeof value === 'string') return value
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const pairRaw = raw.pair && typeof raw.pair === 'object' ? raw.pair as Record<string, unknown> : undefined
  const pair = pairRaw?.a != null && pairRaw.b != null
    ? { a: String(pairRaw.a), b: String(pairRaw.b) }
    : undefined
  const numericValue = raw.value == null ? undefined : Number(raw.value)
  return {
    label: String(raw.label ?? 'Review this assumption'),
    ...(raw.id != null ? { id: String(raw.id) } : {}),
    ...(raw.type != null ? { type: String(raw.type) } : {}),
    ...(raw.action != null ? { action: String(raw.action) } : {}),
    ...(raw.candidate_id != null ? { candidate_id: String(raw.candidate_id) } : {}),
    ...(pair ? { pair } : {}),
    ...(numericValue != null && Number.isFinite(numericValue) ? { value: numericValue } : {}),
  }
}

export function normalizeScenario(rawValue: unknown): Scenario {
  const raw = (rawValue ?? {}) as Record<string, unknown>
  const portals = (Array.isArray(raw.portals) ? raw.portals : []).map((item, index) =>
    portal(item as Record<string, unknown>, index),
  )
  const bboxRaw = Array.isArray(raw.bbox) ? raw.bbox.map(Number) : []
  const bbox: [number, number, number, number] = bboxRaw.length >= 4
    ? [bboxRaw[0]!, bboxRaw[1]!, bboxRaw[2]!, bboxRaw[3]!]
    : [24.93, 60.18, 24.98, 60.21]
  const boundary = (raw.boundary ?? {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [bbox[0], bbox[1]],
        [bbox[2], bbox[1]],
        [bbox[2], bbox[3]],
        [bbox[0], bbox[3]],
        [bbox[0], bbox[1]],
      ]],
    },
  }) as Feature<Polygon | MultiPolygon>
  return {
    id: String(raw.id ?? raw.scenario_id ?? 'helsinki-scenario'),
    name: String(raw.name ?? 'Helsinki study area'),
    description: String(raw.description ?? 'Frozen OpenStreetMap network scenario.'),
    snapshot_id: String(raw.snapshot_id ?? 'unknown-snapshot'),
    snapshot_timestamp: String(raw.snapshot_timestamp ?? raw.timestamp ?? 'unknown'),
    bbox,
    center: coordinate(raw.center, [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]),
    boundary,
    streets: featureCollection(raw.streets),
    buildings: featureCollection(raw.buildings),
    protected_corridors: featureCollection(raw.protected_corridors),
    portals,
    candidates: (Array.isArray(raw.candidates) ? raw.candidates : []).map((item, index) =>
      candidate(item as Record<string, unknown>, index),
    ),
    address_clusters: (Array.isArray(raw.address_clusters) ? raw.address_clusters : []).map((item, index) =>
      addressCluster(item as Record<string, unknown>, index),
    ),
    default_portal_pairs: (Array.isArray(raw.default_portal_pairs) ? raw.default_portal_pairs : []).map(portalPair),
    assumptions: (raw.assumptions as Record<string, unknown>) ?? {},
    attribution: String(raw.attribution ?? '© OpenStreetMap contributors'),
    license: String(raw.license ?? 'Open Database Licence (ODbL)'),
    source: (raw.source as Record<string, unknown> | string) ?? 'OpenStreetMap',
    initial_through_route: raw.initial_through_route as Feature<LineString> | LineString | undefined,
  }
}

export async function getScenario(signal?: AbortSignal): Promise<Scenario> {
  const response = await fetch(`${API_BASE}/scenario`, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) throw new ApiError(`Scenario request failed (${response.status})`, response.status, await response.text())
  return normalizeScenario(await response.json())
}

export async function getHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`, { signal })
    return response.ok
  } catch {
    return false
  }
}

function normalizeResult(rawValue: unknown): SolveResult {
  const raw = (rawValue ?? {}) as Record<string, unknown>
  const rawAccess = (raw.address_access_summary ?? {}) as Record<string, unknown>
  const normalizedAccess = {
    ...rawAccess,
    total: Number(rawAccess.total ?? rawAccess.included_clusters ?? 0),
    served: Number(rawAccess.served ?? rawAccess.served_clusters ?? 0),
    unserved_ids: Array.isArray(rawAccess.unserved_ids)
      ? rawAccess.unserved_ids.map(String)
      : Array.isArray(rawAccess.unserved_cluster_ids)
        ? rawAccess.unserved_cluster_ids.map(String)
        : [],
    all_accessible: Boolean(rawAccess.all_accessible ?? rawAccess.all_served ?? false),
  }
  return {
    ...raw,
    status: String(raw.status ?? raw.verification_status ?? 'data_error'),
    selected_intervention_ids: Array.isArray(raw.selected_intervention_ids)
      ? raw.selected_intervention_ids.map(String)
      : [],
    objective_values: (raw.objective_values as SolveResult['objective_values']) ?? {},
    verification_status: String(raw.verification_status ?? raw.status ?? 'unknown'),
    address_access_summary: normalizedAccess,
    portal_connectivity_summary: raw.portal_connectivity_summary ?? {},
    local_detour_metrics: (raw.local_detour_metrics as SolveResult['local_detour_metrics']) ?? {},
    timing_ms: Number(raw.timing_ms ?? 0),
    iteration_count: Number(raw.iteration_count ?? 0),
    explanation: String(raw.explanation ?? ''),
    snapshot_id: String(raw.snapshot_id ?? ''),
    solve_id: String(raw.solve_id ?? ''),
    unsat_core: Array.isArray(raw.unsat_core)
      ? raw.unsat_core.map((entry) => {
          if (entry && typeof entry === 'object') {
            const item = entry as Record<string, unknown>
            return String(item.label ?? item.key ?? item.details ?? 'Conflicting assumption')
          }
          return String(entry)
        })
      : undefined,
    suggested_relaxations: Array.isArray(raw.suggested_relaxations)
      ? raw.suggested_relaxations.map(suggestedRelaxation)
      : undefined,
  } as SolveResult
}

function normalizeEvent(rawValue: unknown): SolveEvent {
  const raw = (rawValue ?? {}) as Record<string, unknown>
  const nested = (raw.data && typeof raw.data === 'object' ? raw.data : {}) as Record<string, unknown>
  const payload = (raw.payload && typeof raw.payload === 'object' ? raw.payload : {}) as Record<string, unknown>
  const merged = { ...nested, ...payload, ...raw }
  const rawRoute = merged.route as Record<string, unknown> | undefined
  return {
    ...merged,
    type: String(merged.type ?? merged.status ?? 'data_error') as SolveEvent['type'],
    iteration: merged.iteration == null ? undefined : Number(merged.iteration),
    message: merged.message ? String(merged.message) : undefined,
    selected_intervention_ids: Array.isArray(merged.selected_intervention_ids)
      ? merged.selected_intervention_ids.map(String)
      : undefined,
    route: rawRoute && !Array.isArray(rawRoute) && rawRoute.type !== 'Feature' && rawRoute.type !== 'LineString'
      ? (rawRoute.geometry as SolveEvent['route'])
      : (merged.route as SolveEvent['route']),
    result: merged.result ? normalizeResult(merged.result) : undefined,
  } as SolveEvent
}

export async function parseEventStream(
  response: Response,
  onEvent: (event: SolveEvent) => void,
): Promise<SolveResult | undefined> {
  const contentType = response.headers.get('content-type') ?? ''
  if (!response.ok) throw new ApiError(`Solver request failed (${response.status})`, response.status, await response.text())
  if (!contentType.includes('text/event-stream')) {
    const json = await response.json()
    const result = normalizeResult((json as Record<string, unknown>).result ?? json)
    onEvent({ type: 'complete', result })
    return result
  }
  if (!response.body) throw new ApiError('Solver response did not include a stream body')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let finalResult: SolveResult | undefined

  const consumeBlock = (block: string) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data || data === '[DONE]') return
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      onEvent({ type: 'data_error', message: 'The solver emitted an unreadable progress event.' })
      return
    }
    const event = normalizeEvent(parsed)
    if (event.result) finalResult = event.result
    onEvent(event)
  }

  while (true) {
    const { done, value } = await reader.read()
    pending += decoder.decode(value, { stream: !done })
    const blocks = pending.split(/\r?\n\r?\n/)
    pending = blocks.pop() ?? ''
    blocks.forEach(consumeBlock)
    if (done) break
  }
  if (pending.trim()) consumeBlock(pending)
  return finalResult
}

export async function streamSolve(
  request: SolveRequest,
  onEvent: (event: SolveEvent) => void,
  signal?: AbortSignal,
  next = false,
): Promise<SolveResult | undefined> {
  const endpoint = next ? 'solutions/next' : 'solve'
  const response = await fetch(`${API_BASE}/${endpoint}`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream, application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  return parseEventStream(response, onEvent)
}

export async function cancelSolve(solveId?: string): Promise<void> {
  const response = await fetch(`${API_BASE}/solve/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ solve_id: solveId ?? null }),
  })
  if (!response.ok) throw new ApiError(`Cancellation failed (${response.status})`, response.status, await response.text())
}
