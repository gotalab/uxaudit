import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

// Secrets never live in journeys.yaml: values reference `${env:NAME}` and are
// resolved only when the browser needs them. Labels, briefs and reports keep
// the placeholder, so no secret reaches a screenshot caption or the judge.
const REF = /\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}/g;

/** process.env, falling back to .uxaudit/.env (KEY=VALUE lines, git-ignored). */
export function loadEnv(home: string): Record<string, string> {
  const env: Record<string, string> = {};
  const file = join(home, '.env');
  if (existsSync(file)) {
    for (const line of readFileSync(file, 'utf8').split('\n')) {
      const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
      if (m) env[m[1]!] = m[2]!.replace(/^(['"])(.*)\1$/, '$2');
    }
  }
  for (const [k, v] of Object.entries(process.env)) if (v !== undefined) env[k] = v;
  return env;
}

export function resolveEnv(text: string, env: Record<string, string>): string {
  return text.replace(REF, (_, name: string) => {
    const v = env[name];
    if (v === undefined) throw new Error(`\${env:${name}} is not set (export it or add it to .uxaudit/.env)`);
    return v;
  });
}

/** Every ${env:NAME} referenced anywhere in a value (for an up-front check). */
export function envRefs(value: unknown): string[] {
  return [...JSON.stringify(value).matchAll(REF)].map((m) => m[1]!);
}
