import type { ConflictRule, ExhaustiveSearchStats, NetworkPlan, Scenario, SolveRequest, SolveResult } from '../core/types.ts'
import { validateRequest, validateScenario } from '../core/validate.ts'
import { verifyPlan } from '../core/verify.ts'

export interface ExhaustiveHooks {
  isCancelled?: () => boolean
  onPhase?: (phase: 'solving' | 'verifying') => void
}

function combinations<T>(items: T[], size: number): T[][] {
  if (size === 0) return [[]]
  if (size < 0 || size > items.length) return []
  const result: T[][] = []
  const visit = (start: number, chosen: T[]) => {
    if (chosen.length === size) { result.push([...chosen]); return }
    for (let i = start; i <= items.length - (size - chosen.length); i++) {
      chosen.push(items[i]); visit(i + 1, chosen); chosen.pop()
    }
  }
  visit(0, [])
  return result
}

function selections(ids: string[], maximum: number, fixed?: string[]) {
  if (fixed !== undefined) return fixed.length <= maximum ? [[...fixed]] : []
  const result: string[][] = []
  for (let size = maximum; size >= 0; size--) result.push(...combinations(ids, size))
  return result
}

function allRuleGroups(request: SolveRequest): ConflictRule[] {
  const rules: ConflictRule[] = [
    { id: 'collection', label: 'Every cell goes to exactly one open locker along a walk of at most 500 m.' },
    { id: 'locker_budget', label: `Open at most ${request.maxLockers} lockers.` },
    { id: 'locker_capacity', label: `Each locker handles at most ${request.lockerCapacity} parcels per day.` },
    { id: 'supply', label: `Each open locker has one open supplier within a ${(request.flightLimitMm / 1000000).toFixed(1)} km return flight.` },
    { id: 'depot_budget', label: `Open at most ${request.maxDepots} depots.` },
    { id: 'depot_capacity', label: `Each depot supplies at most ${request.depotCapacity} parcels per day across all its lockers.` },
  ]
  if (request.fixedLockerIds !== undefined) rules.push({ id: 'fixed_lockers', label: `Keep exactly these lockers: ${request.fixedLockerIds.join(', ') || 'none'}.` })
  if (request.fixedDepotIds !== undefined) rules.push({ id: 'fixed_depots', label: `Keep exactly these depots: ${request.fixedDepotIds.join(', ') || 'none'}.` })
  return rules
}

// Exhaustive, deterministic backtracking over the same finite decisions as the
// Z3 model. Branches are pruned only when a stated constraint already makes
// every completion impossible; no heuristic is allowed to declare UNSAT.
export async function solveByEnumeration(scenario: Scenario, request: SolveRequest, hooks: ExhaustiveHooks = {}): Promise<SolveResult> {
  const start = performance.now()
  let searchStart = start
  const elapsedMs = () => Math.round(performance.now() - start)
  const stats: ExhaustiveSearchStats = { kind: 'exhaustive', lockerSetsChecked: 0, siteSelectionsChecked: 0, assignmentBranchesVisited: 0, supplyBranchesVisited: 0 }
  let stopped: 'cancelled' | 'timeout' | undefined
  const shouldStop = () => {
    if (stopped) return true
    if (hooks.isCancelled?.()) stopped = 'cancelled'
    else if (performance.now() - searchStart >= request.timeoutMs) stopped = 'timeout'
    return Boolean(stopped)
  }
  try { validateScenario(scenario); validateRequest(scenario, request) }
  catch (error) { return { status: 'error', message: String(error), elapsedMs: elapsedMs(), search: stats } }
  searchStart = performance.now()
  if (shouldStop()) return { status: stopped!, message: stopped === 'cancelled' ? 'Cancelled. No feasibility claim was made.' : 'Exhaustive search reached its time limit. No feasibility claim was made.', elapsedMs: elapsedMs(), search: stats }
  hooks.onPhase?.('solving')

  const lockerIds = scenario.lockers.map(site => site.id)
  const depotIds = scenario.depots.map(site => site.id)
  const walksByCell = new Map(scenario.cells.map(cell => [cell.id, scenario.walking.filter(pair => pair.cellId === cell.id).map(pair => pair.lockerId)]))
  const cellsByLocker = new Map(lockerIds.map(id => [id, new Set(scenario.walking.filter(pair => pair.lockerId === id).map(pair => pair.cellId))]))
  const depotsByLocker = new Map(lockerIds.map(id => [id, scenario.flights.filter(pair => pair.lockerId === id && pair.returnDistanceMm <= request.flightLimitMm).map(pair => pair.depotId)]))
  const totalDemand = scenario.cells.reduce((sum, cell) => sum + cell.parcels, 0)
  let found: NetworkPlan | undefined

  for (const chosenLockers of selections(lockerIds, request.maxLockers, request.fixedLockerIds)) {
    if (shouldStop()) break
    stats.lockerSetsChecked++
    if (!chosenLockers.length || totalDemand > chosenLockers.length * request.lockerCapacity) continue
    if (!scenario.cells.every(cell => walksByCell.get(cell.id)!.some(id => chosenLockers.includes(id)))) continue
    if (!chosenLockers.every(id => cellsByLocker.get(id)!.size > 0)) continue

    for (const chosenDepots of selections(depotIds, request.maxDepots, request.fixedDepotIds)) {
      if (shouldStop()) break
      stats.siteSelectionsChecked++
      if (!chosenDepots.length || totalDemand > chosenDepots.length * request.depotCapacity) continue
      const eligibleDepots = new Map(chosenLockers.map(id => [id, depotsByLocker.get(id)!.filter(depotId => chosenDepots.includes(depotId))]))
      if (chosenLockers.some(id => !eligibleDepots.get(id)!.length)) continue
      if (chosenDepots.some(id => !chosenLockers.some(lockerId => eligibleDepots.get(lockerId)!.includes(id)))) continue

      const cells = scenario.cells.map(cell => ({ ...cell, choices: walksByCell.get(cell.id)!.filter(id => chosenLockers.includes(id)) }))
        .sort((a, b) => a.choices.length - b.choices.length || b.parcels - a.parcels || a.id.localeCompare(b.id))
      const lockerLoads = new Map(chosenLockers.map(id => [id, 0]))
      const assignments = new Map<string, string>()

      const assignSuppliers = () => {
        const ordered = [...chosenLockers].sort((a, b) => eligibleDepots.get(a)!.length - eligibleDepots.get(b)!.length || lockerLoads.get(b)! - lockerLoads.get(a)! || a.localeCompare(b))
        const depotLoads = new Map(chosenDepots.map(id => [id, 0]))
        const supplies = new Map<string, string>()
        const visit = (index: number): boolean => {
          if (shouldStop()) return false
          stats.supplyBranchesVisited++
          if (chosenDepots.filter(id => depotLoads.get(id) === 0).length > ordered.length - index) return false
          if (index === ordered.length) return chosenDepots.every(id => depotLoads.get(id)! > 0)
          const lockerId = ordered[index]
          const load = lockerLoads.get(lockerId)!
          for (const depotId of eligibleDepots.get(lockerId)!) {
            if (depotLoads.get(depotId)! + load > request.depotCapacity) continue
            depotLoads.set(depotId, depotLoads.get(depotId)! + load); supplies.set(lockerId, depotId)
            if (visit(index + 1)) return true
            depotLoads.set(depotId, depotLoads.get(depotId)! - load); supplies.delete(lockerId)
          }
          return false
        }
        if (!visit(0)) return undefined
        return chosenLockers.map(lockerId => ({ lockerId, depotId: supplies.get(lockerId)! }))
      }

      const assignCells = (index: number): boolean => {
        if (shouldStop()) return false
        stats.assignmentBranchesVisited++
        const remaining = cells.length - index
        const unused = chosenLockers.filter(id => lockerLoads.get(id) === 0)
        if (unused.length > remaining) return false
        if (unused.some(lockerId => !cells.slice(index).some(cell => cell.choices.includes(lockerId)))) return false
        if (cells.slice(index).reduce((sum, cell) => sum + cell.parcels, 0) > chosenLockers.reduce((sum, id) => sum + request.lockerCapacity - lockerLoads.get(id)!, 0)) return false
        if (index === cells.length) {
          if (unused.length) return false
          const supplies = assignSuppliers()
          if (!supplies) return false
          found = {
            lockerIds: [...chosenLockers], depotIds: [...chosenDepots],
            assignments: scenario.cells.map(cell => ({ cellId: cell.id, lockerId: assignments.get(cell.id)! })), supplies,
          }
          return true
        }
        const cell = cells[index]
        for (const lockerId of cell.choices) {
          if (lockerLoads.get(lockerId)! + cell.parcels > request.lockerCapacity) continue
          lockerLoads.set(lockerId, lockerLoads.get(lockerId)! + cell.parcels); assignments.set(cell.id, lockerId)
          if (assignCells(index + 1)) return true
          lockerLoads.set(lockerId, lockerLoads.get(lockerId)! - cell.parcels); assignments.delete(cell.id)
        }
        return false
      }
      if (assignCells(0)) break
    }
    if (found || stopped) break
  }

  if (stopped) return { status: stopped, message: stopped === 'cancelled' ? 'Cancelled. No feasibility claim was made.' : 'Exhaustive search reached its time limit. No feasibility claim was made.', elapsedMs: elapsedMs(), search: stats }
  if (!found) return { status: 'unsat', rules: allRuleGroups(request), elapsedMs: elapsedMs(), search: stats }
  hooks.onPhase?.('verifying')
  const verification = verifyPlan(scenario, request, found)
  if (!verification.valid) return { status: 'error', message: `Independent verification failed: ${verification.errors.join('; ')}`, elapsedMs: elapsedMs(), search: stats }
  return { status: 'feasible', plan: found, verification, elapsedMs: elapsedMs(), search: stats }
}
