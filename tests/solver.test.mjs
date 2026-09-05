import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { init, killThreads } from 'z3-solver';
import { solveScenario } from '../src/solver/model.ts';
import { verifyPlan } from '../src/core/verify.ts';

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)));
const api = await init();
after(async () => { await killThreads(api.em); });
const request = (overrides = {}) => ({ ...scenario.defaults, timeoutMs: 15000, ...overrides });
const run = (overrides = {}, hooks) => solveScenario(api, scenario, request(overrides), hooks);

test('joint choices: all demand gets independently verified collection and supply', async () => {
  const result = await run();
  assert.equal(result.status, 'feasible', JSON.stringify(result));
  assert.equal(result.verification.valid, true);
  assert.equal(result.verification.parcelTotal, 871);
  assert.equal(result.verification.routesChecked, 33);
  assert.ok(result.verification.worstWalkMm <= 500000);
  assert.ok(result.verification.longestFlightMm <= 2000000);
  assert.ok(Object.values(result.verification.depotLoads).every(load => load <= 600));
  assert.equal(result.plan.lockerIds.length, 8);
  assert.equal(result.plan.depotIds.length, 2);
});
test('the planning game has at least one exact eight-locker, two-depot win', async () => {
  const result = await run({ fixedLockerIds: ['A', 'C', 'D', 'E', 'G', 'K', 'L', 'N'], fixedDepotIds: ['West', 'East'] });
  assert.equal(result.status, 'feasible', JSON.stringify(result));
  assert.equal(result.verification.valid, true);
});
test('starter solves walking alone but cannot be supplied from ANY two depots', async () => {
  const result = await run({ fixedLockerIds: scenario.starterLockerIds });
  assert.equal(result.status, 'unsat');
  assert.ok(result.rules.some(r => r.id === 'fixed_lockers'));
  assert.ok(result.rules.some(r => r.id === 'depot_budget'));
  const destinations = lockerId => scenario.flights.filter(f => f.lockerId === lockerId && f.returnDistanceMm <= 2000000).map(f => f.depotId);
  assert.deepEqual(destinations('H'), ['South']);
  assert.deepEqual(destinations('I'), ['West']);
  assert.deepEqual(destinations('E').sort(), ['East', 'North']);
});
test('both offered repairs really work, with walking still fixed at 500 m', async () => {
  for (const repair of [{ maxDepots: 3 }, { flightLimitMm: 2400000 }]) {
    const result = await run({ fixedLockerIds: scenario.starterLockerIds, ...repair });
    assert.equal(result.status, 'feasible', JSON.stringify(result));
    assert.deepEqual(result.plan.lockerIds.sort(), [...scenario.starterLockerIds].sort());
    assert.ok(result.verification.worstWalkMm <= 500000);
  }
});
test('seven lockers is globally impossible for this candidate set, even with ample capacity', async () => {
  for (const extra of [{}, { lockerCapacity: 1000, maxDepots: 4, depotCapacity: 1000, flightLimitMm: 4000000 }]) {
    assert.equal((await run({ maxLockers: 7, ...extra })).status, 'unsat');
  }
});
test('empty exact selections mean zero, not free choice; invalid selections are errors', async () => {
  for (const selection of [{ fixedLockerIds: [] }, { fixedDepotIds: [] }, { fixedDepotIds: ['West'] }]) assert.equal((await run(selection)).status, 'unsat');
  assert.equal((await run({ fixedLockerIds: ['not-a-site'] })).status, 'error');
  assert.equal((await run({ fixedDepotIds: ['West', 'West'] })).status, 'error');
  assert.equal((await run({ maxDepots: -1 })).status, 'error');
});
test('independent verifier rejects lost, duplicated, closed and over-capacity assignments', async () => {
  const result = await run(); assert.equal(result.status, 'feasible');
  for (const corrupt of [
    p => { p.assignments.pop(); },
    p => { p.assignments.push(p.assignments[0]); },
    p => { p.lockerIds.pop(); },
    p => { p.supplies.pop(); },
    p => { p.supplies.push(p.supplies[0]); },
    p => { p.supplies.forEach(s => { s.depotId = p.depotIds[0]; }); },
  ]) {
    const plan = structuredClone(result.plan); corrupt(plan);
    assert.equal(verifyPlan(scenario, request(), plan).valid, false);
  }
  assert.equal(verifyPlan(scenario, request({ lockerCapacity: 1 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ depotCapacity: 435 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ flightLimitMm: 1 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ fixedLockerIds: [] }), result.plan).valid, false);
});
test('a cancelled request never returns UNSAT or a stale feasible plan', async () => {
  assert.equal((await run({}, { isCancelled: () => true })).status, 'cancelled');
  let cancelled = false;
  const result = await run({}, { isCancelled: () => cancelled, onPhase: () => { cancelled = true; } });
  assert.equal(result.status, 'cancelled');
});
