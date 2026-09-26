import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { findingId, type RunManifest, type Triage, type Verdict } from './schema.ts';
import REPORT_CSS from './report/style.css';
import REPORT_JS from './report/client.gen.txt';

export interface ReportFinding {
  id: string;
  journey: string;
  key: string;
  title: string;
  severity: 'blocker' | 'major' | 'minor';
  stage: string;
  steps: number[];
  observation: string;
  suggestion: string;
}

export interface ReportData {
  runId: string;
  createdAt: string;
  lang: 'en' | 'ja';
  app: RunManifest['app'];
  journeys: {
    id: string;
    title: string;
    focus: string;
    goal: string;
    expect: string[];
    status: string;
    viewport: string;
    auth: string | null;
    /** Relative to the report file; published next to it as an artifact file. */
    video: string | null;
    verdict: Pick<Verdict, 'verdict' | 'summary'> | null;
    steps: {
      index: number;
      label: string;
      status: string;
      error?: string;
      url: string;
      atMs: number;
      durationMs: number;
      frames: { img: string; afterMs: number }[];
      img: string;
      signals: RunManifest['journeys'][number]['capture']['steps'][number]['signals'];
    }[];
  }[];
  findings: ReportFinding[];
  triage: Triage['items'];
}

const jpeg = (path: string) => `data:image/jpeg;base64,${readFileSync(path).toString('base64')}`;

/** Files an artifact publish must carry next to the page (published path → local path). */
export function artifactFiles(runDir: string, data: ReportData): Record<string, string> {
  return Object.fromEntries(data.journeys.filter((j) => j.video).map((j) => [j.video!, join(runDir, j.video!)]));
}

const SEVERITY_ORDER = { blocker: 0, major: 1, minor: 2 } as const;

export function buildReportData(runDir: string, run: RunManifest, verdicts: Record<string, Verdict>, triage: Triage): ReportData {
  const findings: ReportFinding[] = [];
  const journeys = run.journeys.map((j) => {
    const v = verdicts[j.id] ?? null;
    for (const f of v?.findings ?? []) findings.push({ id: findingId(j.id, f.key), journey: j.id, ...f });
    return {
      id: j.id,
      title: j.title,
      focus: j.focus,
      goal: j.goal,
      expect: j.expect,
      status: j.capture.status,
      viewport: j.capture.viewport,
      auth: j.auth ?? null,
      video: j.capture.video && existsSync(join(runDir, j.capture.video)) ? j.capture.video : null,
      verdict: v && { verdict: v.verdict, summary: v.summary },
      steps: j.capture.steps.map((s) => ({
        index: s.index,
        label: s.label,
        status: s.status,
        error: s.error,
        url: s.url,
        atMs: s.atMs,
        durationMs: s.durationMs,
        frames: s.frames.map((f) => ({ img: jpeg(join(runDir, j.id, f.file)), afterMs: f.afterMs })),
        img: jpeg(join(runDir, j.id, s.shot)),
        signals: s.signals,
      })),
    };
  });
  findings.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  return { runId: run.runId, createdAt: run.createdAt, lang: run.app.lang, app: run.app, journeys, findings, triage: triage.items };
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

/** `fragment` is the Artifact form (the host adds doctype/head/body);
 *  otherwise a complete standalone document. */
export function renderReport(data: ReportData, fragment: boolean): string {
  const name = data.app.name || new URL(data.app.url).host;
  // `</` inside the JSON would end the script element early.
  const json = JSON.stringify(data).replace(/<\//g, '<\\/');
  const body = `<title>${esc(name)} UX audit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+JP:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>${REPORT_CSS}</style>
<main class="wrap" id="app" lang="${data.lang}"></main>
<dialog id="lightbox" aria-label="Screenshot">
  <figure>
    <img id="lb-img" alt="">
    <figcaption id="lb-cap"></figcaption>
  </figure>
  <div class="lb-nav">
    <button type="button" id="lb-prev">&larr;</button>
    <button type="button" id="lb-next">&rarr;</button>
    <button type="button" id="lb-close">Esc</button>
  </div>
</dialog>
<script type="application/json" id="uxaudit-data">${json}</script>
<script>${REPORT_JS.replace(/<\/script/gi, '<\\/script')}</script>`;
  if (fragment) return body;
  return `<!doctype html>
<html lang="${data.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
</head>
<body>
${body}
</body>
</html>
`;
}

/** Markdown hand-off for a coding agent: findings marked "fix", plus open
 *  blocker/major findings nobody has triaged yet. */
export function fixList(data: ReportData): string {
  const picked = data.findings.filter((f) => {
    const s = data.triage[f.id]?.status ?? 'open';
    return s === 'fix' || (s === 'open' && f.severity !== 'minor');
  });
  if (!picked.length) return 'No findings to fix.\n';
  const title = (id: string) => data.journeys.find((j) => j.id === id)?.title ?? id;
  return (
    `# UX fixes (${data.app.name ?? data.app.url}, run ${data.runId})\n\n` +
    picked
      .map((f) => {
        const note = data.triage[f.id]?.note;
        return [
          `## ${f.title}`,
          `- Journey: ${title(f.journey)} (steps ${f.steps.join(', ')})`,
          `- Severity: ${f.severity}, stage: ${f.stage}, status: ${data.triage[f.id]?.status ?? 'open'}`,
          `- Observed: ${f.observation}`,
          `- Suggested fix: ${f.suggestion}`,
          note ? `- Reviewer note: ${note}` : '',
        ]
          .filter(Boolean)
          .join('\n');
      })
      .join('\n\n') +
    '\n'
  );
}
