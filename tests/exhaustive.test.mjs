import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { init, killThreads } from 'z3-solver'
import { solveScenario } from '../src/solver/model.ts'
import { solveByEnumeration } from '../src/exhaustive/model.ts'

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)))
const api = await init()
after(async () => { await killThreads(api.em) })
const request = overrides => ({ ...scenario.defaults, timeoutMs: 15000, ...overrides })

test('exhaustive JavaScript and Z3 agree on every pinned geographic question', async () => {
  const cases = [
    {},
    { fixedLockerIds: ['A', 'C', 'D', 'E', 'G', 'K', 'L', 'N'], fixedDepotIds: ['West', 'East'] },
    { fixedLockerIds: scenario.starterLockerIds },
    { fixedLockerIds: scenario.starterLockerIds, maxDepots: 3 },
    { fixedLockerIds: scenario.starterLockerIds, flightLimitMm: 2400000 },
    { maxLockers: 7 },
  ]
  for (const overrides of cases) {
    const input = request(overrides)
    const [z3, exhaustive] = await Promise.all([solveScenario(api, scenario, input), solveByEnumeration(scenario, input)])
    assert.equal(exhaustive.status, z3.status, JSON.stringify({ overrides, z3, exhaustive }))
    assert.equal(exhaustive.search?.kind, 'exhaustive')
    if (exhaustive.status === 'feasible') assert.equal(exhaustive.verification.valid, true)
  }
})

test('exhaustive search preserves exact empty selections, errors and cancellation semantics', async () => {
  assert.equal((await solveByEnumeration(scenario, request({ fixedLockerIds: [] }))).status, 'unsat')
  assert.equal((await solveByEnumeration(scenario, request({ fixedDepotIds: [] }))).status, 'unsat')
  assert.equal((await solveByEnumeration(scenario, request({ fixedLockerIds: ['unknown'] }))).status, 'error')
  assert.equal((await solveByEnumeration(scenario, request({}), { isCancelled: () => true })).status, 'cancelled')
})
