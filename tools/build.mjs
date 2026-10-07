import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
await build({
  entryPoints: [path.join(root, 'tools/compile-graph.ts')],
  outfile: path.join(root, 'src/compile-graph.mjs'),
  bundle: true, platform: 'node', format: 'esm', target: 'node20',
  alias: {
    'src/core/task/AsyncScheduler': path.join(root, 'tools/headless-scheduler.ts'),
    'src': path.join(root, 'vendor/graphdlc/ts/src'),
  },
  banner: { js: '// Bundled GraphDLC MIT cycle optimizer; see ../vendor/graphdlc/LICENSE.' },
});
