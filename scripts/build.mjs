// Two-step build: the report's browser script is bundled to a string first,
// then inlined into the single-file CLI bundle.
import { build } from 'esbuild';

await build({
  entryPoints: ['src/report/client.ts'],
  bundle: true,
  format: 'iife',
  target: 'es2020',
  minify: true,
  outfile: 'src/report/client.gen.txt',
});

await build({
  entryPoints: ['src/cli.ts'],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  external: ['playwright'],
  loader: { '.css': 'text', '.txt': 'text' },
  outfile: 'dist/uxaudit.mjs',
  // yaml is CommonJS and requires node builtins; give the ESM bundle a require.
  banner: {
    js: "#!/usr/bin/env node\nimport { createRequire as __createRequire } from 'node:module';\nconst require = __createRequire(import.meta.url);",
  },
});
