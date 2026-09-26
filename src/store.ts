import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { parse } from 'yaml';
import { Config, Triage, TriageItem, Verdict, type RunManifest } from './schema.ts';

export const HOME = '.uxaudit';

export function loadConfig(path: string): Config {
  if (!existsSync(path)) throw new Error(`${path} not found. Run \`uxaudit init\` first.`);
  const res = Config.safeParse(parse(readFileSync(path, 'utf8')));
  if (!res.success) throw new Error(`${path} is invalid:\n${formatIssues(res.error.issues)}`);
  return res.data;
}

export function formatIssues(issues: { path: (string | number)[]; message: string }[]): string {
  return issues.map((i) => `  - ${i.path.join('.') || '(root)'}: ${i.message}`).join('\n');
}

export function readManifest(runDir: string): RunManifest {
  const p = join(runDir, 'run.json');
  if (!existsSync(p)) throw new Error(`${runDir} is not a uxaudit run (no run.json)`);
  return JSON.parse(readFileSync(p, 'utf8'));
}

export function latestRun(home: string): string {
  const runs = join(home, 'runs');
  const ids = existsSync(runs) ? readdirSync(runs).filter((d) => existsSync(join(runs, d, 'run.json'))).sort() : [];
  if (!ids.length) throw new Error(`no runs under ${runs}. Run \`uxaudit run\` first.`);
  return join(runs, ids.at(-1)!);
}

/** Finding keys the previous run's judge used for this journey, so the next
 *  judge can reuse them and triage decisions keep applying. */
export function previousKeys(runDir: string, journeyId: string): { key: string; title: string }[] {
  const runs = join(runDir, '..');
  const ids = readdirSync(runs).filter((d) => existsSync(join(runs, d, 'run.json'))).sort();
  const at = ids.indexOf(basename(runDir));
  for (const id of ids.slice(0, at === -1 ? ids.length : at).reverse()) {
    const p = join(runs, id, 'verdicts', `${journeyId}.json`);
    if (!existsSync(p)) continue;
    const v = Verdict.safeParse(JSON.parse(readFileSync(p, 'utf8')));
    if (v.success) return v.data.findings.map((f) => ({ key: f.key, title: f.title }));
  }
  return [];
}

export interface VerdictResult {
  verdicts: Record<string, Verdict>;
  problems: string[];
}

export function loadVerdicts(runDir: string, run: RunManifest): VerdictResult {
  const verdicts: Record<string, Verdict> = {};
  const problems: string[] = [];
  for (const j of run.journeys) {
    const p = join(runDir, 'verdicts', `${j.id}.json`);
    if (!existsSync(p)) {
      problems.push(`${j.id}: missing verdicts/${j.id}.json`);
      continue;
    }
    let raw: unknown;
    try {
      raw = JSON.parse(readFileSync(p, 'utf8'));
    } catch (e) {
      problems.push(`${j.id}: not valid JSON (${(e as Error).message})`);
      continue;
    }
    const res = Verdict.safeParse(raw);
    if (!res.success) {
      problems.push(`${j.id}:\n${formatIssues(res.error.issues)}`);
      continue;
    }
    const max = j.capture.steps.length;
    const bad = res.data.findings.flatMap((f) => f.steps.filter((s) => s > max).map((s) => `${f.key} cites step ${s}`));
    if (bad.length) problems.push(`${j.id}: steps out of range (journey has ${max}): ${bad.join(', ')}`);
    else verdicts[j.id] = res.data;
  }
  return { verdicts, problems };
}

export function loadTriage(home: string): Triage {
  const p = join(home, 'triage.json');
  if (!existsSync(p)) return { version: 1, items: {} };
  return Triage.parse(JSON.parse(readFileSync(p, 'utf8')));
}

/** Merge incoming triage items; the newer `updatedAt` wins per finding. */
export function mergeTriage(home: string, incoming: Record<string, unknown>): { added: number; updated: number } {
  const current = loadTriage(home);
  let added = 0;
  let updated = 0;
  for (const [id, raw] of Object.entries(incoming)) {
    const item = TriageItem.parse(raw);
    const prev = current.items[id];
    if (!prev) added++;
    else if (prev.updatedAt < item.updatedAt) updated++;
    else continue;
    current.items[id] = item;
  }
  writeFileSync(join(home, 'triage.json'), JSON.stringify(current, null, 2) + '\n');
  return { added, updated };
}
