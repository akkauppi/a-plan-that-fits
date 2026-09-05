import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { graphIndex, shortestPaths, routeEdges } from '../src/core/graph.ts';
import { validateScenario } from '../src/core/validate.ts';
import { replayCandidateSelection } from './candidate-selection.mjs';

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const inputBytes = gunzipSync(await readFile('data/inputs/geography.json.gz'));
const input = JSON.parse(inputBytes);
const recipe = JSON.parse(await readFile('data/recipe.json', 'utf8'));
const manifest = JSON.parse(await readFile('data/sources/manifest.json', 'utf8'));
if (sha256(inputBytes) !== manifest.inputSha256) throw new Error('Frozen input hash mismatch. Do not silently rewrite the manifest.');
for (const artifact of manifest.artifacts) {
  if (sha256(await readFile(artifact.path)) !== artifact.sha256) throw new Error(`Source hash mismatch: ${artifact.path}`);
}
if (recipe.walkingLimitMm !== 500000) throw new Error('The teaching rule is exactly 500 m.');
const graph = graphIndex(input.network);
const sites = (items, kind) => items.map(([id, nodeId]) => {
  const node = graph.nodes.get(nodeId);
  if (!node) throw new Error(`Missing ${kind} node ${nodeId}`);
  return { ...node, id, nodeId, label: `${kind} ${id}` };
});
const candidateReplay = replayCandidateSelection(input.network, input.cells, recipe.candidateSelection);
if (JSON.stringify(candidateReplay.steps.map(step => step.nodeId)) !== JSON.stringify(recipe.lockers.map(([, nodeId]) => nodeId))) {
  throw new Error('Locker recipe does not match its candidate-selection rule. Review the derivation; do not hand-edit generated data.');
}
const lockers = sites(recipe.lockers, 'Locker');
const depots = sites(recipe.depots, 'Depot');
const walking = input.cells.flatMap(cell => {
  const paths = shortestPaths(graph, cell.nodeId, 500000 - cell.connectorMm);
  return lockers.flatMap(locker => {
    const route = paths.distances.get(locker.nodeId);
    return route === undefined ? [] : [{ cellId: cell.id, lockerId: locker.id, distanceMm: cell.connectorMm + route, edgeIds: routeEdges(paths, cell.nodeId, locker.nodeId) }];
  });
});
const flights = lockers.flatMap(locker => depots.map(depot => ({
  lockerId: locker.id, depotId: depot.id,
  returnDistanceMm: Math.round(2 * Math.hypot(locker.xyMm[0] - depot.xyMm[0], locker.xyMm[1] - depot.xyMm[1])),
})));
// A reproducible walking-only starter, not a cached Z3/network result.
const choices = cell => walking.filter(p => p.cellId === cell.id && recipe.starterLockerIds.includes(p.lockerId));
const ordered = [...input.cells].sort((a, b) => choices(a).length - choices(b).length || b.parcels - a.parcels || a.id.localeCompare(b.id, 'en'));
const loads = Object.fromEntries(recipe.starterLockerIds.map(id => [id, 0]));
const assignments = [];
function assign(index) {
  if (index === ordered.length) return recipe.starterLockerIds.every(id => loads[id] > 0);
  const cell = ordered[index];
  for (const pair of choices(cell).sort((a, b) => a.distanceMm - b.distanceMm || a.lockerId.localeCompare(b.lockerId, 'en'))) {
    if (loads[pair.lockerId] + cell.parcels > recipe.defaults.lockerCapacity) continue;
    loads[pair.lockerId] += cell.parcels;
    assignments.push({ cellId: cell.id, lockerId: pair.lockerId });
    if (assign(index + 1)) return true;
    assignments.pop(); loads[pair.lockerId] -= cell.parcels;
  }
  return false;
}
if (!assign(0)) throw new Error('Starter has no walking/capacity assignment.');
const content = {
  schemaVersion: 1, id: recipe.id, walkingLimitMm: recipe.walkingLimitMm,
  provenance: { inputSha256: sha256(inputBytes), archiveCommit: input.archiveCommit, networkSnapshot: input.networkSnapshot },
  center: recipe.center, network: input.network, cells: input.cells, lockers, depots, walking, flights,
  defaults: recipe.defaults, starterLockerIds: recipe.starterLockerIds,
  starterAssignments: assignments.sort((a, b) => a.cellId.localeCompare(b.cellId, 'en')),
};
const scenario = { ...content, snapshotId: `parcel-${sha256(JSON.stringify(content)).slice(0, 24)}` };
validateScenario(scenario);
const output = JSON.stringify(scenario) + '\n';
const path = 'public/data/scenario.json';
if (process.argv.includes('--check')) {
  if (await readFile(path, 'utf8') !== output) throw new Error('Scenario is stale. Run npm run data:build, review the diff, then run all tests.');
  console.log(`Validated frozen sources, complete walking matrix and deterministic snapshot ${scenario.snapshotId}.`);
} else {
  await mkdir('public/data', { recursive: true });
  await writeFile(path, output);
  console.log(`Built ${scenario.snapshotId}: ${scenario.cells.length} cells, ${walking.length} eligible walks, ${flights.length} return-flight distances.`);
}
