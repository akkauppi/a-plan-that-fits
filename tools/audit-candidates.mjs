import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { replayCandidateSelection } from './candidate-selection.mjs';

const input = JSON.parse(gunzipSync(await readFile('data/inputs/geography.json.gz')));
const recipe = JSON.parse(await readFile('data/recipe.json', 'utf8'));
const audit = replayCandidateSelection(input.network, input.cells, recipe.candidateSelection);
if (JSON.stringify(audit.steps.map(step => step.nodeId)) !== JSON.stringify(recipe.lockers.map(([, nodeId]) => nodeId))) {
  throw new Error('Selection replay differs from the frozen recipe. Investigate; do not overwrite the candidate IDs.');
}
console.log(`Replayed ${audit.consideredNodes} reachable walking nodes → ${audit.steps.length} hypothetical locker candidates. Exactly matches data/recipe.json; every cell has at least ${audit.minimumChoicesPerCell} choices within 500 m.`);
console.table(audit.steps.map((step, i) => ({
  candidate: recipe.lockers[i][0], node: step.nodeId,
  cellsGainingAnOption: step.cellsGainingAnOption,
  reachableCells: step.reachableCellIds.length,
  worstUsefulWalkM: step.worstUsefulWalkMm / 1000,
})));
console.log('This shortlist ignores capacities, drone supply and buildability. Z3 later chooses which candidates to open under the joint rules. No files changed.');
