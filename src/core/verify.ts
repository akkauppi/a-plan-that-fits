import { graphIndex } from './graph.ts'
import { measureWalk, pairKey, returnFlightMm, validateRequest } from './validate.ts'
import type { Scenario, SolveRequest, NetworkPlan, Verification } from './types.ts'

// No Z3 imports. Recalculate conservation, capacities and actual route lengths.
// Scenario completeness is separately checked before a solver may claim UNSAT.
export function verifyPlan(scenario: Scenario, request: SolveRequest, plan: NetworkPlan): Verification {
  const errors: string[] = []
  const result: Verification = { valid: false, errors, parcelTotal: 0, lockerLoads: {}, depotLoads: {}, outageDepotLoads: {}, worstWalkMm: 0, longestFlightMm: 0, routesChecked: 0 }
  try {
    validateRequest(scenario, request)
    const graph = graphIndex(scenario.network)
    const lockers = new Map(scenario.lockers.map(l => [l.id, l]))
    const depots = new Map(scenario.depots.map(d => [d.id, d]))
    const cells = new Map(scenario.cells.map(c => [c.id, c]))
    const pairs = new Map(scenario.walking.map(p => [pairKey(p.cellId, p.lockerId), p]))
    for (const [chosen, known, exact, maximum, name] of [
      [plan.lockerIds, lockers, request.fixedLockerIds, request.maxLockers, 'lockers'],
      [plan.depotIds, depots, request.fixedDepotIds, request.maxDepots, 'depots'],
    ] as const) {
      if (new Set(chosen).size !== chosen.length || chosen.some(id => !known.has(id))) errors.push(`Unknown or duplicate ${name}`)
      if (chosen.length > maximum) errors.push(`Too many ${name}`)
      if (exact && (chosen.length !== exact.length || exact.some(id => !chosen.includes(id)))) errors.push(`Exact ${name} selection changed`)
    }
    for (const id of plan.lockerIds) result.lockerLoads[id] = 0
    for (const id of plan.depotIds) result.depotLoads[id] = 0
    const assigned = new Set<string>()
    for (const assignment of plan.assignments) {
      const cell = cells.get(assignment.cellId)
      const pair = pairs.get(pairKey(assignment.cellId, assignment.lockerId))
      if (!cell || assigned.has(cell.id) || !plan.lockerIds.includes(assignment.lockerId) || !pair) { errors.push('Unknown, duplicated, closed or unreachable cell assignment'); continue }
      assigned.add(cell.id)
      const distance = measureWalk(scenario, pair, graph)
      if (distance > 500000 || distance !== pair.distanceMm) errors.push(`Walking limit or distance failed: ${cell.id}`)
      result.worstWalkMm = Math.max(result.worstWalkMm, distance)
      result.routesChecked++
      result.parcelTotal += cell.parcels
      result.lockerLoads[assignment.lockerId] += cell.parcels
    }
    if (assigned.size !== cells.size || result.parcelTotal !== scenario.cells.reduce((sum, c) => sum + c.parcels, 0)) errors.push('Not all demand is assigned exactly once')
    if (Object.values(result.lockerLoads).some(load => load <= 0 || load > request.lockerCapacity)) errors.push('Locker capacity or use failed')
    const verifySupplies = (supplies: NetworkPlan['supplies'], unavailableDepotId: string | undefined, requireEveryDepotUsed: boolean, label: string) => {
      const supplied = new Set<string>()
      const usedDepots = new Set<string>()
      const loads = Object.fromEntries(plan.depotIds.map(id => [id, 0])) as Record<string, number>
      for (const supply of supplies) {
        const locker = lockers.get(supply.lockerId)
        const depot = depots.get(supply.depotId)
        if (!locker || !depot || !plan.lockerIds.includes(locker.id) || !plan.depotIds.includes(depot.id) || depot.id === unavailableDepotId || supplied.has(locker.id)) { errors.push(`Invalid or duplicated ${label} supply assignment`); continue }
        supplied.add(locker.id); usedDepots.add(depot.id)
        const distance = returnFlightMm(locker.xyMm, depot.xyMm)
        result.longestFlightMm = Math.max(result.longestFlightMm, distance)
        if (distance > request.flightLimitMm) errors.push(`Return-flight limit failed in ${label}: ${locker.id}`)
        loads[depot.id] += result.lockerLoads[locker.id]
      }
      if (supplied.size !== plan.lockerIds.length) errors.push(`Not every open locker has one supplier in ${label}`)
      if (requireEveryDepotUsed && usedDepots.size !== plan.depotIds.length) errors.push('Unused open depot')
      if (Object.values(loads).some(load => load > request.depotCapacity || requireEveryDepotUsed && load <= 0)) errors.push(`Shared depot capacity or use failed in ${label}`)
      if (Object.values(loads).reduce((a, b) => a + b, 0) !== result.parcelTotal) errors.push(`Supply does not conserve parcels in ${label}`)
      return loads
    }
    result.depotLoads = verifySupplies(plan.supplies, undefined, true, 'normal operation')
    const outageTolerance = request.depotOutageTolerance ?? 0
    const outagePlans = plan.outagePlans ?? []
    if (outageTolerance === 0 && outagePlans.length) errors.push('Unexpected depot outage plans')
    if (outageTolerance === 1) {
      const unavailableIds = outagePlans.map(item => item.unavailableDepotId)
      if (new Set(unavailableIds).size !== unavailableIds.length || unavailableIds.some(id => !plan.depotIds.includes(id))) errors.push('Unknown or duplicated unavailable depot')
      if (unavailableIds.length !== plan.depotIds.length || plan.depotIds.some(id => !unavailableIds.includes(id))) errors.push('Missing depot outage plan')
      for (const depotId of plan.depotIds) {
        const outage = outagePlans.find(item => item.unavailableDepotId === depotId)
        if (outage) result.outageDepotLoads[depotId] = verifySupplies(outage.supplies, depotId, false, `outage of ${depotId}`)
      }
    }
  } catch (error) { errors.push(error instanceof Error ? error.message : String(error)) }
  result.valid = errors.length === 0
  return result
}
