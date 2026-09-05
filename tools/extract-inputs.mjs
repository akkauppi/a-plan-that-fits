// One-time, explicit migration boundary. Routine builds use data/inputs instead.
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import proj4 from 'proj4';

const archive = '7f2bdaf';
const gitArgs = existsSync('.git-local/HEAD') ? ['--git-dir=.git-local', '--work-tree=.'] : [];
const readArchive = path => execFileSync('git', [...gitArgs, 'show', `${archive}:${path}`], { maxBuffer: 100 * 1024 * 1024 });
const readJson = path => JSON.parse(readArchive(path));
const sha256 = value => createHash('sha256').update(value).digest('hex');
const networkPath = 'data/derived/espoo-otaniemi-coastal-base-v1-base-network/snapshots/base-c8dcbcfaca2b2c9498420681/base-network.json';
const base = readJson(networkPath);
const old = readJson('data/derived/service-coverage-otaniemi-tapiola-v1/solver.json');
const hsyPath = 'data/source/service-coverage/otaniemi-tapiola-v1/hsy/population-grid-2025.geojson';
const hsy = readJson(hsyPath);
const hsyCells = new Map(hsy.features.map(f => [`hsy-grid-${f.properties.index}`, f]));
const edges = base.edges.filter(edge => edge.permissions.walking).map(edge => ({
  id: edge.id, from: edge.from, to: edge.to,
  lengthMm: Math.round(edge.length_m * 1000), coordinates: edge.geometry,
}));
const used = new Set(edges.flatMap(edge => [edge.from, edge.to]));
const nodes = base.nodes.filter(node => used.has(node.id)).map(node => ({
  id: node.id, point: [node.longitude, node.latitude], xyMm: [Math.round(node.x * 1000), Math.round(node.y * 1000)],
}));
const byId = new Map(nodes.map(node => [node.id, node]));
const crs = '+proj=utm +zone=35 +ellps=GRS80 +units=m +no_defs';
const cells = old.demand.map(cell => {
  const source = hsyCells.get(cell.id);
  if (!source || source.properties.asukkaita !== cell.population) throw new Error(`Population source mismatch: ${cell.id}`);
  const xyMm = proj4('EPSG:4326', crs, cell.point).map(v => Math.round(v * 1000));
  const snap = byId.get(cell.node_id);
  if (!snap) throw new Error(`Missing walking snap: ${cell.id}`);
  return {
    id: cell.id, population: cell.population, parcels: Math.ceil(cell.population / 10),
    nodeId: cell.node_id, point: cell.point, xyMm,
    connectorMm: Math.round(Math.hypot(xyMm[0] - snap.xyMm[0], xyMm[1] - snap.xyMm[1])),
    polygon: source.geometry.coordinates,
  };
});
const input = JSON.stringify({
  schemaVersion: 1, archiveCommit: archive, networkSnapshot: base.snapshot_id,
  analysisCrs: 'EPSG:3067', network: { nodes, edges }, cells,
}) + '\n';
await mkdir('data/inputs', { recursive: true });
await mkdir('data/sources', { recursive: true });
await writeFile('data/inputs/geography.json.gz', gzipSync(input, { level: 9 }));
const archives = [
  ['osm-overpass.json.gz', 'data/source/scenario-builder/espoo-otaniemi-coastal-base-v1/osm/espoo-otaniemi-coastal-base-v1.osm-overpass.88d79a3217333d77.json.gz'],
  ['population-grid-2025.geojson', hsyPath],
];
const artifacts = [];
for (const [name, path] of archives) {
  const bytes = readArchive(path);
  await writeFile(`data/sources/${name}`, bytes);
  artifacts.push({ path: `data/sources/${name}`, sha256: sha256(bytes), archivePath: path });
}
const oldManifest = readJson('data/source/service-coverage/otaniemi-tapiola-v1/source-manifest.json');
const osmManifest = readJson('data/source/scenario-builder/espoo-otaniemi-coastal-base-v1/osm/espoo-otaniemi-coastal-base-v1.osm-overpass.archive.json');
await writeFile('data/sources/manifest.json', JSON.stringify({
  archiveCommit: archive, inputSha256: sha256(input), normalizationSource: networkPath,
  normalization: 'Frozen walking-permitted directed graph from archive; integer millimetres. Original 33 published cells retained. Connectors reprojected from representative points using EPSG:3067. Not a new raw OSM parser.',
  artifacts,
  osm: { attribution: '© OpenStreetMap contributors', licence: 'ODbL 1.0', licenceUrl: 'https://opendatacommons.org/licenses/odbl/1-0/', sourceUrl: 'https://www.openstreetmap.org/copyright', sourceTimestamp: osmManifest.source_timestamp, rawSha256: base.source.raw_sha256, query: osmManifest.query },
  population: { ...oldManifest.datasets[0], acquiredAt: oldManifest.acquired_at, edition: 2025, query: oldManifest.artifacts[0].query, dataUpdateTimestamp: oldManifest.artifacts[0].data_update_timestamp },
}, null, 2) + '\n');
console.log(`Imported ${nodes.length} walking nodes, ${edges.length} directed edges and ${cells.length} cells from ${archive}.`);
