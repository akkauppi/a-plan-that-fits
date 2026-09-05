import { mkdir, copyFile, writeFile, readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('../', import.meta.url));
const runtime = new URL('../public/runtime/', import.meta.url);
await mkdir(new URL('z3-5.2.0/', runtime), { recursive: true });
for (const file of ['z3-built.js', 'z3-built.wasm']) {
  await copyFile(new URL(`../node_modules/z3-solver/build/${file}`, import.meta.url), new URL(`z3-5.2.0/${file}`, runtime));
}
await copyFile(new URL('../node_modules/coi-serviceworker/coi-serviceworker.js', import.meta.url), new URL('../public/coi-serviceworker.js', import.meta.url));
// Preserve licences of runtime dependencies in the distributable site.
const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));
const notices = ['Third-party software notices. Geographic data attribution is in data/README.md and in the tour.'];
for (const [path, info] of Object.entries(lock.packages)) {
  if (!path || info.dev) continue;
  const directory = new URL(`../${path}/`, import.meta.url);
  const entries = await readdir(directory);
  const licences = entries.filter(name => /^(licen[cs]e|copying|notice)([.-]|$)/i.test(name));
  notices.push(`\n${path} · ${info.version} · ${info.license ?? 'see package licence'}\n`);
  for (const file of licences) {
    try { notices.push(await readFile(new URL(file, directory), 'utf8')); }
    catch (error) { if (error.code !== 'EISDIR') throw error; }
  }
}
await writeFile(new URL('../public/third-party-notices.txt', import.meta.url), notices.join('\n'));
await build({
  entryPoints: [new URL('../src/solver/worker.ts', import.meta.url).pathname],
  outfile: new URL('solver-bundle.js', runtime).pathname,
  absWorkingDir: root,
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  define: { global: 'globalThis' },
  sourcemap: true,
});
await build({
  entryPoints: [new URL('../src/exhaustive/worker.ts', import.meta.url).pathname],
  outfile: new URL('exhaustive-worker.js', runtime).pathname,
  absWorkingDir: root,
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  sourcemap: true,
});
// Emscripten must remain a standalone classic script; bundling it breaks its
// own pthread workers. The wrapper's global alias is confined to this worker.
await writeFile(new URL('solver-worker.js', runtime),
  'globalThis.global = globalThis;\nimportScripts("./z3-5.2.0/z3-built.js", "./solver-bundle.js");\n');
console.log('Prepared browser Z3 5.2.0, exhaustive JavaScript search and project-scoped isolation worker.');
