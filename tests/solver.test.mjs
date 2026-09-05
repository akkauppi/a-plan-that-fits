import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { init, killThreads } from 'z3-solver';
import { solveScenario } from '../src/solver/model.ts';
import { verifyPlan } from '../src/core/verify.ts';

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)));
const api = await init();
after(async () => { await killThreads(api.em); });
const request = (overrides = {}) => ({ ...scenario.defaults, timeoutMs: 30000, ...overrides });
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
  assert.equal(result.plan.lockerIds.length, 10);
  assert.equal(result.plan.depotIds.length, 4);
  assert.equal(result.plan.outagePlans.length, 4);
  assert.equal(Object.keys(result.verification.outageDepotLoads).length, 4);
  for (const loads of Object.values(result.verification.outageDepotLoads)) assert.ok(Object.values(loads).every(load => load <= 600));
});
test('the planning game has at least one exact ten-locker, four-depot resilient win', async () => {
  const result = await run({ fixedLockerIds: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'N'], fixedDepotIds: ['West', 'North', 'East', 'Central-West'] });
  assert.equal(result.status, 'feasible', JSON.stringify(result));
  assert.equal(result.verification.valid, true);
  assert.equal(result.plan.outagePlans.length, 4);
});
test('three depots cannot preserve walking coverage after any one depot outage', async () => {
  const result = await run({ maxDepots: 3 });
  assert.equal(result.status, 'unsat');
  assert.ok(result.rules.some(r => r.id === 'depot_outage_supply'));
});
test('the offered rule changes really work, with walking still fixed at 500 m', async () => {
  for (const repair of [{ maxDepots: 3, depotOutageTolerance: 0 }, { maxLockers: 9 }]) {
    const result = await run(repair);
    assert.equal(result.status, 'feasible', JSON.stringify(result));
    assert.ok(result.verification.worstWalkMm <= 500000);
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
    p => { p.outagePlans.pop(); },
    p => { p.outagePlans[0].supplies[0].depotId = p.outagePlans[0].unavailableDepotId; },
  ]) {
    const plan = structuredClone(result.plan); corrupt(plan);
    assert.equal(verifyPlan(scenario, request(), plan).valid, false);
  }
  assert.equal(verifyPlan(scenario, request({ lockerCapacity: 1 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ depotCapacity: 435 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ flightLimitMm: 1 }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ fixedLockerIds: [] }), result.plan).valid, false);
  assert.equal(verifyPlan(scenario, request({ depotOutageTolerance: 0 }), result.plan).valid, false);
});
test('a cancelled request never returns UNSAT or a stale feasible plan', async () => {
  assert.equal((await run({}, { isCancelled: () => true })).status, 'cancelled');
  let cancelled = false;
  const result = await run({}, { isCancelled: () => cancelled, onPhase: () => { cancelled = true; } });
  assert.equal(result.status, 'cancelled');
});
