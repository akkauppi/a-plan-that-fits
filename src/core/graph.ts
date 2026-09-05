import type { NetworkEdge, NetworkNode } from './types.ts'

// Integer millimetres keep build-time and browser eligibility identical.
export function graphIndex(network: { nodes: NetworkNode[]; edges: NetworkEdge[] }) {
  const nodes = new Map(network.nodes.map(node => [node.id, node]))
  const edges = new Map(network.edges.map(edge => [edge.id, edge]))
  if (nodes.size !== network.nodes.length || edges.size !== network.edges.length) throw new Error('Duplicate graph IDs')
  const outgoing = new Map<string, NetworkEdge[]>()
  for (const edge of network.edges) {
    if (!nodes.has(edge.from) || !nodes.has(edge.to) || !Number.isSafeInteger(edge.lengthMm) || edge.lengthMm <= 0) throw new Error(`Invalid graph edge ${edge.id}`)
    const list = outgoing.get(edge.from) ?? []
    list.push(edge)
    outgoing.set(edge.from, list)
  }
  for (const list of outgoing.values()) list.sort((a, b) => a.id.localeCompare(b.id, 'en'))
  return { nodes, edges, outgoing }
}
export type Graph = ReturnType<typeof graphIndex>

export function shortestPaths(graph: Graph, start: string, cutoff = Infinity) {
  if (!graph.nodes.has(start)) throw new Error(`Missing origin node ${start}`)
  const distances = new Map<string, number>([[start, 0]])
  const previous = new Map<string, NetworkEdge>()
  const heap: [number, string][] = []
  const push = (item: [number, string]) => {
    let i = heap.length
    heap.push(item)
    while (i > 0) {
      const p = (i - 1) >> 1
      if (heap[p][0] <= item[0]) break
      heap[i] = heap[p]; i = p
    }
    heap[i] = item
  }
  push([0, start])
  while (heap.length) {
    const [distance, id] = heap[0]
    const tail = heap.pop()!
    if (heap.length) {
      let i = 0
      while (i * 2 + 1 < heap.length) {
        let child = i * 2 + 1
        if (child + 1 < heap.length && heap[child + 1][0] < heap[child][0]) child++
        if (heap[child][0] >= tail[0]) break
        heap[i] = heap[child]; i = child
      }
      heap[i] = tail
    }
    if (distances.get(id) !== distance) continue
    for (const edge of graph.outgoing.get(id) ?? []) {
      const next = distance + edge.lengthMm
      if (next <= cutoff && next < (distances.get(edge.to) ?? Infinity)) {
        distances.set(edge.to, next); previous.set(edge.to, edge); push([next, edge.to])
      }
    }
  }
  return { distances, previous }
}

export function routeEdges(paths: ReturnType<typeof shortestPaths>, start: string, end: string): string[] {
  const edges: string[] = []
  let current = end
  while (current !== start) {
    const edge = paths.previous.get(current)
    if (!edge || edges.length > paths.previous.size) throw new Error(`Missing route to ${end}`)
    edges.push(edge.id); current = edge.from
  }
  return edges.reverse()
}
