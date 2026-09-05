import { graphIndex, shortestPaths } from './graph.ts'
import type { Graph } from './graph.ts'
import type { Scenario, SolveRequest, WalkingPair } from './types.ts'

export const pairKey = (a: string, b: string) => JSON.stringify([a, b])
const check = (condition: unknown, message: string): void => { if (!condition) throw new Error(message) }
const unique = (ids: string[], label: string) => {
  check(ids.every(id => typeof id === 'string' && /^[\w-]+$/.test(id)), `Invalid ${label} ID`)
  check(new Set(ids).size === ids.length, `Duplicate ${label} IDs`)
}
export const returnFlightMm = (a: [number, number], b: [number, number]) => Math.round(2 * Math.hypot(a[0] - b[0], a[1] - b[1]))

// Reconstruct the directed route, including the representative-point connector.
// This deliberately does not trust the advertised distance in the pair table.
export function measureWalk(scenario: Scenario, pair: WalkingPair, graph: Graph) {
  const cell = scenario.cells.find(c => c.id === pair.cellId)
  const locker = scenario.lockers.find(l => l.id === pair.lockerId)
  if (!cell || !locker) throw new Error('Unknown route endpoint')
  let node = cell.nodeId
  let distance = cell.connectorMm
  for (const id of pair.edgeIds) {
    const edge = graph.edges.get(id)
    if (!edge || edge.from !== node) throw new Error(`Broken directed walking route for ${cell.id}`)
    node = edge.to; distance += edge.lengthMm
  }
  check(node === locker.nodeId, `Walking route ends at wrong locker: ${pair.lockerId}`)
  return distance
}

export function validateRequest(scenario: Scenario, request: SolveRequest) {
  for (const [name, max] of [['maxLockers', scenario.lockers.length], ['maxDepots', scenario.depots.length], ['lockerCapacity', 10000], ['depotCapacity', 10000], ['flightLimitMm', 10000000], ['timeoutMs', 30000]] as const) {
    check(Number.isSafeInteger(request[name]) && request[name] >= (name === 'timeoutMs' ? 1 : 0) && request[name] <= max, `Invalid ${name}`)
  }
  const outageTolerance = request.depotOutageTolerance === undefined ? 0 : request.depotOutageTolerance
  check(Number.isSafeInteger(outageTolerance) && outageTolerance >= 0 && outageTolerance <= 1, 'Invalid depotOutageTolerance')
  for (const [selection, candidates] of [[request.fixedLockerIds, scenario.lockers], [request.fixedDepotIds, scenario.depots]] as const) {
    if (selection === undefined) continue
    check(Array.isArray(selection), 'Selection must be an array, or omitted')
    unique(selection, 'selection')
    check(selection.every(id => candidates.some(c => c.id === id)), 'Unknown selected site')
  }
}

export function validateScenario(scenario: Scenario) {
  check(scenario.schemaVersion === 1 && scenario.walkingLimitMm === 500000, 'Unsupported scenario: walking limit must be 500 m')
  for (const [items, name] of [[scenario.cells, 'cell'], [scenario.lockers, 'locker'], [scenario.depots, 'depot']] as const) unique(items.map(item => item.id), name)
  check(scenario.cells.length > 0 && scenario.lockers.length > 0 && scenario.depots.length > 0, 'Empty scenario')
  const graph = graphIndex(scenario.network)
  for (const node of scenario.network.nodes) {
    check(node.xyMm.length === 2 && node.xyMm.every(Number.isSafeInteger), `Invalid projected coordinates: ${node.id}`)
    check(node.point.length === 2 && node.point.every(Number.isFinite) && Math.abs(node.point[0]) <= 180 && Math.abs(node.point[1]) <= 90, `Invalid map coordinates: ${node.id}`)
  }
  for (const site of [...scenario.lockers, ...scenario.depots]) {
    const node = graph.nodes.get(site.nodeId)
    check(node && node.xyMm.every((value, i) => value === site.xyMm[i]) && node.point.every((value, i) => value === site.point[i]), `Site does not match frozen node: ${site.id}`)
  }
  const pairs = new Map(scenario.walking.map(pair => [pairKey(pair.cellId, pair.lockerId), pair]))
  check(pairs.size === scenario.walking.length, 'Duplicate walking pairs')
  let expectedPairs = 0
  for (const cell of scenario.cells) {
    check(Number.isSafeInteger(cell.population) && cell.population > 0 && cell.parcels === Math.ceil(cell.population / 10), `Invalid illustrative demand: ${cell.id}`)
    const node = graph.nodes.get(cell.nodeId)
    check(node && cell.xyMm.every(Number.isSafeInteger), `Invalid cell snap: ${cell.id}`)
    const connector = Math.round(Math.hypot(cell.xyMm[0] - node!.xyMm[0], cell.xyMm[1] - node!.xyMm[1]))
    check(connector === cell.connectorMm && connector <= 500000, `Invalid connector: ${cell.id}`)
    const paths = shortestPaths(graph, cell.nodeId, 500000 - connector)
    for (const locker of scenario.lockers) {
      const distance = paths.distances.get(locker.nodeId)
      const pair = pairs.get(pairKey(cell.id, locker.id))
      if (distance === undefined) { check(!pair, `Ineligible walking pair: ${cell.id}/${locker.id}`); continue }
      expectedPairs++
      check(pair && pair.distanceMm === connector + distance, `Missing or incorrect eligible walking pair: ${cell.id}/${locker.id}`)
      check(measureWalk(scenario, pair!, graph) === pair!.distanceMm, 'Route does not match shortest distance')
    }
  }
  check(expectedPairs === pairs.size, 'Unknown walking endpoints')
  const flights = new Map(scenario.flights.map(pair => [pairKey(pair.lockerId, pair.depotId), pair]))
  check(flights.size === scenario.flights.length && flights.size === scenario.lockers.length * scenario.depots.length, 'Incomplete or duplicate flight matrix')
  for (const locker of scenario.lockers) for (const depot of scenario.depots) {
    check(flights.get(pairKey(locker.id, depot.id))?.returnDistanceMm === returnFlightMm(locker.xyMm, depot.xyMm), 'Incorrect return-flight distance')
  }
  validateRequest(scenario, { ...scenario.defaults, timeoutMs: 15000 })
  unique(scenario.starterLockerIds, 'starter locker')
  const loads = new Map(scenario.starterLockerIds.map(id => [id, 0]))
  unique(scenario.starterAssignments.map(a => a.cellId), 'starter assignment')
  check(scenario.starterAssignments.length === scenario.cells.length, 'Incomplete starter plan')
  for (const assignment of scenario.starterAssignments) {
    const cell = scenario.cells.find(c => c.id === assignment.cellId)
    check(cell && loads.has(assignment.lockerId) && pairs.has(pairKey(assignment.cellId, assignment.lockerId)), 'Invalid starter assignment')
    loads.set(assignment.lockerId, loads.get(assignment.lockerId)! + cell!.parcels)
  }
  check([...loads.values()].every(load => load > 0 && load <= scenario.defaults.lockerCapacity), 'Invalid starter locker load')
  return graph
}
