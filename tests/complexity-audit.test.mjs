import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { auditComplexity } from '../tools/complexity-audit.mjs'

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)))

test('complexity audit exposes raw size, effective pruning and full exact-selection outcomes', async () => {
  const audit = await auditComplexity(scenario)
  assert.deepEqual(audit.scenario, { id: 'otaniemi-resilient-drone-lockers-v2', snapshotId: scenario.snapshotId, cells: 33, lockers: 24, depots: 6 })
  assert.equal(audit.rawExactSiteSelections, '29418840')
  assert.deepEqual(audit.walking.optionsPerCell, { min: 3, median: 3, max: 6, mean: 3.64 })
  assert.equal(audit.walking.eligiblePairs, 120)
  assert.equal(audit.exactBudgetAudit.complete, false)
  assert.deepEqual(audit.resilienceBoundary, {
    selectedDepots: 3,
    depotSelectionsChecked: 20,
    selectionsWithFullLocalCoverage: 0,
    bestCoveredCellCount: 27,
  })
  assert.deepEqual(audit.exhaustiveProfiles.jointDefault, {
    status: 'feasible', lockerSetsChecked: 240, siteSelectionsChecked: 173,
    assignmentBranchesVisited: 36, supplyBranchesVisited: 56,
  })
  assert.deepEqual(audit.exhaustiveProfiles.oneFewerLocker, {
    status: 'feasible', lockerSetsChecked: 15744, siteSelectionsChecked: 173,
    assignmentBranchesVisited: 34, supplyBranchesVisited: 51,
  })
})
