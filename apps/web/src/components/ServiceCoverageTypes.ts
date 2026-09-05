import type {
  Feature,
  FeatureCollection,
  LineString,
  MultiLineString,
  MultiPolygon,
  Point,
  Polygon,
} from 'geojson'

export type ServiceCoverageStatus =
  | 'verified_optimal'
  | 'verified_unsat'
  | 'timeout'
  | 'cancelled'
  | 'data_error'

export type ServiceCoverageEventType =
  | 'started'
  | 'matrix_compiled'
  | 'feasible_assignment'
  | 'objective_improved'
  | 'fresh_verification'
  | 'unsat_core'
  | 'verification_error'
  | ServiceCoverageStatus

export interface ServiceDemandCell {
  id: string
  label: string
  district: string
  population: number
  centroid: [number, number]
  feature: Feature<Point | Polygon | MultiPolygon>
}

export interface ServiceCandidateSite {
  id: string
  label: string
  category: string
  point: [number, number]
  eligible: boolean
  capacity_default: number
  capacity_status: 'observed' | 'declared' | 'unknown'
  capacity_note?: string
  feature?: Feature<Point>
}

export interface ServiceCoverageDefaults {
  site_budget: number
  max_distance_m: number
  capacity_multiplier: number
  timeout_seconds: number
}

export interface ServiceCoverageAttributionSource {
  label: string
  licence: string
  licence_url: string
  modifications: string
  url: string
}

export interface ServiceCoverageScenario {
  id: string
  name: string
  description: string
  snapshot_id: string
  snapshot_timestamp: string
  bbox: [number, number, number, number]
  center: [number, number]
  network: FeatureCollection<LineString | MultiLineString>
  buildings?: FeatureCollection<Polygon | MultiPolygon>
  population_cells: ServiceDemandCell[]
  candidate_sites: ServiceCandidateSite[]
  defaults: ServiceCoverageDefaults
  methodology: string
  attribution: string
  attribution_sources: ServiceCoverageAttributionSource[]
  derived_processing: string
}

export interface ServiceCoverageAssignment {
  demand_cell_id: string
  site_id: string
  distance_m: number
  population: number
  route?: Feature<LineString | MultiLineString>
}

export interface ServiceSiteLoad {
  site_id: string
  assigned_population: number
  effective_capacity: number
  utilisation: number
  assigned_cell_count?: number
}

export interface ServiceCoverageObjectiveValues {
  selected_site_count: number
  open_sites?: number
  worst_distance_m: number
  population_weighted_distance_m: number
  population_weighted_total_distance_person_m?: number
  population_weighted_mean_distance_m?: number
  load_imbalance_people?: number
}

export interface ServiceCoverageVerification {
  verified?: boolean
  all_cells_assigned: boolean
  capacities_respected: boolean
  distances_respected: boolean
  selected_sites_eligible: boolean
  budget_respected: boolean
  summary?: {
    demand_cells: number
    population: number
    assigned_cells: number
    selected_sites: number
    graph_routes_checked: number
  }
}

export interface ServiceCoverageResult {
  status: ServiceCoverageStatus
  message: string
  selected_site_ids: string[]
  assignments: ServiceCoverageAssignment[]
  site_loads: ServiceSiteLoad[]
  objective_values?: Partial<ServiceCoverageObjectiveValues>
  verification?: Partial<ServiceCoverageVerification>
  diagnostics?: Record<string, unknown>
  solver_timing_ms?: number
  iteration_count?: number
  snapshot_id?: string
}

export interface ServiceCoverageSolveEvent {
  type: ServiceCoverageEventType
  iteration?: number
  message?: string
  solve_id?: string
  selected_site_ids?: string[]
  assignments?: ServiceCoverageAssignment[]
  site_loads?: ServiceSiteLoad[]
  objective_values?: Partial<ServiceCoverageObjectiveValues>
  witness_cell_id?: string
  unsat_core?: Array<{ id: string; kind: string; label: string }>
  finding?: string
  result?: ServiceCoverageResult
}

export interface ServiceCoverageSolveRequest {
  scenario_id: string
  site_budget: number
  max_distance_m: number
  capacity_multiplier: number
  forced_site_ids: string[]
  banned_site_ids: string[]
  timeout_seconds: number
}

export type ServiceSiteConstraint = 'free' | 'forced' | 'banned'

export function emptyFeatureCollection<G extends LineString | MultiLineString | Polygon | MultiPolygon>(): FeatureCollection<G> {
  return { type: 'FeatureCollection', features: [] }
}
