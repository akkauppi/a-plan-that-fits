import { graphIndex, shortestPaths } from '../src/core/graph.ts';

// Explain/replay the frozen teaching shortlist, NOT a production siting method.
// This chooses possible sites from geography alone. It does not call Z3, solve
// capacity/supply, or replace the canonical candidate IDs in data/recipe.json.
export function replayCandidateSelection(network, cells) {
  const graph = graphIndex(network);
  const optionsByNode = new Map();
  for (const cell of cells) {
    const paths = shortestPaths(graph, cell.nodeId, 500000 - cell.connectorMm);
    for (const [nodeId, distance] of paths.distances) {
      const options = optionsByNode.get(nodeId) ?? [];
      options.push({ cellId: cell.id, distanceMm: cell.connectorMm + distance });
      optionsByNode.set(nodeId, options);
    }
  }
  const choicesPerCell = new Map(cells.map(cell => [cell.id, 0]));
  const selected = [];
  const steps = [];
  while ([...choicesPerCell.values()].some(count => count < 2)) {
    let best;
    for (const [nodeId, options] of optionsByNode) {
      const node = graph.nodes.get(nodeId);
      const tooClose = selected.some(site => Math.hypot(site.xyMm[0] - node.xyMm[0], site.xyMm[1] - node.xyMm[1]) < 80000);
      if (tooClose) continue;
      const useful = options.filter(option => choicesPerCell.get(option.cellId) < 2);
      if (!useful.length) continue;
      const candidate = { node, options, gain: useful.length, worstUsefulWalkMm: Math.max(...useful.map(option => option.distanceMm)) };
      // Most cells helped first; then shortest worst useful walk; then stable ID.
      if (!best || candidate.gain > best.gain || candidate.gain === best.gain && (
        candidate.worstUsefulWalkMm < best.worstUsefulWalkMm ||
        candidate.worstUsefulWalkMm === best.worstUsefulWalkMm && node.id < best.node.id
      )) best = candidate;
    }
    if (!best) throw new Error('Cannot give each cell two choices with the 80 m candidate-spacing rule.');
    selected.push(best.node);
    for (const option of best.options) choicesPerCell.set(option.cellId, choicesPerCell.get(option.cellId) + 1);
    steps.push({
      nodeId: best.node.id,
      cellsGainingAnOption: best.gain,
      reachableCellIds: best.options.map(option => option.cellId),
      worstUsefulWalkMm: best.worstUsefulWalkMm,
    });
  }
  return { consideredNodes: optionsByNode.size, steps, minimumChoicesPerCell: Math.min(...choicesPerCell.values()) };
}
