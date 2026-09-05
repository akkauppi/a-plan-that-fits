export type Point = [number, number]

export interface NetworkNode {
  id: string
  point: Point
  xyMm: Point
}
export interface NetworkEdge {
  id: string
  from: string
  to: string
  lengthMm: number
  coordinates: Point[]
}
export interface DemandCell {
  id: string
  population: number
  parcels: number
  nodeId: string
  point: Point
  xyMm: Point
  connectorMm: number
  polygon: Point[][]
}
export interface Site extends NetworkNode {
  nodeId: string
  label: string
}
export interface WalkingPair {
  cellId: string
  lockerId: string
  distanceMm: number
  edgeIds: string[]
}
export interface FlightPair {
  lockerId: string
  depotId: string
  returnDistanceMm: number
}
export interface Scenario {
  schemaVersion: 1
  id: string
  snapshotId: string
  walkingLimitMm: 500000
  provenance: { inputSha256: string; archiveCommit: string; networkSnapshot: string }
  center: Point
  network: { nodes: NetworkNode[]; edges: NetworkEdge[] }
  cells: DemandCell[]
  lockers: Site[]
  depots: Site[]
  walking: WalkingPair[]
  flights: FlightPair[]
  defaults: Limits
  starterLockerIds: string[]
  starterAssignments: CellAssignment[]
}
export interface Limits {
  maxLockers: number
  maxDepots: number
  lockerCapacity: number
  depotCapacity: number
  flightLimitMm: number
  depotOutageTolerance?: number
}
export interface SolveRequest extends Limits {
  // Omitted = Z3 chooses. [] = exactly zero. Neither means "force these and
  // silently add more". Selection scope is part of the claim being checked.
  fixedLockerIds?: string[]
  fixedDepotIds?: string[]
  timeoutMs: number
}
export interface CellAssignment { cellId: string; lockerId: string }
export interface SupplyAssignment { lockerId: string; depotId: string }
export interface DepotOutagePlan { unavailableDepotId: string; supplies: SupplyAssignment[] }
export interface NetworkPlan {
  lockerIds: string[]
  depotIds: string[]
  assignments: CellAssignment[]
  supplies: SupplyAssignment[]
  outagePlans?: DepotOutagePlan[]
}
export interface Verification {
  valid: boolean
  errors: string[]
  parcelTotal: number
  lockerLoads: Record<string, number>
  depotLoads: Record<string, number>
  outageDepotLoads: Record<string, Record<string, number>>
  worstWalkMm: number
  longestFlightMm: number
  routesChecked: number
}
export interface ConflictRule { id: string; label: string }
export interface ExhaustiveSearchStats {
  kind: 'exhaustive'
  lockerSetsChecked: number
  siteSelectionsChecked: number
  assignmentBranchesVisited: number
  supplyBranchesVisited: number
}
export type SolveResult =
  | { status: 'feasible'; plan: NetworkPlan; verification: Verification; elapsedMs: number; search?: ExhaustiveSearchStats }
  | { status: 'unsat'; rules: ConflictRule[]; elapsedMs: number; search?: ExhaustiveSearchStats }
  | { status: 'timeout' | 'cancelled' | 'error'; message: string; elapsedMs: number; search?: ExhaustiveSearchStats }

export type WorkerRequest =
  | { type: 'init'; scenario: Scenario }
  | { type: 'solve'; requestId: number; request: SolveRequest }
  | { type: 'cancel'; requestId: number }

export type WorkerResponse =
  | { type: 'ready' }
  | { type: 'init-error'; message: string }
  | { type: 'progress'; requestId: number; phase: 'solving' | 'verifying' }
  | { type: 'result'; requestId: number; result: SolveResult }
