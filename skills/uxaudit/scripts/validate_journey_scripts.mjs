#!/usr/bin/env node
/**
 * Journey-script dry-run validator.
 *
 * Walks every `<journey-scripts-dir>/*.json` through Playwright in a
 * lightweight "dry-run" mode that exercises navigations, clicks, types,
 * waits and scrolls — but skips screenshots and DOM snapshots — so the
 * orchestrator can find out which selectors actually resolve BEFORE the
 * full capture phase commits to a verdict.
 *
 * Why this exists
 * ───────────────
 * The Compiler subagent (Phase 03 Step 9) writes selectors by reading the
 * starting page's curl-fetched HTML once, with no execution context. That
 * works for ~50 % of journeys; the rest break on subtle mismatches like
 *
 *   - the field is a <textarea> not an <input>
 *   - the placeholder string is "My Weeknight Favorites" not "Name"
 *   - the dietary pill only mounts after the user opens a Filters drawer
 *   - `a[href^="/recipe/"]` matches the header `+ New Recipe` CTA before
 *     the recipe card link
 *
 * Without this validator, those failures only show up at capture time, by
 * which point the L4 Judge sees a half-broken evidence directory and
 * (correctly) marks every axis fail. The orchestrator then can't tell
 * whether the app is bad or whether the script was bad.
 *
 * With this validator, the orchestrator runs us first, sees which
 * selectors didn't resolve, hands the failures back to the Compiler
 * for a healing pass, and only commits to capture when scripts are
 * known-good. The cost is one extra Playwright run per journey at
 * 4-way parallelism — usually 30–60s per iteration, well worth it
 * versus the cost of audits that lie.
 *
 * Output
 * ──────
 * For each `<journey-scripts-dir>/<id>.json`, write
 * `<journey-scripts-dir>/<id>.validation.json` with:
 *
 *   {
 *     "journey_id": "ai-meal-plan",
 *     "validated_at": "<iso>",
 *     "starting_url": "http://localhost:3000/meal-planner",
 *     "viewport": { "width": 1440, "height": 900 },
 *     "ok": false,
 *     "first_error_step": 10,
 *     "steps": [
 *       { "idx": 0, "action": "initial-load", "status": "ok" },
 *       { "idx": 1, "action": "click", "selector": "...", "status": "ok" },
 *       …
 *       {
 *         "idx": 10, "action": "type",
 *         "selector": "input[placeholder*='rice, olive oil']",
 *         "status": "error",
 *         "error": "TimeoutError: locator.fill: Timeout 8000ms exceeded.",
 *         "dom_excerpt": "<...>"   // best-guess HTML around the failure
 *       }
 *     ]
 *   }
 *
 * The orchestrator reads `ok` first; if false, hands the per-step
 * `error` + `dom_excerpt` rows to the Compiler healing prompt.
 *
 * Usage
 * ─────
 *   node validate_journey_scripts.mjs <journey-scripts-dir> [--viewport <preset|WxH>]
 *
 * Exits 0 even when individual journeys fail — the orchestrator inspects
 * the .validation.json files to decide what to do. Exit 2 only on hard
 * setup errors (missing dir, no scripts, browser launch failure).
 *
 * Concurrency: walks journeys sequentially. Parallelism here would fight
 * the dev server (the same server is also serving the capture phase) and
 * the validator runtime is dominated by per-action waits, not browser
 * spin-up.
 */
import { mkdirSync, readdirSync, readFileSync, writeFileSync, existsSync, statSync } from 'fs';
import { join, basename } from 'path';
import {
  openTarget,
  closeTarget,
  getArg,
  parseViewport,
  resolveSameOriginUrl,
  validateLoopbackUrl,
} from './_target.mjs';

// ──────────────────────────────────────────────────────────────────────
// Args + setup
// ──────────────────────────────────────────────────────────────────────

const argv = process.argv.slice(2);
const positional = [];
const FLAGS_WITH_VALUE = new Set(['viewport']);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    if (FLAGS_WITH_VALUE.has(a.slice(2))) i++;
    continue;
  }
  positional.push(a);
}
const [scriptsDir] = positional;
const viewportArg = getArg('viewport');

if (!scriptsDir) {
  console.error('Usage: node validate_journey_scripts.mjs <journey-scripts-dir> [--viewport <preset|WxH>]');
  process.exit(2);
}
if (!existsSync(scriptsDir) || !statSync(scriptsDir).isDirectory()) {
  console.error(`[validate] not a directory: ${scriptsDir}`);
  process.exit(2);
}

const journeyFiles = readdirSync(scriptsDir)
  .filter(f => f.endsWith('.json') && !f.endsWith('.validation.json'))
  .sort();

if (journeyFiles.length === 0) {
  console.error(`[validate] no journey scripts in ${scriptsDir}`);
  process.exit(2);
}

console.error(`[validate] dry-running ${journeyFiles.length} journey script(s) in ${scriptsDir}`);

// ──────────────────────────────────────────────────────────────────────
// Static lint — mechanical Compiler bugs that don't need a browser
// ──────────────────────────────────────────────────────────────────────

/**
 * Set of action types capture_journey.mjs actually understands. Must
 * stay in sync with the ALLOWED_ACTIONS set in capture_journey.mjs —
 * anything else is a Compiler-side invention (triple_click, hover,
 * drag) that capture will reject at runtime.
 */
const ALLOWED_ACTIONS = new Set([
  'navigate', 'click', 'type', 'wait', 'screenshot', 'scroll',
]);

/**
 * Heuristic: is this click "destructive" and therefore required to
 * carry an `expect_change`? We can't know for sure without running
 * the app, but we can match the selector text against a vocabulary
 * of verbs that almost always produce a state change. False positives
 * are OK (the Compiler can argue it back), false negatives are not
 * (they produce create-first-recipe-style false passes).
 */
const DESTRUCTIVE_VERBS = [
  'publish', 'save', 'submit', 'login', 'log in', 'sign in', 'sign up',
  'create', 'add', 'send', 'delete', 'remove', 'confirm', 'continue',
  'next', 'checkout', 'pay', 'order', 'generate', 'update', 'apply',
];

function looksDestructive(selector) {
  if (typeof selector !== 'string') return false;
  const lower = selector.toLowerCase();
  return DESTRUCTIVE_VERBS.some((v) => lower.includes(v));
}

/**
 * Detect hardcoded dynamic IDs (nanoid / uuid / database PKs) inside selectors.
 *
 * Why: the Compiler reads the running app's HTML once via curl. If a recipe
 * card link looks like `<a href="/recipe/aNeCG92BKQTwo3pjptKO5">` at compile
 * time, the Compiler tends to copy that ID verbatim into the journey script.
 * The next time seed data is regenerated, the ID changes, the selector
 * doesn't resolve, and capture lies. We saw this twice in a single session
 * during recipe_app_01 iter-6: once for `aNeCG92BKQTwo3pjptKO5` and once
 * for `o82dzK44fkszE6gHwboiE`. Both were nanoids.
 *
 * Detection strategy — two patterns, both surgically scoped:
 *
 *   1. **UUID v4 anywhere** in the selector. UUIDs are almost never stable
 *      across seed regenerations (unless explicitly pinned), so any UUID
 *      substring is suspicious regardless of context.
 *
 *   2. **15+ char id-like token after `/<resource>/`**. This is the
 *      `/recipe/<id>` / `/user/<id>` / `/cookbook/<id>` pattern. We require:
 *        - 15+ chars (nanoid is 21 by default; long enough to rule out slugs)
 *        - mixed letters+digits OR mixed upper+lower (rules out kebab slugs
 *          like `meal-dinner` or `slow-cooker-recipes`)
 *
 * What we deliberately do NOT flag:
 *   - `text=<long content string>` selectors — content is content, not an ID
 *   - `[data-testid='primary-action-button']` — developer-controlled, stable
 *   - `[placeholder='Search by recipe name, ingredient, or description...']`
 *     — static UI copy
 *   - kebab-case-only paths like `/browse?tag=meal-dinner` — slugs are stable
 *
 * The Compiler can swap a flagged selector for a flexible match, e.g.
 *   `a[href='/recipe/aNeCG92BKQTwo3pjptKO5']`
 *     → `a[href^='/recipe/']:not([href='/recipe/new'])`
 * which survives seed regeneration without losing intent.
 */
const UUID_REGEX = /\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b/g;
const PATH_ID_REGEX = /\/[a-z][a-z0-9-]*\/([A-Za-z0-9_-]{15,})/g;

function findHardcodedDynamicIds(selector) {
  if (typeof selector !== 'string') return [];
  // text= selectors carry content, not selectors-by-id. A long product name
  // like "Slow Cooker Beef Stew with Root Vegetables" should not be flagged.
  if (selector.startsWith('text=')) return [];

  const findings = [];

  // Pattern 1 — UUID v4 anywhere
  let m;
  UUID_REGEX.lastIndex = 0;
  while ((m = UUID_REGEX.exec(selector)) !== null) {
    findings.push({ id: m[0], kind: 'uuid' });
  }

  // Pattern 2 — id-like token after a path segment
  PATH_ID_REGEX.lastIndex = 0;
  while ((m = PATH_ID_REGEX.exec(selector)) !== null) {
    const id = m[1];
    const hasLetterDigitMix = /[A-Za-z]/.test(id) && /[0-9]/.test(id);
    const hasCaseMix = /[A-Z]/.test(id) && /[a-z]/.test(id);
    if (hasLetterDigitMix || hasCaseMix) {
      findings.push({ id, kind: 'path-id' });
    }
  }

  return findings;
}

/**
 * Walk a journey's steps and return an array of static-lint issues.
 * Zero issues = the script is mechanically well-formed and deserves a
 * Playwright dry-run. Non-zero = fail fast without burning a browser.
 *
 * These mirror the Compiler brief's "Pre-write self-check" section —
 * catching these at validator time is the last safety net before we
 * commit a wrong script to capture.
 */
function staticLint(journey) {
  const issues = [];
  const steps = journey.steps || [];
  let safeStartingUrl = null;

  // Required top-level shape checks
  if (!journey.id) issues.push({ idx: -1, kind: 'missing-id', message: 'journey is missing top-level `id`' });
  if (!journey.starting_url) issues.push({ idx: -1, kind: 'missing-starting-url', message: 'journey is missing top-level `starting_url`' });
  if (journey.starting_url) {
    try {
      safeStartingUrl = validateLoopbackUrl(journey.starting_url, 'journey.starting_url');
    } catch (e) {
      issues.push({ idx: -1, kind: 'invalid-starting-url', message: e.message });
    }
  }
  if (!Array.isArray(steps) || steps.length === 0) {
    issues.push({ idx: -1, kind: 'no-steps', message: 'journey has no `steps` array (or it is empty)' });
    return issues;
  }

  // Track duplicate screenshot names
  const screenshotNames = new Map();

  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];

    // Unknown action types
    if (!ALLOWED_ACTIONS.has(s.action)) {
      issues.push({
        idx: i,
        kind: 'unknown-action',
        message: `step ${i} uses unsupported action \`${s.action}\`. Allowed: ${[...ALLOWED_ACTIONS].join(', ')}`,
      });
      continue; // further checks on this step are meaningless
    }

    // type without selector
    if (s.action === 'type' && !s.selector) {
      issues.push({
        idx: i,
        kind: 'type-without-selector',
        message: `step ${i} is \`type\` but has no \`selector\` field. capture_journey.mjs has no implicit-focus fallback — add a selector or delete the step.`,
      });
    }

    // click that looks destructive but has no expect_change
    if (s.action === 'click' && !s.expect_change && looksDestructive(s.selector)) {
      issues.push({
        idx: i,
        kind: 'destructive-click-without-expect-change',
        message: `step ${i} clicks \`${s.selector}\` which looks destructive (matches a verb like publish/save/submit/login/create/generate/delete/...) but has no \`expect_change\` field. Add \`{"kind": "navigation" | "dom" | "any", "timeout_ms": 5000}\` so the capture layer can detect click-did-nothing failures.`,
      });
    }

    // Back-to-back screenshots
    if (s.action === 'screenshot' && i > 0 && steps[i - 1].action === 'screenshot') {
      issues.push({
        idx: i,
        kind: 'back-to-back-screenshot',
        message: `step ${i} is a \`screenshot\` immediately following another \`screenshot\` at step ${i - 1} with no intervening action — delete one; the frame fingerprinting would flag them as identical anyway.`,
      });
    }

    // Duplicate screenshot name within the journey
    if (s.action === 'screenshot' && s.name) {
      if (screenshotNames.has(s.name)) {
        issues.push({
          idx: i,
          kind: 'duplicate-screenshot-name',
          message: `step ${i} reuses \`screenshot.name\` "${s.name}" (first seen at step ${screenshotNames.get(s.name)}). Each name must be unique within the journey.`,
        });
      } else {
        screenshotNames.set(s.name, i);
      }

      // Pre-numbered names are a Compiler bug (the capture script assigns the counter)
      if (/^[0-9]+[-_]/.test(s.name)) {
        issues.push({
          idx: i,
          kind: 'pre-numbered-screenshot-name',
          message: `step ${i} has \`screenshot.name\` "${s.name}" — do not pre-number your names. capture_journey.mjs assigns the 3-digit counter; pre-numbering produces redundant filenames.`,
        });
      }
    }

    // expect_change shape check
    if (s.expect_change) {
      const kind = s.expect_change.kind;
      if (!['navigation', 'dom', 'any'].includes(kind)) {
        issues.push({
          idx: i,
          kind: 'bad-expect-change-kind',
          message: `step ${i} has \`expect_change.kind: ${JSON.stringify(kind)}\` — must be one of "navigation" | "dom" | "any".`,
        });
      }
    }

    // Hardcoded dynamic IDs (nanoid / uuid / database PK) in selectors
    if (s.selector) {
      const idFindings = findHardcodedDynamicIds(s.selector);
      for (const f of idFindings) {
        const idLabel = f.kind === 'uuid' ? 'UUID' : 'dynamic-looking ID';
        issues.push({
          idx: i,
          kind: 'hardcoded-dynamic-id',
          message: `step ${i} selector \`${s.selector}\` contains a hardcoded ${idLabel} \`${f.id}\` — these are typically generated by nanoid/uuid/database PKs and break across seed regenerations. Use a flexible match (e.g. \`a[href^='/recipe/']:not([href='/recipe/new'])\`) or a text-based selector instead.`,
        });
      }
    }

    if (s.action === 'navigate' && s.url && safeStartingUrl) {
      try {
        resolveSameOriginUrl(s.url, safeStartingUrl, `step ${i} url`);
      } catch (e) {
        issues.push({
          idx: i,
          kind: 'disallowed-navigation-url',
          message: e.message,
        });
      }
    }
  }

  return issues;
}

// ──────────────────────────────────────────────────────────────────────
// Per-journey validator
// ──────────────────────────────────────────────────────────────────────

/**
 * The Compiler may use either CSS-style selectors or text= prefixed
 * selectors. Mirror capture_journey.mjs's resolveSelector() exactly so
 * "validates here, breaks there" never happens — if validate uses a
 * different resolution path than capture, the validator's value is
 * gone.
 */
function resolveSelector(page, sel) {
  if (typeof sel !== 'string') return null;
  if (sel.startsWith('text=')) return page.getByText(sel.slice(5), { exact: false }).first();
  return page.locator(sel).first();
}

/**
 * On error, capture a small slice of the live DOM near the failed
 * selector so the Compiler healing prompt can see what the page actually
 * looked like instead of having to re-curl. We deliberately keep this
 * small (~3KB) so the Compiler subagent's input fits comfortably.
 *
 * Strategy: try to find the first ancestor that contains a recognizable
 * label (form, fieldset, section, dialog, [role=region|dialog]). Failing
 * that, fall back to the body's first 3KB.
 */
async function captureDomExcerpt(page, sel) {
  try {
    // Build a heuristic that finds a "context container" near where the
    // selector would have matched. We can't actually locate the missing
    // element (that's why we're here) but we can grab the closest part
    // of the DOM that probably holds it.
    const html = await page.content();
    // Naive: keep first 3000 chars after the first <main>, <form> or
    // <section>; otherwise the head of <body>.
    const lower = html.toLowerCase();
    const candidates = ['<main', '<form', '<section', '<dialog', '<fieldset'];
    let start = -1;
    for (const c of candidates) {
      const idx = lower.indexOf(c);
      if (idx >= 0 && (start < 0 || idx < start)) start = idx;
    }
    if (start < 0) {
      const bodyIdx = lower.indexOf('<body');
      start = bodyIdx >= 0 ? bodyIdx : 0;
    }
    return html.slice(start, start + 3000);
  } catch {
    return '';
  }
}

async function validateJourney(journeyPath) {
  const journey = JSON.parse(readFileSync(journeyPath, 'utf-8'));
  const journeyId = journey.id || basename(journeyPath, '.json');

  // Static lint first — mechanical Compiler bugs don't need a browser.
  // If any static issue is found, skip the Playwright dry-run entirely
  // and return a short-circuit report. The Compiler's healing pass can
  // fix static issues faster than it can fix selector issues because
  // the feedback is deterministic (no "try again, maybe Playwright
  // will resolve it this time" loop).
  const staticIssues = staticLint(journey);
  if (staticIssues.length > 0) {
    const stepReports = [];
    const firstIdx = staticIssues.find((i) => i.idx >= 0)?.idx;
    for (const issue of staticIssues) {
      stepReports.push({
        idx: issue.idx,
        action: issue.idx >= 0 ? (journey.steps[issue.idx]?.action || '?') : 'top-level',
        status: 'error',
        error: `static-lint: ${issue.kind}: ${issue.message}`,
        lint_kind: issue.kind,
      });
    }
    return {
      journey_id: journeyId,
      validated_at: new Date().toISOString(),
      starting_url: safeStartingUrl,
      viewport: journey.viewport || null,
      ok: false,
      first_error_step: firstIdx ?? -1,
      total_steps: (journey.steps || []).length,
      static_lint_only: true,
      steps: stepReports,
    };
  }
  const safeStartingUrl = journey.starting_url
    ? validateLoopbackUrl(journey.starting_url, 'journey.starting_url')
    : journey.starting_url;

  // Pick viewport: CLI flag > journey JSON > desktop default. Same logic
  // as capture_journey.mjs so the validator's environment matches what
  // capture will see.
  let viewport;
  if (viewportArg) viewport = parseViewport(viewportArg);
  else if (journey.viewport && journey.viewport.width)
    viewport = { ...journey.viewport, _name: `${journey.viewport.width}x${journey.viewport.height}` };
  else viewport = parseViewport('desktop');

  const target = await openTarget({
    url: safeStartingUrl,
    viewport,
    // No video, no tracing — this is a dry-run.
  });
  const { page } = target;

  const stepReports = [];
  let firstErrorStep = null;
  // Per-action timeout. Validator uses the SAME 8s click timeout that
  // capture_journey.mjs uses, so a step that passes here is one that
  // capture will also pass. Bumping this would just hide failures.
  const ACTION_TIMEOUT_MS = 8000;

  // Mirror capture_journey.mjs's "always wait for initial paint" behavior
  // so the first step doesn't race against unhydrated React.
  await page.waitForTimeout(800);
  stepReports.push({ idx: 0, action: 'initial-load', status: 'ok' });

  let stepIdx = 0;
  for (const step of journey.steps || []) {
    stepIdx += 1;
    // Skip pure observation actions — they always succeed and never
    // produce useful validation signal.
    if (step.action === 'screenshot' || step.action === 'wait' || step.action === 'scroll') {
      stepReports.push({ idx: stepIdx, action: step.action, status: 'ok' });
      // Honor `wait ms` so subsequent steps see the same DOM state they
      // would in capture mode. Skip selector-based waits — those would
      // need their own validation pass.
      if (step.action === 'wait' && typeof step.ms === 'number') {
        await page.waitForTimeout(Math.min(step.ms, 1500));
      }
      continue;
    }

    const record = { idx: stepIdx, action: step.action, status: 'ok' };
    if (step.selector) record.selector = step.selector;
    if (step.url) record.url = step.url;

    try {
      if (step.action === 'navigate') {
        const url = resolveSameOriginUrl(step.url, safeStartingUrl, `step ${stepIdx} url`);
        await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
        record.url = url;
      } else if (step.action === 'click') {
        const loc = resolveSelector(page, step.selector);
        // visibility check + click. We use waitFor visible to surface
        // "selector matched but element is hidden" cases (e.g. an item
        // inside a collapsed Filters drawer) — those would silently fail
        // capture too.
        await loc.waitFor({ state: 'visible', timeout: ACTION_TIMEOUT_MS });
        await loc.click({ timeout: ACTION_TIMEOUT_MS });
      } else if (step.action === 'type') {
        const loc = resolveSelector(page, step.selector);
        await loc.waitFor({ state: 'visible', timeout: ACTION_TIMEOUT_MS });
        await loc.fill(step.text || '');
        record.text_length = (step.text || '').length;
      } else {
        // Should be unreachable — staticLint() already rejected unknown
        // action types before we got here. Keep the throw so the failure
        // is loud if someone bypasses staticLint.
        throw new Error(`Unknown action type: ${JSON.stringify(step.action)}. Allowed: ${[...ALLOWED_ACTIONS].join(', ')}`);
      }
    } catch (e) {
      record.status = 'error';
      record.error = `${e.name}: ${e.message}`.slice(0, 280);
      record.dom_excerpt = await captureDomExcerpt(page, step.selector);
      firstErrorStep = stepIdx;
      stepReports.push(record);
      // Stop on first error — capture would also stop here, and chasing
      // downstream failures wastes the dev server.
      break;
    }
    stepReports.push(record);
  }

  await closeTarget(target);

  return {
    journey_id: journeyId,
    validated_at: new Date().toISOString(),
    starting_url: safeStartingUrl,
    viewport,
    ok: firstErrorStep === null,
    first_error_step: firstErrorStep,
    total_steps: (journey.steps || []).length,
    steps: stepReports,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Main loop
// ──────────────────────────────────────────────────────────────────────

let okCount = 0;
let failCount = 0;
const summary = [];

for (const fname of journeyFiles) {
  const fullPath = join(scriptsDir, fname);
  const baseName = basename(fname, '.json');
  process.stderr.write(`[validate] ${baseName} … `);
  let report;
  try {
    report = await validateJourney(fullPath);
  } catch (e) {
    report = {
      journey_id: baseName,
      validated_at: new Date().toISOString(),
      ok: false,
      first_error_step: -1,
      total_steps: 0,
      steps: [],
      setup_error: `${e.name}: ${e.message}`.slice(0, 280),
    };
  }
  const outPath = join(scriptsDir, `${baseName}.validation.json`);
  writeFileSync(outPath, JSON.stringify(report, null, 2));
  if (report.ok) {
    okCount += 1;
    console.error('ok');
  } else {
    failCount += 1;
    const where = report.setup_error
      ? `setup-error: ${report.setup_error}`
      : `step ${report.first_error_step}`;
    console.error(`FAIL @ ${where}`);
  }
  summary.push({ id: report.journey_id, ok: report.ok, first_error_step: report.first_error_step });
}

console.error(`[validate] done — ${okCount} ok / ${failCount} fail (of ${journeyFiles.length})`);

// Always exit 0 unless we couldn't even start. The orchestrator inspects
// the per-journey .validation.json files to decide on healing/skip.
process.exit(0);
