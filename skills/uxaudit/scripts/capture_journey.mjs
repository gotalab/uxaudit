#!/usr/bin/env node
/**
 * Walk a journey JSON through Playwright, capturing one screenshot + DOM snapshot
 * per waypoint. Used by L4 checks (and as a Playwright-driven baseline for L3
 * checks that compare a journey to a goal).
 *
 * Usage:
 *   node capture_journey.mjs <journey.json> <output-dir> [--video]
 *
 * Flags:
 *   --video           Also record a webm video of the entire journey.
 *                     The video lands in <output-dir>/journey.webm and is
 *                     automatically picked up by the dashboard if <output-dir>
 *                     is the check's evidence/ directory.
 *
 * journey.json schema (see references/concepts/architecture.md):
 *   {
 *     name, goal, starting_url, viewport: {width,height},
 *     viewport_only: false,       // default false → fullPage screenshots; set
 *                                 //   true ONLY for FTUE-style "what's in the
 *                                 //   first viewport at 1s / 5s" captures.
 *     steps: [
 *       { action: "navigate", url: "/" },
 *       { action: "click", selector: "text=Publish Recipe",
 *         expect_change: { kind: "navigation" | "dom" | "any", timeout_ms: 5000 } },
 *         //  ^ REQUIRED on destructive clicks (Publish/Save/Submit/Login/...)
 *         //    The capture will record `status: no-state-change` if the click
 *         //    resolved in Playwright but URL/DOM did not change — this closes
 *         //    the "click did nothing but the screenshot is identical" false
 *         //    positive that used to slip through as `status: ok`.
 *       { action: "type", selector: "input[name=email]", text: "..." },
 *       { action: "wait", ms: 500 } | { action: "wait", selector: "..." },
 *       { action: "screenshot", name: "after-publish" },
 *       { action: "scroll", to: "bottom" }
 *     ],
 *     success_criteria: "..."
 *   }
 *
 * Allowed action types (anything else throws at capture time):
 *   navigate | click | type | wait | screenshot | scroll
 *
 * Output (when <output-dir> = checks/<id>/evidence/):
 *   ├── steps.json          ← per-step status + frame_diff summary
 *   ├── 001.png             ← counter-only filenames (intent-neutral so the
 *   │                          Judge cannot be primed by Compiler-authored
 *   │                          names like `010-recipe-detail-page.png`)
 *   ├── 001.html            ← DOM snapshot at each screenshot waypoint
 *   ├── journey.webm        ← full journey video (only if --video)
 *   └── trace.zip           ← Playwright trace
 *
 * Each step with a screenshot carries:
 *   intent                  ← the Compiler's short descriptor, e.g. "after-publish"
 *   frame_hash              ← 12-char SHA-1 of the PNG bytes
 *   identical_to_previous   ← true iff frame_hash equals the prior frame's
 *   identical_run_length    ← length of the consecutive identical run so far
 *   full_page               ← true iff this screenshot was full-page
 *
 * steps.json top-level `frame_diff`:
 *   { total_frames, unique_frames, max_identical_run, capture_made_progress }
 *
 * Rule the Judge uses: if `max_identical_run >= 3` spans a destructive click
 * boundary, that click almost certainly produced no visible state change and
 * the affected axis (usually `task_completion` and `value_delivery`) must be
 * `fail`, not `pass`.
 */
import { mkdirSync, writeFileSync, readFileSync, renameSync, existsSync } from 'fs';
import { join } from 'path';
import { createHash } from 'crypto';
import {
  openTarget,
  closeTarget,
  getArg,
  hasFlag,
  parseViewport,
  resolveSameOriginUrl,
  validateLoopbackUrl,
} from './_target.mjs';

// Allow-list of supported action types. Anything outside this set throws at
// capture time so the Compiler cannot silently emit garbage (e.g. triple_click,
// hover, drag) that `status: unknown-action` used to hide.
const ALLOWED_ACTIONS = new Set([
  'navigate', 'click', 'type', 'wait', 'screenshot', 'scroll',
]);

// Destructive click kinds that should ALWAYS produce a state change. The
// Compiler emits `expect_change: { kind: 'navigation' | 'dom', timeout_ms? }`
// on any such click. When the assertion fails, the step is recorded as
// `no-state-change` and the Judge can trust the "click succeeded but nothing
// happened" signal instead of having to infer it from identical pixels.
const DEFAULT_EXPECT_CHANGE_TIMEOUT_MS = 5000;

// Strip flags to get positional args. Flags consumed below are mutually
// exclusive with extra positional after them.
const FLAGS_WITH_VALUE = new Set(['viewport', 'electron-app']);
const argv = process.argv.slice(2);
const positional = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    if (FLAGS_WITH_VALUE.has(a.slice(2))) i++;
    continue;
  }
  positional.push(a);
}
const [journeyPath, outDir] = positional;
const recordVideo = hasFlag('video');
const viewportArg = getArg('viewport');
const electronApp = getArg('electron-app');

if (!journeyPath || !outDir) {
  console.error('Usage: node capture_journey.mjs <journey.json> <output-dir> [--video] [--viewport mobile|...] [--electron-app PATH]');
  process.exit(1);
}

const journey = JSON.parse(readFileSync(journeyPath, 'utf-8'));
const startingUrl = electronApp ? null : validateLoopbackUrl(journey.starting_url, 'journey.starting_url');
mkdirSync(outDir, { recursive: true });

// Precedence for viewport: CLI flag > journey JSON > preset default.
let viewport;
if (viewportArg) {
  viewport = parseViewport(viewportArg);
} else if (journey.viewport && journey.viewport.width) {
  viewport = { ...journey.viewport, _name: `${journey.viewport.width}x${journey.viewport.height}` };
} else {
  viewport = parseViewport('desktop');
}

const recordVideoOpt = recordVideo
  ? { dir: outDir, size: { width: viewport.width, height: viewport.height } }
  : undefined;

const target = await openTarget({
  url: electronApp ? null : startingUrl,
  electronApp,
  viewport,
  recordVideo: recordVideoOpt,
  // Honor the journey's cold_start flag. When true, openTarget creates a
  // fresh-state context + explicit storage wipe + no-cache header so the
  // first-time user experience Judge gets a genuine cold-start capture.
  coldStart: !!journey.cold_start,
});
const { browser, ctx, page, kind } = target;
if (journey.cold_start) {
  console.error(`[journey] cold_start=true → fresh context, storage cleared, no-cache`);
}
if (ctx && ctx.tracing) {
  // Tracing is only available on web contexts; Electron skips it.
  await ctx.tracing.start({ screenshots: true, snapshots: true });
}

const steps = [];
let stepIdx = 0;
let stepCounter = 0;
let lastError = null;

// Frame fingerprinting: every screenshot gets a short SHA-1 of its PNG bytes
// so the Judge can detect runs of identical frames (e.g. a Publish click that
// succeeded in Playwright but produced no visible state change). Not a
// perceptual hash — two visually-identical frames that differ in a single
// pixel (cursor blink, clock) will register as different. That is fine for
// the common "click did nothing" bug we are trying to catch; false negatives
// are safer than false positives here.
let lastFrameHash = null;
let identicalRunLength = 0;

function pad(n, w) { return String(n).padStart(w, '0'); }

// 3-digit zero padding so per-journey screenshots sort lexicographically
// even past 99. A typical journey is 6-12 frames, but some product flows
// (long forms, error recovery loops, dense onboarding) can spike above
// 100 — at that point a 2-digit pad would put "100-foo" between "09-foo"
// and "10-foo" in ASCII order and break the dashboard waypoint strip
// + the L4 Judge's frame ordering. The screenshot name still appears
// in the orchestrator-facing docs as "01-...", not "001-...", because
// 3-digit padding is implementation detail; consumers should glob
// `*.png` and sort lexicographically rather than hard-coding the prefix.
const SCREENSHOT_PAD = 3;

async function snapshot(name) {
  stepCounter += 1;
  // Context hygiene: the Compiler's `name` hint used to leak its intent into
  // the Judge as a filename suffix (e.g. `010-recipe-detail-page.png` primed
  // the Judge to "see" a detail page even when the pixels still showed the
  // form). We keep the suffix in `steps.json` for human debugging, but the
  // filename on disk is the machine-neutral counter only. The Judge reads
  // the filename directly, so it now sees `010.png`, not an intent string.
  const fname = pad(stepCounter, SCREENSHOT_PAD);
  const pngPath = join(outDir, `${fname}.png`);
  const htmlPath = join(outDir, `${fname}.html`);
  // fullPage: true by default. Viewport-only screenshots used to hide
  // below-the-fold widgets (reviews, notes, cook-mode timer) and made
  // "affordance not visible" verdicts meaningless. The FTUE journey opts
  // out via `journey.viewport_only === true` because its whole rubric is
  // "what does a new user see in the first viewport at 1s and 5s".
  const useFullPage = journey.viewport_only !== true;
  await page.screenshot({ path: pngPath, fullPage: useFullPage });
  const html = await page.content();
  writeFileSync(htmlPath, html);
  // Fingerprint the PNG bytes so consecutive identical frames surface as
  // `identical_to_previous: true` in steps.json. The Judge uses this to
  // distinguish "genuine 3-step flow" from "3 frames of the same page
  // because the action did nothing".
  const bytes = readFileSync(pngPath);
  const frameHash = createHash('sha1').update(bytes).digest('hex').slice(0, 12);
  const identicalToPrevious = frameHash === lastFrameHash;
  if (identicalToPrevious) {
    identicalRunLength += 1;
  } else {
    identicalRunLength = 0;
  }
  lastFrameHash = frameHash;
  return {
    fname,
    intent: name.replace(/[^a-z0-9-]/gi, '-'),
    frame_hash: frameHash,
    identical_to_previous: identicalToPrevious,
    identical_run_length: identicalRunLength,
    full_page: useFullPage,
  };
}

async function resolveSelector(sel) {
  if (typeof sel !== 'string') return null;
  if (sel.startsWith('text=')) return page.getByText(sel.slice(5), { exact: false }).first();
  return page.locator(sel).first();
}

// openTarget() already navigated to journey.starting_url for web targets.
// For Electron we land in the app's first window — no goto needed.
await page.waitForTimeout(800);
const initial = await snapshot('initial');
steps.push({
  idx: 0,
  action: 'initial-load',
  status: 'ok',
  screenshot: `${initial.fname}.png`,
  dom: `${initial.fname}.html`,
  intent: initial.intent,
  frame_hash: initial.frame_hash,
  identical_to_previous: initial.identical_to_previous,
  full_page: initial.full_page,
});

for (const step of (journey.steps || [])) {
  stepIdx += 1;
  const record = { idx: stepIdx, action: step.action, status: 'ok' };
  try {
    // Structural guard: the Compiler promised to emit only allow-listed action
    // types. If it emitted something else we fail loud instead of silently
    // passing — the old `status: unknown-action` path let garbage survive into
    // steps.json and polluted downstream judgments.
    if (!ALLOWED_ACTIONS.has(step.action)) {
      throw new Error(
        `Unknown action type: ${JSON.stringify(step.action)}. ` +
        `Allowed: ${[...ALLOWED_ACTIONS].join(', ')}`
      );
    }
    if (step.action === 'navigate') {
      const url = resolveSameOriginUrl(step.url, startingUrl, 'journey.steps[].url');
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
      record.url = url;
    } else if (step.action === 'click') {
      // Capture a "before" state so we can verify expect_change after click.
      // We check both URL (SPA navigation, anchor change) and DOM size
      // (modal open, list item added, toast shown). A change in EITHER
      // satisfies the assertion.
      const before = step.expect_change
        ? {
            url: page.url(),
            html_len: await page.evaluate(() => document.body.innerHTML.length).catch(() => 0),
          }
        : null;
      const loc = await resolveSelector(step.selector);
      await loc.click({ timeout: 8000 });
      record.selector = step.selector;
      if (step.expect_change) {
        const timeout = step.expect_change.timeout_ms || DEFAULT_EXPECT_CHANGE_TIMEOUT_MS;
        const kind = step.expect_change.kind || 'any';
        record.expect_change = { kind, timeout_ms: timeout };
        try {
          // Playwright's waitForFunction only forwards ONE arg to the page
          // function — use the built-in waitForURL for the navigation case
          // (more reliable than sniffing location.href inside a polled eval)
          // and an object arg for the DOM / any cases.
          if (kind === 'navigation') {
            await page.waitForURL((u) => u.toString() !== before.url, { timeout });
          } else if (kind === 'dom') {
            await page.waitForFunction(
              (b) => Math.abs(document.body.innerHTML.length - b.html_len) > 20,
              before,
              { timeout }
            );
          } else {
            // 'any' — either URL or DOM change is enough
            await page.waitForFunction(
              (b) =>
                location.href !== b.url ||
                Math.abs(document.body.innerHTML.length - b.html_len) > 20,
              before,
              { timeout }
            );
          }
          record.state_changed = true;
          // Record what actually moved so the Judge can debug post-hoc.
          const after = {
            url: page.url(),
            html_len: await page.evaluate(() => document.body.innerHTML.length).catch(() => 0),
          };
          record.state_change_observed = {
            url_changed: after.url !== before.url,
            dom_size_delta: after.html_len - before.html_len,
          };
        } catch (e) {
          // The click resolved in Playwright but the expected change never
          // happened. This used to ship as `status: ok` + identical-pixel
          // screenshots and fooled the Judge into thinking the form
          // submitted. Now it surfaces as an explicit failure mode.
          record.status = 'no-state-change';
          record.error =
            `click on ${step.selector} succeeded but expected ${kind} change ` +
            `did not happen within ${timeout}ms`;
          lastError = record;
          try {
            const f = await snapshot(`no-change-${stepIdx}`);
            record.screenshot = `${f.fname}.png`;
            record.dom = `${f.fname}.html`;
            record.intent = f.intent;
            record.frame_hash = f.frame_hash;
            record.identical_to_previous = f.identical_to_previous;
          } catch {}
          steps.push(record);
          break;
        }
      }
    } else if (step.action === 'type') {
      const loc = await resolveSelector(step.selector);
      await loc.fill(step.text || '');
      record.selector = step.selector;
      record.text_length = (step.text || '').length;
    } else if (step.action === 'wait') {
      if (step.selector) {
        const loc = await resolveSelector(step.selector);
        await loc.waitFor({ state: 'visible', timeout: 10000 });
        record.selector = step.selector;
      } else {
        await page.waitForTimeout(step.ms || 500);
        record.ms = step.ms || 500;
      }
    } else if (step.action === 'screenshot') {
      const name = step.name || `step-${stepIdx}`;
      const f = await snapshot(name);
      record.screenshot = `${f.fname}.png`;
      record.dom = `${f.fname}.html`;
      record.intent = f.intent;
      record.frame_hash = f.frame_hash;
      record.identical_to_previous = f.identical_to_previous;
      record.identical_run_length = f.identical_run_length;
      record.full_page = f.full_page;
    } else if (step.action === 'scroll') {
      if (step.to === 'bottom') {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      } else if (step.to === 'top') {
        await page.evaluate(() => window.scrollTo(0, 0));
      } else if (typeof step.delta === 'number') {
        await page.evaluate((d) => window.scrollBy(0, d), step.delta);
      }
      record.to = step.to;
      record.delta = step.delta;
    }
  } catch (e) {
    record.status = 'error';
    record.error = `${e.name}: ${e.message}`.slice(0, 240);
    lastError = record;
    // capture an error screenshot to show the failure context
    try {
      const f = await snapshot(`error-${stepIdx}`);
      record.screenshot = `${f.fname}.png`;
      record.dom = `${f.fname}.html`;
      record.intent = f.intent;
      record.frame_hash = f.frame_hash;
      record.identical_to_previous = f.identical_to_previous;
    } catch {}
    steps.push(record);
    break;
  }
  steps.push(record);
}

// Always capture a final state if we didn't already
const finalName = lastError ? 'after-error' : 'final';
try {
  const f = await snapshot(finalName);
  steps.push({
    idx: stepIdx + 1,
    action: 'final-state',
    status: 'ok',
    screenshot: `${f.fname}.png`,
    dom: `${f.fname}.html`,
    intent: f.intent,
    frame_hash: f.frame_hash,
    identical_to_previous: f.identical_to_previous,
    identical_run_length: f.identical_run_length,
    full_page: f.full_page,
  });
} catch (e) {}

if (ctx && ctx.tracing) {
  try { await ctx.tracing.stop({ path: join(outDir, 'trace.zip') }); } catch {}
}

// Surface frame-diff summary at the top level of steps.json so the Judge sees
// it without having to walk every step. This is the single most load-bearing
// signal for detecting "the click did nothing" — a long run of identical
// frames after a destructive click means the action had no visible effect,
// regardless of what the filename `intent` suggests.
const frameRecords = steps.filter((s) => s.frame_hash);
const uniqueFrames = new Set(frameRecords.map((s) => s.frame_hash));
let maxIdenticalRun = 0;
let currentRun = 0;
let prevHash = null;
for (const s of frameRecords) {
  if (s.frame_hash === prevHash) {
    currentRun += 1;
  } else {
    currentRun = 1;
    prevHash = s.frame_hash;
  }
  if (currentRun > maxIdenticalRun) maxIdenticalRun = currentRun;
}

writeFileSync(join(outDir, 'steps.json'), JSON.stringify({
  name: journey.name,
  goal: journey.goal,
  starting_url: startingUrl,
  success_criteria: journey.success_criteria || '',
  viewport,
  cold_start: !!journey.cold_start,
  viewport_only: journey.viewport_only === true,
  total_steps: (journey.steps || []).length,
  completed_steps: steps.filter(s => s.status === 'ok').length,
  failed_at: lastError ? lastError.idx : null,
  frame_diff: {
    total_frames: frameRecords.length,
    unique_frames: uniqueFrames.size,
    max_identical_run: maxIdenticalRun,
    // Convenience flag the Judge reads directly: "capture produced enough
    // visual variety to actually evaluate a multi-step flow". If the entire
    // journey is 1-2 unique frames, the verdict is almost always `unverifiable`
    // or `fail` regardless of what the screenshots individually look like.
    capture_made_progress: uniqueFrames.size >= 3,
  },
  steps,
  captured_at: new Date().toISOString(),
}, null, 2));

// Close context first so the video file flushes to disk, then rename
// it to a stable name that the dashboard can find. Electron has no
// video recording — kind === 'electron' skips this entirely.
let videoPath = null;
if (recordVideo && kind === 'web') {
  try { videoPath = await page.video()?.path(); } catch {}
}
await closeTarget(target);
if (videoPath && existsSync(videoPath)) {
  const finalVideo = join(outDir, 'journey.webm');
  try { renameSync(videoPath, finalVideo); }
  catch (e) { console.error(`[journey] could not rename video: ${e.message}`); }
}

console.error(`[journey] done → ${outDir} (${steps.length} step records${recordVideo ? ' + journey.webm' : ''})`);
