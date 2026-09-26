// Browser-side script embedded in the report. Bundled to an IIFE string at
// build time (see package.json `build:client`).
import type { ReportData, ReportFinding } from '../report.ts';

type Status = 'open' | 'fix' | 'accepted' | 'false-positive';
interface TriageItem { status: Status; note: string; title?: string; updatedAt: string }

interface Store {
  mode: 'shared' | 'local' | 'none';
  save(id: string, item: TriageItem): Promise<void>;
}

const data: ReportData = JSON.parse(document.getElementById('uxaudit-data')!.textContent!);
const triage: Record<string, TriageItem> = { ...(data.triage as Record<string, TriageItem>) };
let store: Store = { mode: 'none', save: async () => {} };
let showTriaged = false;

const T = {
  en: {
    journeys: 'journeys', passed: 'passed', failed: 'failed', unclear: 'unclear', pending: 'not judged',
    open: 'open findings', findings: 'Findings', journeysH: 'Journeys',
    fix: 'Fix', accepted: 'Accept', 'false-positive': 'Not an issue', reopen: 'Reopen',
    note: 'Note for the fixer (optional)', observed: 'What the user sees', suggestion: 'Suggested fix',
    step: 'step', steps: 'steps', goal: 'Goal', showTriaged: 'Show triaged', hideTriaged: 'Hide triaged',
    copyFixes: 'Copy fix list', export: 'Export triage.json', copied: 'Copied to clipboard',
    exported: 'Saved triage.json', noFindings: 'No findings. Every judged journey passed.',
    allTriaged: 'Every finding has been triaged.', notJudged: 'Not judged yet. Run the judge step, then regenerate this report.',
    shared: 'Triage is saved to this page and shared with Claude and other viewers.',
    local: 'Triage is saved in this browser only. Export triage.json and commit it to keep it.',
    blocked: 'Journey stopped here', noChange: 'no visible change', slow: 'slow', overflow: 'horizontal scroll',
    console: 'console error', http: 'HTTP', statusFix: 'marked fix', statusAccepted: 'accepted', statusFp: 'not an issue',
    copyFail: 'Copy failed. Select the text below instead.', close: 'Close',
    watch: 'Watch', video: 'Recording', briefly: 'brief state', after: 's after the action',
  },
  ja: {
    journeys: 'ジャーニー', passed: '合格', failed: '不合格', unclear: '判定保留', pending: '未判定',
    open: '未対応の指摘', findings: '指摘', journeysH: 'ジャーニー',
    fix: '直す', accepted: '許容', 'false-positive': '問題なし', reopen: '未対応に戻す',
    note: '修正する人へのメモ（任意）', observed: 'ユーザーに見えていること', suggestion: '修正案',
    step: 'ステップ', steps: 'ステップ', goal: 'ゴール', showTriaged: '対応済みも表示', hideTriaged: '対応済みを隠す',
    copyFixes: '修正リストをコピー', export: 'triage.json を書き出す', copied: 'コピーしました',
    exported: 'triage.json を保存しました', noFindings: '指摘はありません。判定済みのジャーニーはすべて合格です。',
    allTriaged: 'すべての指摘をトリアージ済みです。', notJudged: 'まだ判定していません。判定ステップを実行してからレポートを再生成してください。',
    shared: 'トリアージはこのページに保存され、Claude や他の閲覧者と共有されます。',
    local: 'トリアージはこのブラウザにだけ保存されます。残すには triage.json を書き出してコミットしてください。',
    blocked: 'ここでジャーニーが止まりました', noChange: '画面変化なし', slow: '遅い', overflow: '横スクロール',
    console: 'コンソールエラー', http: 'HTTP', statusFix: '直す', statusAccepted: '許容', statusFp: '問題なし',
    copyFail: 'コピーできませんでした。下のテキストを選択してください。', close: '閉じる',
    watch: '動画で見る', video: '録画', briefly: '一瞬だけ表示', after: '秒後',
  },
}[data.lang];

const SEV = { en: { blocker: 'Blocker', major: 'Major', minor: 'Minor' }, ja: { blocker: '致命的', major: '重大', minor: '軽微' } }[data.lang];
const STAGE = {
  en: { understand: 'Understand', decide: 'Decide', act: 'Act', recover: 'Recover' },
  ja: { understand: '理解', decide: '判断', act: '操作', recover: '回復' },
}[data.lang] as Record<string, string>;

// ── tiny DOM helper ────────────────────────────────────────────────────────
type Child = Node | string | null | undefined | false;
function h(tag: string, attrs: Record<string, unknown> = {}, ...children: (Child | Child[])[]): HTMLElement {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v as EventListener);
    else if (k === 'class') el.className = String(v);
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}

const statusOf = (id: string): Status => triage[id]?.status ?? 'open';
const journeyOf = (id: string) => data.journeys.find((j) => j.id === id)!;

// ── render ─────────────────────────────────────────────────────────────────
function render() {
  const app = document.getElementById('app')!;
  app.replaceChildren(header(), findingsSection(), journeysSection());
}

function header() {
  const judged = data.journeys.filter((j) => j.verdict);
  const count = (v: string) => judged.filter((j) => j.verdict!.verdict === v).length;
  const openCount = data.findings.filter((f) => statusOf(f.id) === 'open').length;
  const pending = data.journeys.length - judged.length;
  const when = new Date(data.createdAt);
  return h('header', { class: 'top' },
    h('div', { class: 'brand' }, 'uxaudit'),
    h('h1', {}, data.app.name || new URL(data.app.url).host),
    h('p', { class: 'meta mono' }, `${data.app.url} · ${when.toLocaleString(data.lang === 'ja' ? 'ja-JP' : 'en-US')} · run ${data.runId}`),
    h('div', { class: 'tally' },
      h('span', {}, h('b', {}, String(data.journeys.length)), T.journeys),
      h('span', { class: 't-pass' }, h('b', {}, String(count('pass'))), T.passed),
      h('span', { class: 't-fail' }, h('b', {}, String(count('fail'))), T.failed),
      count('unclear') ? h('span', { class: 't-warn' }, h('b', {}, String(count('unclear'))), T.unclear) : null,
      pending ? h('span', { class: 't-warn' }, h('b', {}, String(pending)), T.pending) : null,
      h('span', { class: openCount ? 't-fail' : '' }, h('b', {}, String(openCount)), T.open),
    ),
    store.mode === 'none' ? null : h('p', { class: `store-note ${store.mode}` }, store.mode === 'shared' ? T.shared : T.local),
  );
}

function findingsSection() {
  const toast = h('span', { class: 'toast', role: 'status' });
  const open = data.findings.filter((f) => statusOf(f.id) === 'open');
  const triaged = data.findings.filter((f) => statusOf(f.id) !== 'open');
  const list = showTriaged ? [...open, ...triaged] : open;
  const tools = h('div', { class: 'tools' },
    toast,
    triaged.length ? h('button', { class: 'btn', type: 'button', onclick: () => { showTriaged = !showTriaged; render(); } },
      `${showTriaged ? T.hideTriaged : T.showTriaged} (${triaged.length})`) : null,
    data.findings.length ? h('button', { class: 'btn', type: 'button', onclick: () => copyFixList(toast) }, T.copyFixes) : null,
    store.mode === 'local' && Object.keys(triage).length ? h('button', { class: 'btn', type: 'button', onclick: () => exportTriage(toast) }, T.export) : null,
  );
  let body: HTMLElement;
  if (!data.findings.length) {
    const anyJudged = data.journeys.some((j) => j.verdict);
    body = h('p', { class: 'empty' }, anyJudged ? T.noFindings : T.notJudged);
  } else if (!list.length) {
    body = h('p', { class: 'empty' }, T.allTriaged);
  } else {
    body = h('ol', { class: 'findings' }, list.map(findingItem));
  }
  return h('section', { class: 'section', id: 'findings' },
    h('div', { class: 'section-head' }, h('h2', {}, T.findings), tools),
    body,
  );
}

function findingItem(f: ReportFinding) {
  const j = journeyOf(f.journey);
  const status = statusOf(f.id);
  const item = triage[f.id];
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Triage' },
    (['fix', 'accepted', 'false-positive'] as const).map((s) =>
      h('button', {
        type: 'button', 'data-s': s, 'aria-pressed': String(status === s),
        onclick: () => setTriage(f, status === s ? 'open' : s, item?.note ?? ''),
      }, T[s])),
  );
  const note = h('input', {
    class: 'note', id: `note-${f.id}`, type: 'text', placeholder: T.note, value: item?.note ?? '',
    onchange: (e: Event) => setTriage(f, statusOf(f.id), (e.target as HTMLInputElement).value),
  });
  const thumbs = f.steps.map((n) => {
    const s = j.steps[n - 1];
    return s ? h('button', { class: 'thumb', type: 'button', 'aria-label': `${T.step} ${n}`, onclick: () => openLightbox(j.id, n) },
      h('img', { src: s.img, alt: `${T.step} ${n}: ${s.label}` }),
      h('span', { class: 'badge' }, String(n).padStart(2, '0'))) : null;
  });
  return h('li', { class: `finding${status !== 'open' ? ' triaged' : ''}`, 'data-id': f.id },
    h('div', { class: 'f-head' },
      h('span', { class: `chip sev-${f.severity}` }, SEV[f.severity]),
      h('span', { class: 'chip stage' }, STAGE[f.stage] ?? f.stage),
      h('span', {}, `${j.title} · ${f.steps.length > 1 ? T.steps : T.step} ${f.steps.join(', ')}`),
    ),
    h('h3', {}, f.title),
    h('div', { class: 'f-body' },
      h('div', { class: 'f-thumbs' }, thumbs,
        j.video ? h('button', { class: 'btn watch', type: 'button', onclick: () => seekVideo(j.id, j.steps[f.steps[0]! - 1]?.atMs ?? 0) }, `▶ ${T.watch}`) : null),
      h('dl', {}, h('dt', {}, T.observed), h('dd', {}, f.observation), h('dt', {}, T.suggestion), h('dd', {}, f.suggestion)),
    ),
    h('div', { class: 'triage' }, seg, note),
  );
}

function journeysSection() {
  return h('section', { class: 'section', id: 'journeys' },
    h('h2', {}, T.journeysH),
    h('div', { class: 'journeys' }, data.journeys.map((j) => {
      const v = j.verdict?.verdict ?? 'pending';
      const label = v === 'pass' ? T.passed : v === 'fail' ? T.failed : v === 'unclear' ? T.unclear : T.pending;
      return h('article', { class: 'journey', id: `j-${j.id}` },
        h('div', { class: 'j-head' },
          h('span', { class: `verdict v-${v}` }, label),
          h('h3', {}, j.title),
          h('span', { class: 'focus' }, [j.focus, j.viewport, j.auth && `auth: ${j.auth}`].filter(Boolean).join(' · ')),
        ),
        h('p', { class: 'goal' }, h('b', {}, `${T.goal}: `), j.goal),
        j.verdict ? h('p', { class: 'j-summary' }, j.verdict.summary) : null,
        j.video ? h('video', { class: 'rec', id: `v-${j.id}`, src: j.video, controls: true, muted: true, playsinline: true, preload: 'metadata', 'aria-label': `${T.video}: ${j.title}` }) : null,
        h('ol', { class: 'strip' }, j.steps.map((s) => h('li', { class: `frame st-${s.status}` },
          h('button', { class: 'thumb', type: 'button', 'aria-label': `${T.step} ${s.index}`, onclick: () => openLightbox(j.id, s.index) },
            h('img', { src: s.img, alt: `${T.step} ${s.index}: ${s.label}` }),
            s.frames.length ? h('span', { class: 'badge more' }, `+${s.frames.length}`) : null),
          h('div', { class: 'cap' },
            h('span', { class: 'num' }, String(s.index).padStart(2, '0')), s.label,
            j.video ? h('button', { class: 'seek mono', type: 'button', title: T.watch, onclick: () => seekVideo(j.id, s.atMs) }, `▶ ${clock(s.atMs)}`) : null),
          flags(s),
        ))),
      );
    })),
  );
}

function flags(s: ReportData['journeys'][number]['steps'][number]) {
  const out: HTMLElement[] = [];
  if (s.status === 'failed') out.push(h('span', { class: 'flag', title: s.error ?? '' }, T.blocked));
  if (s.status === 'no-change') out.push(h('span', { class: 'flag' }, T.noChange));
  if (s.frames.length) out.push(h('span', { class: 'flag soft' }, `${T.briefly} ×${s.frames.length}`));
  if (s.signals.consoleErrors.length) out.push(h('span', { class: 'flag', title: s.signals.consoleErrors.join('\n') }, `${T.console} ×${s.signals.consoleErrors.length}`));
  for (const e of s.signals.httpErrors) out.push(h('span', { class: 'flag', title: e.url }, `${T.http} ${e.status}`));
  if (s.signals.slow) out.push(h('span', { class: 'flag soft' }, `${T.slow} ${(s.durationMs / 1000).toFixed(1)}s`));
  if (s.signals.horizontalOverflow) out.push(h('span', { class: 'flag soft' }, T.overflow));
  return out.length ? h('div', { class: 'flags' }, out) : null;
}

// ── triage ─────────────────────────────────────────────────────────────────
async function setTriage(f: ReportFinding, status: Status, note: string) {
  const item: TriageItem = { status, note, title: f.title, updatedAt: new Date().toISOString() };
  triage[f.id] = item;
  render();
  try {
    await store.save(f.id, item);
  } catch (e) {
    console.warn('uxaudit: triage save failed', e);
  }
}

function mergeIn(id: string, item: TriageItem) {
  const prev = triage[id];
  if (!prev || prev.updatedAt < item.updatedAt) triage[id] = item;
}

const LOCAL_KEY = `uxaudit-triage:${data.app.url}`;

async function initStore() {
  const claude = (window as unknown as { claude?: { use(name: string): Promise<any> } }).claude;
  let db: any = null;
  try {
    if (claude?.use) db = await claude.use('db');
  } catch {
    db = null;
  }
  if (db) {
    const col = db.collection('triage');
    store = { mode: 'shared', save: (id, item) => col.doc(id).set(item) };
    col.onSnapshot(
      (snap: { docs: { id: string; data(): TriageItem }[] }) => {
        for (const d of snap.docs) mergeIn(d.id, d.data());
        // Don't rebuild the DOM under someone typing a note; their change event re-renders.
        if (!(document.activeElement as HTMLElement | null)?.classList.contains('note')) render();
      },
      (err: unknown) => console.warn('uxaudit: triage sync stopped', err),
    );
    render();
    return;
  }
  try {
    const saved = JSON.parse(localStorage.getItem(LOCAL_KEY) || '{}') as Record<string, TriageItem>;
    for (const [id, item] of Object.entries(saved)) mergeIn(id, item);
    store = {
      mode: 'local',
      save: async () => {
        try { localStorage.setItem(LOCAL_KEY, JSON.stringify(triage)); } catch { /* storage blocked */ }
      },
    };
  } catch {
    store = { mode: 'local', save: async () => {} };
  }
  render();
}

function fixListMarkdown() {
  const picked = data.findings.filter((f) => {
    const s = statusOf(f.id);
    return s === 'fix' || (s === 'open' && f.severity !== 'minor');
  });
  return `# UX fixes (${data.app.name ?? data.app.url}, run ${data.runId})\n\n` + picked.map((f) => [
    `## ${f.title}`,
    `- Journey: ${journeyOf(f.journey).title} (steps ${f.steps.join(', ')})`,
    `- Severity: ${f.severity}, stage: ${f.stage}, status: ${statusOf(f.id)}`,
    `- Observed: ${f.observation}`,
    `- Suggested fix: ${f.suggestion}`,
    triage[f.id]?.note ? `- Reviewer note: ${triage[f.id]!.note}` : '',
  ].filter(Boolean).join('\n')).join('\n\n') + '\n';
}

async function copyFixList(toast: HTMLElement) {
  const text = fixListMarkdown();
  try {
    await navigator.clipboard.writeText(text);
    toast.textContent = T.copied;
  } catch {
    toast.textContent = T.copyFail;
    const area = h('textarea', { class: 'note', rows: '8', readonly: 'true' }) as HTMLTextAreaElement;
    area.value = text;
    toast.after(area);
    area.select();
  }
}

async function exportTriage(toast: HTMLElement) {
  const text = JSON.stringify({ version: 1, items: triage }, null, 2) + '\n';
  const claude = (window as unknown as { claude?: { use(name: string): Promise<any> } }).claude;
  const downloads = claude?.use ? await claude.use('downloads').catch(() => null) : null;
  if (downloads) {
    try {
      await downloads.save({ filename: 'triage.json', data: text });
      toast.textContent = T.exported;
    } catch { /* declined */ }
    return;
  }
  if (!claude) {
    const a = h('a', { href: URL.createObjectURL(new Blob([text], { type: 'application/json' })), download: 'triage.json' });
    a.click();
    toast.textContent = T.exported;
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toast.textContent = T.copied;
  } catch {
    toast.textContent = T.copyFail;
  }
}

// ── lightbox ───────────────────────────────────────────────────────────────
const lb = document.getElementById('lightbox') as HTMLDialogElement;
interface Shot { img: string; caption: string; step: number; final: boolean }
let lbAt: { shots: Shot[]; i: number } | null = null;

/** Every image of a journey in order: short-lived frames, then the settled screen. */
function shotsOf(journey: string): Shot[] {
  const j = journeyOf(journey);
  return j.steps.flatMap((s) => {
    const n = String(s.index).padStart(2, '0');
    return [
      ...s.frames.map((f) => ({ img: f.img, step: s.index, final: false, caption: `${j.title} · ${n} ${s.label} · ${(f.afterMs / 1000).toFixed(1)}${T.after} (${T.briefly})` })),
      { img: s.img, step: s.index, final: true, caption: `${j.title} · ${n} ${s.label}${s.error ? ` — ${s.error}` : ''}` },
    ];
  });
}

function openLightbox(journey: string, step: number) {
  const shots = shotsOf(journey);
  lbAt = { shots, i: Math.max(0, shots.findIndex((x) => x.step === step && x.final)) };
  showFrame();
  if (!lb.open) lb.showModal();
}

function showFrame() {
  if (!lbAt) return;
  const shot = lbAt.shots[lbAt.i]!;
  const img = document.getElementById('lb-img') as HTMLImageElement;
  img.src = shot.img;
  img.alt = shot.caption;
  document.getElementById('lb-cap')!.textContent = shot.caption;
}

function stepFrame(d: number) {
  if (!lbAt) return;
  const n = lbAt.shots.length;
  lbAt.i = (lbAt.i + d + n) % n;
  showFrame();
}

// ── video ──────────────────────────────────────────────────────────────────
const clock = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

function seekVideo(journey: string, atMs: number) {
  const v = document.getElementById(`v-${journey}`) as HTMLVideoElement | null;
  if (!v) return;
  if (lb.open) lb.close();
  v.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  v.currentTime = Math.max(0, atMs / 1000 - 0.3);
  void v.play().catch(() => {});
}

document.getElementById('lb-prev')!.addEventListener('click', () => stepFrame(-1));
document.getElementById('lb-next')!.addEventListener('click', () => stepFrame(1));
document.getElementById('lb-close')!.addEventListener('click', () => lb.close());
document.getElementById('lb-close')!.setAttribute('aria-label', T.close);
lb.addEventListener('click', (e) => { if (e.target === lb) lb.close(); });
lb.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') stepFrame(-1);
  if (e.key === 'ArrowRight') stepFrame(1);
});

render();
void initStore();
