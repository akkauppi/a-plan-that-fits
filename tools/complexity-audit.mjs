import { readFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { validateScenario } from '../src/core/validate.ts'
import { solveByEnumeration } from '../src/exhaustive/model.ts'

function combinations(items, size) {
  if (size === 0) return [[]]
  if (size < 0 || size > items.length) return []
  const result = []
  const visit = (start, chosen) => {
    if (chosen.length === size) { result.push([...chosen]); return }
    for (let index = start; index <= items.length - (size - chosen.length); index++) {
      chosen.push(items[index]); visit(index + 1, chosen); chosen.pop()
    }
  }
  visit(0, [])
  return result
}

function binomial(n, k) {
  if (k < 0 || k > n) return 0n
  let result = 1n
  for (let index = 1; index <= Math.min(k, n - k); index++) result = result * BigInt(n - index + 1) / BigInt(index)
  return result
}

function summarize(values) {
  const sorted = [...values].sort((a, b) => a - b)
  return {
    min: sorted[0], median: sorted[Math.floor(sorted.length / 2)], max: sorted.at(-1),
    mean: Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2)),
  }
}

const deterministicSearch = result => ({
  status: result.status,
  lockerSetsChecked: result.search?.lockerSetsChecked ?? 0,
  siteSelectionsChecked: result.search?.siteSelectionsChecked ?? 0,
  assignmentBranchesVisited: result.search?.assignmentBranchesVisited ?? 0,
  supplyBranchesVisited: result.search?.supplyBranchesVisited ?? 0,
})

export async function auditComplexity(scenario) {
  validateScenario(scenario)
  const limits = scenario.defaults
  const lockerIds = scenario.lockers.map(site => site.id)
  const depotIds = scenario.depots.map(site => site.id)
  const lockerSets = combinations(lockerIds, limits.maxLockers)
  const depotSets = combinations(depotIds, limits.maxDepots)
  const walksByCell = new Map(scenario.cells.map(cell => [cell.id, scenario.walking.filter(pair => pair.cellId === cell.id).map(pair => pair.lockerId)]))
  const eligibleFlights = scenario.flights.filter(pair => pair.returnDistanceMm <= limits.flightLimitMm)
  const depotsByLocker = new Map(lockerIds.map(id => [id, eligibleFlights.filter(pair => pair.lockerId === id).map(pair => pair.depotId)]))
  const walkingDegrees = scenario.cells.map(cell => walksByCell.get(cell.id).length)
  const supplyDegrees = lockerIds.map(id => depotsByLocker.get(id).length)
  const locallyPlausible = []
  for (const lockers of lockerSets) {
    if (!scenario.cells.every(cell => walksByCell.get(cell.id).some(id => lockers.includes(id)))) continue
    for (const depots of depotSets) {
      if (lockers.every(lockerId => depotsByLocker.get(lockerId).some(id => depots.includes(id)))) locallyPlausible.push({ lockers, depots })
    }
  }

  const exactResults = { feasible: 0, unsat: 0, other: 0 }
  for (const selection of locallyPlausible) {
    const result = await solveByEnumeration(scenario, { ...limits, timeoutMs: 15000, fixedLockerIds: selection.lockers, fixedDepotIds: selection.depots })
    if (result.status === 'feasible') exactResults.feasible++
    else if (result.status === 'unsat') exactResults.unsat++
    else exactResults.other++
  }
  const joint = await solveByEnumeration(scenario, { ...limits, timeoutMs: 15000 })
  const oneFewerLocker = await solveByEnumeration(scenario, { ...limits, maxLockers: limits.maxLockers - 1, timeoutMs: 15000 })
  return {
    schemaVersion: 1,
    scenario: { id: scenario.id, snapshotId: scenario.snapshotId, cells: scenario.cells.length, lockers: lockerIds.length, depots: depotIds.length },
    defaultBudgets: { lockers: limits.maxLockers, depots: limits.maxDepots },
    rawExactSiteSelections: (binomial(lockerIds.length, limits.maxLockers) * binomial(depotIds.length, limits.maxDepots)).toString(),
    walking: {
      eligiblePairs: scenario.walking.length,
      optionsPerCell: summarize(walkingDegrees),
      rawAssignmentsAcrossAllCandidates: walkingDegrees.reduce((product, value) => product * BigInt(value), 1n).toString(),
    },
    supply: {
      eligiblePairsAtDefaultRange: eligibleFlights.length,
      optionsPerLocker: summarize(supplyDegrees),
      rawAssignmentsAcrossAllCandidates: supplyDegrees.reduce((product, value) => product * BigInt(value), 1n).toString(),
    },
    exactBudgetAudit: { locallyPlausibleSelections: locallyPlausible.length, fullResults: exactResults },
    exhaustiveProfiles: { jointDefault: deterministicSearch(joint), oneFewerLocker: deterministicSearch(oneFewerLocker) },
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)))
  const audit = await auditComplexity(scenario)
  if (process.argv.includes('--json')) console.log(JSON.stringify(audit, null, 2))
  else {
    console.log(`Complexity audit · ${audit.scenario.id} · ${audit.scenario.snapshotId}`)
    console.log(`${audit.scenario.cells} cells · ${audit.scenario.lockers} lockers choose ${audit.defaultBudgets.lockers} · ${audit.scenario.depots} depots choose ${audit.defaultBudgets.depots}`)
    console.log(`${Number(audit.rawExactSiteSelections).toLocaleString('en-GB')} raw exact site selections`)
    console.log(`${audit.walking.eligiblePairs} eligible walks · cell options min/median/max ${audit.walking.optionsPerCell.min}/${audit.walking.optionsPerCell.median}/${audit.walking.optionsPerCell.max}`)
    console.log(`${audit.supply.eligiblePairsAtDefaultRange} eligible flights · depot options per locker min/median/max ${audit.supply.optionsPerLocker.min}/${audit.supply.optionsPerLocker.median}/${audit.supply.optionsPerLocker.max}`)
    console.log(`${audit.exactBudgetAudit.locallyPlausibleSelections} selections pass the visible walking/range checks · ${audit.exactBudgetAudit.fullResults.feasible} feasible · ${audit.exactBudgetAudit.fullResults.unsat} impossible under the full model`)
    for (const [name, profile] of Object.entries(audit.exhaustiveProfiles)) console.log(`${name}: ${profile.status} · ${profile.lockerSetsChecked} locker sets · ${profile.siteSelectionsChecked} complete site selections · ${profile.assignmentBranchesVisited} collection branches · ${profile.supplyBranchesVisited} supply branches`)
    console.log('Counts and branch profiles are deterministic. Elapsed time is deliberately excluded; use the browser comparison for illustrative timing.')
  }
}
