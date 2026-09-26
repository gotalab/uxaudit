import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { parse } from 'yaml';
import { Config, Verdict } from '../src/schema.ts';
import { loadTriage, mergeTriage } from '../src/store.ts';
import { envRefs, resolveEnv } from '../src/env.ts';

const CLI = new URL('../dist/uxaudit.mjs', import.meta.url).pathname;
// Smallest valid JPEG (1x1).
const JPEG = Buffer.from(
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
  'base64',
);

test('the demo journeys parse', () => {
  const raw = readFileSync(new URL('../examples/demo-app/.uxaudit/journeys.yaml', import.meta.url), 'utf8');
  const config = Config.parse(parse(raw));
  assert.equal(config.journeys.length, 5);
  assert.deepEqual(envRefs(config.auth), ['DEMO_PASSWORD']);
  assert.equal(config.journeys[0]!.focus, 'first-value');
});

test('unknown step actions are rejected', () => {
  const res = Config.safeParse({
    version: 1,
    app: { url: 'http://localhost:3000' },
    journeys: [{ id: 'a', title: 'A', goal: 'g', steps: [{ tripleClick: 'x' }] }],
  });
  assert.equal(res.success, false);
});

test('verdict rules: pass cannot carry major findings, fail needs one', () => {
  const finding = { key: 'no-feedback', title: 't', severity: 'major', stage: 'recover', steps: [1], observation: 'o', suggestion: 's' };
  assert.equal(Verdict.safeParse({ journey: 'a', verdict: 'pass', summary: 's', findings: [finding] }).success, false);
  assert.equal(Verdict.safeParse({ journey: 'a', verdict: 'fail', summary: 's', findings: [] }).success, false);
  assert.equal(Verdict.safeParse({ journey: 'a', verdict: 'fail', summary: 's', findings: [finding] }).success, true);
});

test('triage merge keeps the newer decision', () => {
  const home = mkdtempSync(join(tmpdir(), 'uxaudit-'));
  mergeTriage(home, { 'a:x': { status: 'fix', note: '', updatedAt: '2026-01-02T00:00:00Z' } });
  const r = mergeTriage(home, {
    'a:x': { status: 'accepted', note: '', updatedAt: '2026-01-01T00:00:00Z' },
    'a:y': { status: 'false-positive', note: 'by design', updatedAt: '2026-01-01T00:00:00Z' },
  });
  assert.deepEqual(r, { added: 1, updated: 0 });
  assert.equal(loadTriage(home).items['a:x']!.status, 'fix');
});

test('report escapes judge-written text and fix list picks the right findings', () => {
  const home = mkdtempSync(join(tmpdir(), 'uxaudit-'));
  const run = join(home, 'runs', '2026-01-01T00-00-00');
  mkdirSync(join(run, 'j1'), { recursive: true });
  mkdirSync(join(run, 'verdicts'));
  writeFileSync(join(run, 'j1', '01.jpg'), JPEG);
  const step = { index: 1, label: 'open /', status: 'ok', url: 'http://localhost:1/', atMs: 0, durationMs: 5, frames: [], shot: '01.jpg', signals: { consoleErrors: [], httpErrors: [], slow: false, horizontalOverflow: false } };
  writeFileSync(join(run, 'run.json'), JSON.stringify({
    version: 1, runId: '2026-01-01T00-00-00', createdAt: '2026-01-01T00:00:00Z',
    app: { url: 'http://localhost:1/', lang: 'en' },
    journeys: [{ id: 'j1', title: 'J1', focus: 'other', goal: 'g', expect: [], capture: { id: 'j1', status: 'completed', viewport: 'desktop', steps: [step] } }],
  }));
  const f = (key: string, severity: string, title: string) => ({ key, title, severity, stage: 'act', steps: [1], observation: 'o', suggestion: 's' });
  writeFileSync(join(run, 'verdicts', 'j1.json'), JSON.stringify({
    journey: 'j1', verdict: 'fail', summary: 's',
    findings: [f('evil-title', 'major', '</script><script>alert(1)</script>'), f('small-thing', 'minor', 'Minor issue'), f('ignored-one', 'major', 'Accepted issue')],
  }));
  mergeTriage(home, { 'j1:ignored-one': { status: 'accepted', note: '', updatedAt: '2026-01-01T00:00:00Z' } });

  execFileSync('node', [CLI, 'report', run, '--home', home]);
  const html = readFileSync(join(run, 'report.html'), 'utf8');
  assert.equal(html.includes('</script><script>alert(1)'), false);
  assert.equal((html.match(/<\/script>/g) ?? []).length, 2);

  const fixes = execFileSync('node', [CLI, 'fixes', run, '--home', home], { encoding: 'utf8' });
  assert.match(fixes, /alert\(1\)/); // open major → listed
  assert.doesNotMatch(fixes, /Minor issue/); // open minor → skipped
  assert.doesNotMatch(fixes, /Accepted issue/); // accepted → skipped
});

test('journeys must name an existing auth entry', () => {
  const res = Config.safeParse({
    version: 1,
    app: { url: 'http://localhost:3000' },
    journeys: [{ id: 'a', title: 'A', goal: 'g', auth: 'admin', steps: [{ goto: '/' }] }],
  });
  assert.equal(res.success, false);
});

test('env placeholders resolve at use and fail loudly when missing', () => {
  assert.equal(resolveEnv('pw=${env:PW}', { PW: 's3cret' }), 'pw=s3cret');
  assert.throws(() => resolveEnv('${env:NOPE}', {}), /NOPE\} is not set/);
});

test('a recorded auth entry needs a check', () => {
  const base = { version: 1, app: { url: 'http://localhost:3000' }, journeys: [{ id: 'a', title: 'A', goal: 'g', auth: 'g', steps: [{ goto: '/' }] }] };
  assert.equal(Config.safeParse({ ...base, auth: { g: { recorded: true } } }).success, false);
  assert.equal(Config.safeParse({ ...base, auth: { g: { recorded: true, check: [{ see: 'Hi' }] } } }).success, true);
});
