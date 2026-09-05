import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validateScenario } from '../src/core/validate.ts';
import { graphIndex, shortestPaths } from '../src/core/graph.ts';
import { replayCandidateSelection } from '../tools/candidate-selection.mjs';
import { proposeExpandedScenario } from '../tools/expanded-scenario-proposal.mjs';

const scenario = JSON.parse(await readFile(new URL('../public/data/scenario.json', import.meta.url)));
test('the documented shortlist procedure reproduces all 24 candidates in order', () => {
  const audit = replayCandidateSelection(scenario.network, scenario.cells, { minimumChoices: 3, minimumSpacingMm: 80000 });
  assert.equal(audit.consideredNodes, 13045);
  assert.equal(audit.minimumChoicesPerCell, 3);
  assert.equal(audit.requestedMinimumChoices, 3);
  assert.equal(audit.minimumSpacingMm, 80000);
  assert.deepEqual(audit.steps.map(step => step.nodeId), scenario.lockers.map(locker => locker.nodeId));
  for (let i = 0; i < scenario.lockers.length; i++) for (const other of scenario.lockers.slice(i + 1)) {
    const site = scenario.lockers[i];
    assert.ok(Math.hypot(site.xyMm[0] - other.xyMm[0], site.xyMm[1] - other.xyMm[1]) >= 80000);
  }
});
test('the expanded proposal is reproducible and honest about outage resilience', () => {
  const proposal = proposeExpandedScenario(scenario);
  assert.equal(proposal.status, 'implemented-geography-audit');
  assert.equal(proposal.lockers.length, 24);
  assert.equal(proposal.depots.length, 6);
  assert.equal(proposal.candidateMethod.minimumChoicesPerCell, 3);
  assert.equal(proposal.candidateMethod.minimumSpacingMm, 80000);
  assert.equal(proposal.rawExactSiteSelections, '29418840');
  assert.deepEqual(proposal.depots.slice(-2).map(depot => depot.nodeId), ['osm-node-8209555651', 'osm-node-12728836257']);
  assert.equal(proposal.resilience.threeSelectedDepots.combinationsWithFullLocalCoverage, 0);
  assert.equal(proposal.resilience.threeSelectedDepots.bestRobustCoverageCellCount, 27);
  assert.equal(proposal.resilience.fourSelectedDepots.combinationsWithFullLocalCoverage, 3);
  assert.ok(proposal.resilience.fourSelectedDepots.witnesses.every(item => item.coverWithinLockerBudget.length <= 10));
});
test('expanded frozen geography has the intended scale and a complete 500 m walking matrix', () => {
  assert.equal(scenario.walkingLimitMm, 500000);
  assert.equal(scenario.cells.length, 33);
  assert.equal(scenario.cells.reduce((n, c) => n + c.population, 0), 8554);
  assert.equal(scenario.cells.reduce((n, c) => n + c.parcels, 0), 871);
  assert.equal(scenario.lockers.length, 24);
  assert.equal(scenario.depots.length, 6);
  assert.equal(scenario.walking.length, 120);
  assert.equal(scenario.flights.length, 144);
  assert.equal(scenario.defaults.maxLockers, 10);
  assert.equal(scenario.defaults.maxDepots, 4);
  assert.equal(scenario.defaults.depotOutageTolerance, 1);
  assert.doesNotThrow(() => validateScenario(scenario));
});
test('omitting even one eligible pair cannot produce a false UNSAT claim', () => {
  const changed = structuredClone(scenario);
  changed.walking.pop();
  assert.throws(() => validateScenario(changed), /Missing or incorrect eligible/);
});
test('route, connector, flight and ID corruption is rejected before solving', () => {
  for (const corrupt of [
    s => { s.walking[0].distanceMm--; },
    s => { s.walking[0].edgeIds.reverse(); },
    s => { s.cells[0].connectorMm = 0; },
    s => { s.flights[0].returnDistanceMm /= 2; },
    s => { s.network.edges.push(s.network.edges[0]); },
    s => { s.walkingLimitMm = 600000; },
  ]) {
    const changed = structuredClone(scenario); corrupt(changed);
    assert.throws(() => validateScenario(changed));
  }
});
test('directed graph includes exactly 500 m but excludes 500 m plus 1 mm', () => {
  const nodes = ['a', 'b', 'c'].map(id => ({ id, point: [0, 0], xyMm: [0, 0] }));
  const graph = graphIndex({ nodes, edges: [
    { id: 'ab', from: 'a', to: 'b', lengthMm: 500000, coordinates: [] },
    { id: 'bc', from: 'b', to: 'c', lengthMm: 1, coordinates: [] },
  ] });
  assert.equal(shortestPaths(graph, 'a', 500000).distances.get('b'), 500000);
  assert.equal(shortestPaths(graph, 'a', 500000).distances.has('c'), false);
  assert.equal(shortestPaths(graph, 'b', 500000).distances.has('a'), false);
});
