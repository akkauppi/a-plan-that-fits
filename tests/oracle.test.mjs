import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { init, killThreads } from 'z3-solver';
import { solveScenario } from '../src/solver/model.ts';

// Tiny, fully enumerable geography: two points 400 m apart, two lockers,
// two collocated depots, two parcels per cell. Not copied from solver expressions.
const nodes = [0, 400000].map((x, i) => ({ id: `n${i}`, point: [x / 1000000, 0], xyMm: [x, 0] }));
const edges = [{ id: 'ab', from: 'n0', to: 'n1', lengthMm: 400000, coordinates: nodes.map(n => n.point) }, { id: 'ba', from: 'n1', to: 'n0', lengthMm: 400000, coordinates: nodes.map(n => n.point).reverse() }];
const sites = prefix => nodes.map((n, i) => ({ ...n, nodeId: n.id, id: `${prefix}${i}`, label: `${prefix}${i}` }));
const cells = nodes.map((n, i) => ({ id: `c${i}`, nodeId: n.id, point: n.point, xyMm: n.xyMm, connectorMm: 0, polygon: [], population: 20, parcels: 2 }));
const scenario = {
  schemaVersion: 1, id: 'oracle', snapshotId: 'oracle', walkingLimitMm: 500000, center: [0, 0], provenance: {},
  network: { nodes, edges }, cells, lockers: sites('l'), depots: sites('d'),
  walking: cells.flatMap((c, i) => [0, 1].map(j => ({ cellId: c.id, lockerId: `l${j}`, distanceMm: i === j ? 0 : 400000, edgeIds: i === j ? [] : [i === 0 ? 'ab' : 'ba'] }))),
  flights: [0, 1].flatMap(i => [0, 1].map(j => ({ lockerId: `l${i}`, depotId: `d${j}`, returnDistanceMm: i === j ? 0 : 800000 }))),
  defaults: { maxLockers: 2, maxDepots: 2, lockerCapacity: 3, depotCapacity: 4, flightLimitMm: 600000 },
  starterLockerIds: ['l0', 'l1'], starterAssignments: [{ cellId: 'c0', lockerId: 'l0' }, { cellId: 'c1', lockerId: 'l1' }],
};
function enumerate(request) {
  const exact = (chosen, fixed) => fixed === undefined || chosen.length === fixed.length && fixed.every(id => chosen.includes(id));
  for (const first of [0, 1]) for (const second of [0, 1]) {
    const chosen = [...new Set([first, second])];
    const loads = [0, 0]; loads[first] += 2; loads[second] += 2;
    if (chosen.length > request.maxLockers || loads.some(load => load > request.lockerCapacity) || !exact(chosen.map(i => `l${i}`), request.fixedLockerIds)) continue;
    for (const westSupplier of [0, 1]) for (const eastSupplier of [0, 1]) {
      const suppliers = [westSupplier, eastSupplier];
      const openDepots = [...new Set(chosen.map(i => suppliers[i]))];
      const supplied = [0, 0]; for (const i of chosen) supplied[suppliers[i]] += loads[i];
      if (openDepots.length > request.maxDepots || supplied.some(load => load > request.depotCapacity) || !exact(openDepots.map(i => `d${i}`), request.fixedDepotIds)) continue;
      if (chosen.some(i => 2 * Math.abs(nodes[i].xyMm[0] - nodes[suppliers[i]].xyMm[0]) > request.flightLimitMm)) continue;
      return true;
    }
  }
  return false;
}
const api = await init();
after(async () => { await killThreads(api.em); });
test('real Z3 agrees with exhaustive enumeration across small budget/capacity/range cases', async () => {
  let checked = 0;
  for (const maxLockers of [1, 2]) for (const maxDepots of [1, 2]) for (const lockerCapacity of [3, 4]) for (const depotCapacity of [2, 4]) for (const flightLimitMm of [600000, 800000]) {
    const request = { maxLockers, maxDepots, lockerCapacity, depotCapacity, flightLimitMm, timeoutMs: 5000 };
    const result = await solveScenario(api, scenario, request);
    assert.equal(result.status, enumerate(request) ? 'feasible' : 'unsat', JSON.stringify({ request, result }));
    checked++;
  }
  assert.equal(checked, 32);
  for (const selections of [{ fixedLockerIds: [] }, { fixedLockerIds: ['l0'] }, { fixedDepotIds: ['d0'] }, { fixedLockerIds: ['l1'], fixedDepotIds: ['d0'] }]) {
    const request = { ...scenario.defaults, lockerCapacity: 4, ...selections, timeoutMs: 5000 };
    assert.equal((await solveScenario(api, scenario, request)).status, enumerate(request) ? 'feasible' : 'unsat');
  }
});
