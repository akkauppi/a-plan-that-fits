import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { auditComplexity } from '../tools/complexity-audit.mjs'

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)))

test('complexity audit exposes raw size, effective pruning and full exact-selection outcomes', async () => {
  const audit = await auditComplexity(scenario)
  assert.deepEqual(audit.scenario, { id: 'otaniemi-drone-lockers-v1', snapshotId: scenario.snapshotId, cells: 33, lockers: 15, depots: 4 })
  assert.equal(audit.rawExactSiteSelections, '38610')
  assert.deepEqual(audit.walking.optionsPerCell, { min: 2, median: 2, max: 4, mean: 2.36 })
  assert.equal(audit.walking.eligiblePairs, 78)
  assert.equal(audit.exactBudgetAudit.locallyPlausibleSelections, 16)
  assert.deepEqual(audit.exactBudgetAudit.fullResults, { feasible: 16, unsat: 0, other: 0 })
  assert.deepEqual(audit.exhaustiveProfiles.jointDefault, {
    status: 'feasible', lockerSetsChecked: 903, siteSelectionsChecked: 24,
    assignmentBranchesVisited: 34, supplyBranchesVisited: 9,
  })
  assert.deepEqual(audit.exhaustiveProfiles.oneFewerLocker, {
    status: 'unsat', lockerSetsChecked: 16384, siteSelectionsChecked: 0,
    assignmentBranchesVisited: 0, supplyBranchesVisited: 0,
  })
})
