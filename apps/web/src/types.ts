import type { Feature, FeatureCollection, Geometry, LineString, Polygon, MultiPolygon } from 'geojson'

export type Id = string
export type Coordinate = [number, number]

export interface Portal {
  id: Id
  label: string
  direction: string
  node_ids: string[]
  point: Coordinate
}

export interface PortalPair {
  a: Id
  b: Id
  label: string
}

export interface Candidate {
  id: Id
  edge_ids: string[]
  name: string
  street_name: string
  point: Coordinate
  cross_geometry: LineString
  cost: number
  eligible: boolean
  reason?: string
  boundary_distance_m?: number
  boundary_distance_metric?: string
  nearest_primary_portal_distance_m?: number
  nearest_primary_portal_distance_metric?: string
  nearest_primary_portal_id?: string
  nearest_primary_portal_crossing_id?: string
}

export interface AddressCluster {
  id: Id
  label: string
  node_id: string
  point: Coordinate
  allowed_portal_ids: string[]
  building_count?: number
}

export interface SetbackZoneProperties {
  setback_m: number
  boundary_distance_metric?: string
  nearest_primary_portal_distance_metric?: string
  [key: string]: unknown
}

export interface Scenario {
  id: string
  name: string
  description: string
  snapshot_id: string
  snapshot_timestamp: string
  bbox: [number, number, number, number]
  center: Coordinate
  boundary: Feature<Polygon | MultiPolygon>
  terminal_zone: Feature<Polygon | MultiPolygon, SetbackZoneProperties>
  portal_approach_zones: Feature<Polygon | MultiPolygon, SetbackZoneProperties>
  streets: FeatureCollection
  buildings: FeatureCollection
  protected_corridors: FeatureCollection
  portals: Portal[]
  candidates: Candidate[]
  address_clusters: AddressCluster[]
  default_portal_pairs: PortalPair[]
  assumptions: Record<string, unknown>
  attribution: string
  license: string
  source: Record<string, unknown> | string
  initial_through_route?: Feature<LineString> | LineString
}

export interface SolveRequest {
  scenario_id: string
  budget: number
  required_portal_pairs: Array<{ a: string; b: string }>
  forced_interventions: string[]
  locked_open_streets: string[]
  emergency_permeable: boolean
  objective_mode: 'balanced' | 'fewest' | 'access'
  timeout_seconds: number
  solve_id?: string
}

export type SolveStatus =
  | 'idle'
  | 'solving'
  | 'candidate_found'
  | 'counterexample_found'
  | 'refining'
  | 'verified_sat'
  | 'verified_optimal'
  | 'verified_unsat'
  | 'timeout'
  | 'cancelled'
  | 'data_error'

export type SolveEventType =
  | 'started'
  | 'candidate_found'
  | 'counterexample_found'
  | 'refining'
  | 'candidate_rejected'
  | 'verified_sat'
  | 'verified_optimal'
  | 'verified_unsat'
  | 'timeout'
  | 'cancelled'
  | 'data_error'
  | 'complete'

export interface SolveEvent {
  type: SolveEventType
  iteration?: number
  message?: string
  selected_intervention_ids?: string[]
  route?: Feature<LineString> | LineString | Coordinate[]
  portal_pair?: { a: string; b: string }
  constraint?: string
  reason?: string
  result?: SolveResult
  timestamp?: string
  [key: string]: unknown
}

export interface ObjectiveValues {
  intervention_count?: number
  weighted_cost?: number
  access_detour?: number
  affected_clusters?: number
  spacing_penalty?: number
  [key: string]: number | string | undefined
}

export interface AddressAccessSummary {
  served?: number
  total?: number
  unserved_ids?: string[]
  all_accessible?: boolean
  [key: string]: unknown
}

export interface SuggestedRelaxation {
  id?: string
  label: string
  action?: string
  type?: string
  value?: number
  pair?: { a: string; b: string }
  candidate_id?: string
}

export interface PrivateCarComponentSummary {
  component_count: number
  node_count: number
  largest_component_node_count: number
  largest_component_fraction: number
  singleton_component_count: number
  open_directed_edge_count: number
  rendered_physical_edge_count: number
  inter_component_physical_edge_count: number
}

export interface PrivateCarConnectivity {
  metric: 'directed_strongly_connected_components'
  definition: string
  baseline: PrivateCarComponentSummary
  filtered: PrivateCarComponentSummary
}

export interface ConnectivityComponentProperties {
  metric: 'directed_strongly_connected_components'
  directed: true
  component_id: number | null
  component_size: number | null
  from_component_id: number
  to_component_id: number
  within_component: boolean
  color: string
}

export interface SolveResult {
  status: SolveStatus | string
  selected_intervention_ids: string[]
  objective_values: ObjectiveValues
  verification_status: string
  address_access_summary: AddressAccessSummary
  portal_connectivity_summary: unknown
  local_detour_metrics: Record<string, number | string | null>
  timing_ms: number
  iteration_count: number
  explanation: string
  snapshot_id: string
  solve_id: string
  unsat_core?: string[]
  suggested_relaxations?: Array<SuggestedRelaxation | string>
  access_routes?: FeatureCollection<LineString>
  private_car_connectivity?: PrivateCarConnectivity
  baseline_components?: FeatureCollection<LineString, ConnectivityComponentProperties>
  filtered_components?: FeatureCollection<LineString, ConnectivityComponentProperties>
  /** Compatibility alias for filtered_components. */
  components?: FeatureCollection<LineString, ConnectivityComponentProperties>
  [key: string]: unknown
}

export interface Alternative {
  id: string
  label: string
  result: SolveResult
}

export interface ScenarioSettings {
  budget: number
  selectedPairKeys: string[]
  forced: string[]
  locked: string[]
  emergencyPermeable: boolean
  objectiveMode: SolveRequest['objective_mode']
  timeoutSeconds: number
}

export interface BuilderPointRadiusArea {
  kind: 'point_radius'
  longitude: number
  latitude: number
  radius_m: number
}

export interface BuilderSelection {
  preset_id?: 'otaniemi-coastal-v1'
  area?: BuilderPointRadiusArea
}

export interface BuilderBuildRequest extends BuilderSelection {
  refresh?: boolean
  confirm_live_source_refresh?: 'REFRESH_OSM'
}

export interface BuilderCatalog {
  schema_version: string
  profile_id: string
  default_preset_id: 'otaniemi-coastal-v1'
  presets: Array<{
    id: 'otaniemi-coastal-v1'
    name: string
    description: string
    frozen: boolean
    default_successor: boolean
  }>
  location_limits: {
    coordinate_crs: string
    finland_preflight_envelope: [number, number, number, number]
    radius_m: { minimum: number; maximum: number; default: number }
    network_context_buffer_m: number
  }
  active_solver: { scenario: string; unchanged: boolean; message: string }
}

export interface BuilderSourceReadiness {
  adapter_id: string
  name: string
  role: string
  readiness: 'archived' | 'refresh_required' | 'missing' | 'invalid_archive' | 'credentials_required' | 'user_source_required'
  available_offline: boolean
  feature_count?: number | null
  acquired_at?: string | null
  source_timestamp?: string | null
  spatial_coverage: 'full' | 'partial' | 'none' | 'unknown'
  message: string
}

export interface BuilderPreflight {
  schema_version: string
  selection: BuilderSelection
  recipe: {
    scenario_id: string
    name: string
    sha256: string
    analysis_crs: string
    network_context_buffer_m: number
  }
  area: {
    coordinate_crs: string
    core_geometry: Geometry
    core_bbox: [number, number, number, number]
    core_area_km2: number
    network_context_bbox: [number, number, number, number]
  }
  sources: BuilderSourceReadiness[]
  analysis_artifacts: {
    flood_exposure: {
      status: 'verified_exposure' | 'not_built' | 'invalid_exposure' | 'base_unavailable' | 'not_requested'
      scope: 'exposure_only'
      passability_inferred: false
      snapshot_id?: string
      base_snapshot_id?: string
      return_periods?: Record<'100' | '1000', {
        exposed_segments: number
        exposed_length_m: number
        vertical_review_segments: number
      }>
      message: string
    }
  }
  offline_build_ready: boolean
  build: {
    status: 'verified_snapshot' | 'not_built' | 'invalid_snapshot'
    snapshot_id?: string | null
    message?: string
  }
  semantics: {
    coverage_is_not_completeness: boolean
    base_network_only: boolean
    active_solver_unchanged: boolean
    flood_passability_inferred: boolean
    message: string
  }
}

export type BuilderJobStatus =
  | 'queued'
  | 'preflighting'
  | 'building'
  | 'cancellation_requested'
  | 'verified'
  | 'missing_archive'
  | 'failed'
  | 'cancelled'

export interface BuilderJobEvent {
  sequence: number
  type: string
  message: string
  timestamp: string
  details: Record<string, unknown>
}

export interface BuilderJob {
  job_id: string
  status: BuilderJobStatus
  created_at: string
  updated_at: string
  scenario_id: string
  refresh: boolean
  result?: {
    snapshot_id?: string
    node_count?: number
    directed_edge_count?: number
    snapshot_path?: string
    scope?: string
  } | null
  error?: { code: string; message: string } | null
  events: BuilderJobEvent[]
}

export function asFeatureCollection(features?: Array<Feature<Geometry>>): FeatureCollection {
  return { type: 'FeatureCollection', features: features ?? [] }
}

export function pairKey(pair: Pick<PortalPair, 'a' | 'b'>): string {
  return [pair.a, pair.b].sort().join('::')
}
