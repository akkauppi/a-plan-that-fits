import { readFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { graphIndex } from '../src/core/graph.ts'
import { returnFlightMm } from '../src/core/validate.ts'
import { replayCandidateSelection } from './candidate-selection.mjs'

const combinations = (items, size) => {
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

const binomial = (n, k) => {
  let result = 1n
  for (let index = 1; index <= Math.min(k, n - k); index++) result = result * BigInt(n - index + 1) / BigInt(index)
  return result
}

const lockerLabel = index => String.fromCharCode('A'.charCodeAt(0) + index)

function nearestNode(nodes, target, excludedIds) {
  let best
  for (const node of nodes) {
    if (excludedIds.has(node.id)) continue
    const offsetMm = Math.round(Math.hypot(node.xyMm[0] - target[0], node.xyMm[1] - target[1]))
    if (!best || offsetMm < best.offsetMm || offsetMm === best.offsetMm && node.id < best.node.id) best = { node, offsetMm }
  }
  return best
}

const bitCount = value => {
  let count = 0
  while (value) { value &= value - 1n; count++ }
  return count
}

function findCover(lockers, cellIds, maximumLockers) {
  const cellIndex = new Map(cellIds.map((id, index) => [id, index]))
  const target = (1n << BigInt(cellIds.length)) - 1n
  const masks = lockers.map(locker => locker.cellIds.reduce((mask, id) => mask | 1n << BigInt(cellIndex.get(id)), 0n))
  const candidatesByCell = cellIds.map((_, cell) => masks.flatMap((mask, index) => mask & 1n << BigInt(cell) ? [index] : []))
  const seen = new Set()
  const visit = (covered, chosen) => {
    if (covered === target) return chosen.map(index => lockers[index].id)
    if (chosen.length === maximumLockers) return undefined
    const key = `${covered}:${chosen.length}`
    if (seen.has(key)) return undefined
    seen.add(key)
    let options
    for (let cell = 0; cell < cellIds.length; cell++) {
      if (covered & 1n << BigInt(cell)) continue
      const useful = candidatesByCell[cell].filter(index => ((~covered) & masks[index] & target) !== 0n)
      if (!useful.length) return undefined
      if (!options || useful.length < options.length) options = useful
    }
    options.sort((a, b) => bitCount((~covered) & masks[b] & target) - bitCount((~covered) & masks[a] & target) || lockers[a].id.localeCompare(lockers[b].id, 'en'))
    for (const index of options) {
      const result = visit(covered | masks[index], [...chosen, index])
      if (result) return result
    }
  }
  return visit(0n, [])
}

function resilienceAudit(depots, lockers, cells, selectedDepotCount, maximumLockers, flightLimitMm) {
  return combinations(depots, selectedDepotCount).map(chosenDepots => {
    const depotIds = new Set(chosenDepots.map(depot => depot.id))
    const robustLockers = lockers.filter(locker => locker.reachableDepotIds.filter(id => depotIds.has(id)).length >= 2)
    const coveredCellIds = new Set(robustLockers.flatMap(locker => locker.cellIds))
    const cover = coveredCellIds.size === cells.length ? findCover(robustLockers, cells.map(cell => cell.id), maximumLockers) : undefined
    return {
      depotIds: chosenDepots.map(depot => depot.id),
      robustLockerCount: robustLockers.length,
      robustCoverageCellCount: coveredCellIds.size,
      coverWithinLockerBudget: cover ?? null,
    }
  })
}

// This is a read-only design audit, not a data builder. It independently derives
// the expanded candidate scene without changing the recipe or generated data.
export function proposeExpandedScenario(scenario) {
  const network = graphIndex(scenario.network)
  const selection = replayCandidateSelection(scenario.network, scenario.cells, { minimumChoices: 3, minimumSpacingMm: 80000 })
  const lockers = selection.steps.map((step, index) => {
    const node = network.nodes.get(step.nodeId)
    return { id: lockerLabel(index), nodeId: node.id, xyMm: node.xyMm, cellIds: step.reachableCellIds }
  })
  const xs = scenario.cells.map(cell => cell.xyMm[0])
  const ys = scenario.cells.map(cell => cell.xyMm[1])
  const center = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]
  const edgeDepotIds = new Set(['West', 'North', 'East', 'South'])
  const edgeDepots = scenario.depots.filter(depot => edgeDepotIds.has(depot.id))
  const existingDepotNodeIds = new Set(edgeDepots.map(depot => depot.nodeId))
  const extraDepotTargets = [
    { id: 'Central-West', xyMm: [center[0] - 300000, center[1]] },
    { id: 'Central-East', xyMm: [center[0] + 300000, center[1]] },
  ]
  const extraDepots = extraDepotTargets.map(target => {
    const match = nearestNode(scenario.network.nodes, target.xyMm, existingDepotNodeIds)
    existingDepotNodeIds.add(match.node.id)
    return { id: target.id, nodeId: match.node.id, xyMm: match.node.xyMm, targetXyMm: target.xyMm, offsetMm: match.offsetMm }
  })
  const depots = [...edgeDepots.map(({ id, nodeId, xyMm }) => ({ id, nodeId, xyMm })), ...extraDepots]
  for (const locker of lockers) locker.reachableDepotIds = depots
    .filter(depot => returnFlightMm(locker.xyMm, depot.xyMm) <= scenario.defaults.flightLimitMm)
    .map(depot => depot.id)
  const proposed = { lockers: 10, depots: 4, tolerateDepotOutages: 1 }
  const threeDepotAudit = resilienceAudit(depots, lockers, scenario.cells, 3, proposed.lockers, scenario.defaults.flightLimitMm)
  const fourDepotAudit = resilienceAudit(depots, lockers, scenario.cells, proposed.depots, proposed.lockers, scenario.defaults.flightLimitMm)
  return {
    schemaVersion: 1,
    status: 'implemented-geography-audit',
    unchangedRules: { walkingLimitMm: scenario.walkingLimitMm, flightLimitMm: scenario.defaults.flightLimitMm },
    candidateMethod: {
      consideredNetworkNodes: selection.consideredNodes,
      minimumChoicesPerCell: selection.requestedMinimumChoices,
      minimumSpacingMm: selection.minimumSpacingMm,
    },
    proposedBudgets: proposed,
    rawExactSiteSelections: (binomial(lockers.length, proposed.lockers) * binomial(depots.length, proposed.depots)).toString(),
    lockers: lockers.map(({ id, nodeId, cellIds, reachableDepotIds }) => ({ id, nodeId, reachableCellCount: cellIds.length, reachableDepotIds })),
    depots: depots.map(({ id, nodeId, targetXyMm, offsetMm }) => ({ id, nodeId, ...(targetXyMm ? { targetXyMm, offsetMm } : {}) })),
    resilience: {
      meaning: 'Every selected locker remains reachable from a selected depot after any one selected depot is unavailable.',
      threeSelectedDepots: {
        combinationsChecked: threeDepotAudit.length,
        combinationsWithFullLocalCoverage: threeDepotAudit.filter(item => item.coverWithinLockerBudget).length,
        bestRobustCoverageCellCount: Math.max(...threeDepotAudit.map(item => item.robustCoverageCellCount)),
      },
      fourSelectedDepots: {
        combinationsChecked: fourDepotAudit.length,
        combinationsWithFullLocalCoverage: fourDepotAudit.filter(item => item.coverWithinLockerBudget).length,
        witnesses: fourDepotAudit.filter(item => item.coverWithinLockerBudget),
      },
    },
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)))
  const proposal = proposeExpandedScenario(scenario)
  if (process.argv.includes('--json')) console.log(JSON.stringify(proposal, null, 2))
  else {
    console.log('Expanded scenario geography audit (does not modify generated data)')
    console.log(`${proposal.lockers.length} lockers choose ${proposal.proposedBudgets.lockers} · ${proposal.depots.length} depots choose ${proposal.proposedBudgets.depots}`)
    console.log(`${Number(proposal.rawExactSiteSelections).toLocaleString('en-GB')} raw exact site selections`)
    console.log(`Locker rule: at least ${proposal.candidateMethod.minimumChoicesPerCell} walking choices per cell, candidates at least ${proposal.candidateMethod.minimumSpacingMm / 1000} m apart`)
    console.log(`Three depots + one outage: 0/${proposal.resilience.threeSelectedDepots.combinationsChecked} choices preserve full local coverage (best ${proposal.resilience.threeSelectedDepots.bestRobustCoverageCellCount}/${scenario.cells.length} cells)`)
    console.log(`Four depots + one outage: ${proposal.resilience.fourSelectedDepots.combinationsWithFullLocalCoverage}/${proposal.resilience.fourSelectedDepots.combinationsChecked} choices have a locker cover within budget`)
    for (const witness of proposal.resilience.fourSelectedDepots.witnesses) console.log(`  ${witness.depotIds.join(' + ')} → lockers ${witness.coverWithinLockerBudget.join(', ')}`)
    console.log('This command checks local walking/range resilience only. Capacity and contingency assignments are checked separately by both solvers and the independent verifier.')
  }
}
