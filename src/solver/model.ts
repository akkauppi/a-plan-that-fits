import type { init, Bool, Arith } from 'z3-solver'
import type { ConflictRule, Scenario, SolveRequest, SolveResult } from '../core/types.ts'
import { validateScenario, validateRequest } from '../core/validate.ts'
import { verifyPlan } from '../core/verify.ts'

type Z3 = Awaited<ReturnType<typeof init>>
export interface SolveHooks {
  isCancelled?: () => boolean
  onInterruptReady?: (interrupt: () => void) => void
  onPhase?: (phase: 'solving' | 'verifying') => void
}

// Feasibility, not optimisation. Only admissible walking/supply pairs get a
// Boolean decision. No paths are invented by Z3, and no assignment is fractional.
export async function solveScenario(api: Z3, scenario: Scenario, request: SolveRequest, hooks: SolveHooks = {}): Promise<SolveResult> {
  const start = performance.now()
  const elapsedMs = () => Math.round(performance.now() - start)
  const cancelled = (): SolveResult => ({ status: 'cancelled', message: 'Cancelled. No feasibility claim was made.', elapsedMs: elapsedMs() })
  if (hooks.isCancelled?.()) return cancelled()
  try { validateScenario(scenario); validateRequest(scenario, request) }
  catch (error) { return { status: 'error', message: String(error), elapsedMs: elapsedMs() } }

  const ctx = new api.Context('parcel')
  const { Bool, Int, If, Sum, And, Or, Implies } = ctx
  const solver = new ctx.Solver()
  solver.set('timeout', request.timeoutMs)
  hooks.onInterruptReady?.(() => ctx.interrupt())
  const rules: ConflictRule[] = []
  const track = (id: string, label: string, constraints: Bool<'parcel'>[]) => {
    rules.push({ id, label }); solver.addAndTrack(And(...constraints), id)
  }
  const sum = (terms: Arith<'parcel'>[]) => terms.length ? Sum(terms[0], ...terms.slice(1)) : Int.val(0)
  const openLockers = scenario.lockers.map((_, i) => Bool.const(`locker_${i}`))
  const openDepots = scenario.depots.map((_, i) => Bool.const(`depot_${i}`))
  const walks = scenario.walking.map((pair, i) => ({ ...pair, decision: Bool.const(`collect_${i}`) }))
  const eligibleFlightPairs = scenario.flights.filter(pair => pair.returnDistanceMm <= request.flightLimitMm)
  const flights = eligibleFlightPairs.map((pair, i) => ({ ...pair, decision: Bool.const(`supply_${i}`) }))
  const outageCases = (request.depotOutageTolerance ?? 0) === 1 ? scenario.depots.map((unavailableDepot, failureIndex) => ({
    unavailableDepot,
    active: openDepots[failureIndex],
    flights: eligibleFlightPairs.filter(pair => pair.depotId !== unavailableDepot.id).map((pair, i) => ({ ...pair, decision: Bool.const(`outage_${failureIndex}_supply_${i}`) })),
  })) : []
  const cellParcels = new Map(scenario.cells.map(c => [c.id, c.parcels]))
  const loads = scenario.lockers.map(locker => sum(walks.filter(w => w.lockerId === locker.id).map(w => If(w.decision, Int.val(cellParcels.get(w.cellId)!), Int.val(0)))))
  try {
    track('collection', 'Every cell goes to exactly one open locker along a walk of at most 500 m.', [
      ...scenario.cells.map(cell => sum(walks.filter(w => w.cellId === cell.id).map(w => If(w.decision, Int.val(1), Int.val(0)))).eq(1)),
      ...scenario.lockers.map((locker, i) => openLockers[i].eq(Or(...walks.filter(w => w.lockerId === locker.id).map(w => w.decision)))),
    ])
    track('locker_budget', `Open at most ${request.maxLockers} lockers.`, [sum(openLockers.map(v => If(v, Int.val(1), Int.val(0)))).le(request.maxLockers)])
    track('locker_capacity', `Each locker handles at most ${request.lockerCapacity} parcels per day.`, loads.map(load => load.le(request.lockerCapacity)))
    track('supply', `Each open locker has one open supplier within a ${(request.flightLimitMm / 1000000).toFixed(1)} km return flight.`, [
      ...scenario.lockers.map((locker, i) => sum(flights.filter(f => f.lockerId === locker.id).map(f => If(f.decision, Int.val(1), Int.val(0)))).eq(If(openLockers[i], Int.val(1), Int.val(0)))),
      ...scenario.depots.map((depot, i) => openDepots[i].eq(Or(...flights.filter(f => f.depotId === depot.id).map(f => f.decision)))),
    ])
    track('depot_budget', `Open at most ${request.maxDepots} depots.`, [sum(openDepots.map(v => If(v, Int.val(1), Int.val(0)))).le(request.maxDepots)])
    track('depot_capacity', `Each depot supplies at most ${request.depotCapacity} parcels per day across all its lockers.`, scenario.depots.map(depot => sum(flights.filter(f => f.depotId === depot.id).map(f => If(f.decision, loads[scenario.lockers.findIndex(l => l.id === f.lockerId)], Int.val(0)))).le(request.depotCapacity)))
    if (outageCases.length) {
      track('depot_outage_supply', 'Every open locker can be reassigned to an open in-range depot after any one open depot is unavailable.', outageCases.flatMap(outage => [
        ...scenario.lockers.map((locker, i) => sum(outage.flights.filter(f => f.lockerId === locker.id).map(f => If(f.decision, Int.val(1), Int.val(0)))).eq(If(And(outage.active, openLockers[i]), Int.val(1), Int.val(0)))),
        ...outage.flights.map(flight => Implies(flight.decision, openDepots[scenario.depots.findIndex(depot => depot.id === flight.depotId)])),
      ]))
      track('depot_outage_capacity', `After any one open depot is unavailable, each remaining depot supplies at most ${request.depotCapacity} parcels per day.`, outageCases.flatMap(outage => scenario.depots.map(depot => sum(outage.flights.filter(f => f.depotId === depot.id).map(f => If(f.decision, loads[scenario.lockers.findIndex(l => l.id === f.lockerId)], Int.val(0)))).le(request.depotCapacity))))
    }
    if (request.fixedLockerIds !== undefined) track('fixed_lockers', `Keep exactly these lockers: ${request.fixedLockerIds.join(', ') || 'none'}.`, scenario.lockers.map((l, i) => openLockers[i].eq(Bool.val(request.fixedLockerIds!.includes(l.id)))))
    if (request.fixedDepotIds !== undefined) track('fixed_depots', `Keep exactly these depots: ${request.fixedDepotIds.join(', ') || 'none'}.`, scenario.depots.map((d, i) => openDepots[i].eq(Bool.val(request.fixedDepotIds!.includes(d.id)))))
    if (hooks.isCancelled?.()) return cancelled()
    hooks.onPhase?.('solving')
    const status = await solver.check()
    if (hooks.isCancelled?.()) return cancelled()
    if (status === 'unknown') {
      const reason = solver.reasonUnknown()
      return { status: /timeout|canceled|cancelled|resource/i.test(reason) ? 'timeout' : 'error', message: `No conclusion: ${reason}. This does not mean the rules are impossible.`, elapsedMs: elapsedMs() }
    }
    if (status === 'unsat') {
      const core = new Set([...solver.unsatCore().values()].map(value => value.toString()))
      return { status: 'unsat', rules: rules.filter(rule => core.has(rule.id)), elapsedMs: elapsedMs() }
    }
    const model = solver.model()
    try {
      const selected = (value: Bool<'parcel'>) => ctx.isTrue(model.eval(value, true))
      const plan = {
        lockerIds: scenario.lockers.filter((_, i) => selected(openLockers[i])).map(l => l.id),
        depotIds: scenario.depots.filter((_, i) => selected(openDepots[i])).map(d => d.id),
        assignments: walks.filter(w => selected(w.decision)).map(({ cellId, lockerId }) => ({ cellId, lockerId })),
        supplies: flights.filter(f => selected(f.decision)).map(({ lockerId, depotId }) => ({ lockerId, depotId })),
        outagePlans: outageCases.filter(outage => selected(outage.active)).map(outage => ({
          unavailableDepotId: outage.unavailableDepot.id,
          supplies: outage.flights.filter(f => selected(f.decision)).map(({ lockerId, depotId }) => ({ lockerId, depotId })),
        })),
      }
      hooks.onPhase?.('verifying')
      const verification = verifyPlan(scenario, request, plan)
      if (!verification.valid) return { status: 'error', message: `Independent verification failed: ${verification.errors.join('; ')}`, elapsedMs: elapsedMs() }
      return { status: 'feasible', plan, verification, elapsedMs: elapsedMs() }
    } finally { model.release() }
  } catch (error) {
    return hooks.isCancelled?.() ? cancelled() : { status: 'error', message: String(error), elapsedMs: elapsedMs() }
  } finally { solver.release() }
}
