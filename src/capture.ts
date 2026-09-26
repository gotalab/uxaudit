import { createHash } from 'node:crypto';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Locator, Page } from 'playwright';
import { loadPlaywright, resolveViewport, sameOrigin } from './browser.ts';
import { resolveEnv } from './env.ts';
import { annotate, ripple, SCREENSHOT_STYLE, type Point } from './overlay.ts';
import type { Journey, JourneyCapture, Step, StepRecord, StepSignals, Target } from './schema.ts';

const ACTION_TIMEOUT = 5_000;
const SLOW_MS = 3_000;
/** When to look again after an action, before the page settles. Catches
 *  toasts, spinners and transitions that are gone by the final screenshot. */
const TRANSIENT_AT_MS = [100, 600];
const VIDEO_MAX_WIDTH = 1280;

export interface BrowserOptions {
  base: URL;
  viewport: string;
  locale: string;
  env: Record<string, string>;
  headed?: boolean;
}

export interface CaptureOptions extends BrowserOptions {
  outDir: string;
  /** Session saved by signIn(); the journey starts signed in. */
  storageState?: string;
}

function contextOptions(vp: ReturnType<typeof resolveViewport>, opts: BrowserOptions) {
  return {
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.deviceScaleFactor,
    isMobile: vp.isMobile,
    hasTouch: vp.hasTouch,
    userAgent: vp.userAgent,
    // Fixed locale/timezone so reruns render the same text.
    locale: opts.locale,
    timezoneId: 'UTC',
  };
}

/** Run setup steps (an `auth` entry's sign-in, or the `check` of a recorded
 *  session) and optionally save the resulting session to `statePath`.
 *  Not recorded or judged: signing in is setup, not the journey under test.
 *  On failure the last screen is saved to `failShot` for debugging. */
export async function signIn(
  steps: Step[],
  opts: BrowserOptions & { statePath?: string; storageState?: string; failShot: string },
) {
  const { chromium } = await loadPlaywright();
  const vp = resolveViewport(opts.viewport);
  const browser = await chromium.launch({ headless: !opts.headed });
  try {
    const context = await browser.newContext({ ...contextOptions(vp, opts), storageState: opts.storageState });
    const page = await context.newPage();
    page.setDefaultTimeout(ACTION_TIMEOUT);
    if (!('goto' in steps[0]!)) await page.goto(opts.base.toString());
    for (const [i, step] of steps.entries()) {
      try {
        const target = targetOf(step);
        await runStep(page, step, opts.base, target ? locate(page, target) : undefined, opts.env);
        await settle(page);
      } catch (e) {
        writeFileSync(opts.failShot, await snap(page));
        throw new Error(`step ${i + 1} (${describe(step)}) failed: ${(e as Error).message.split('\n')[0]}`);
      }
    }
    if (opts.statePath) await context.storageState({ path: opts.statePath });
  } finally {
    await browser.close();
  }
}

/** Open a visible browser for a person to sign in by hand (any method:
 *  OAuth, passkey, 2FA, magic link), then save the session. `waitForUser`
 *  resolves when they are done. */
export async function recordSession(opts: BrowserOptions & { statePath: string; waitForUser: (page: Page) => Promise<void> }) {
  const { chromium } = await loadPlaywright();
  const vp = resolveViewport(opts.viewport);
  const browser = await chromium.launch({ headless: !opts.headed });
  try {
    const context = await browser.newContext(contextOptions(vp, opts));
    const page = await context.newPage();
    let closed = false;
    browser.on('disconnected', () => (closed = true));
    await page.goto(opts.base.toString());
    await opts.waitForUser(page);
    if (closed) throw new Error('the browser was closed before the session was saved');
    await context.storageState({ path: opts.statePath });
  } finally {
    await browser.close().catch(() => {});
  }
}

export async function captureJourney(journey: Journey, opts: CaptureOptions): Promise<JourneyCapture> {
  const { chromium } = await loadPlaywright();
  const vp = resolveViewport(opts.viewport);
  const browser = await chromium.launch({ headless: !opts.headed });
  const context = await browser.newContext({
    ...contextOptions(vp, opts),
    storageState: opts.storageState,
    recordVideo: { dir: join(opts.outDir, '.video'), size: videoSize(vp.width, vp.height) },
  });
  mkdirSync(opts.outDir, { recursive: true });
  const page = await context.newPage();
  const videoStart = Date.now();
  page.setDefaultTimeout(ACTION_TIMEOUT);

  let pending: StepSignals = emptySignals();
  page.on('console', (msg) => {
    if (msg.type() === 'error') pending.consoleErrors.push(msg.text().slice(0, 300));
  });
  page.on('pageerror', (err) => pending.consoleErrors.push(String(err.message).slice(0, 300)));
  page.on('response', (res) => {
    if (res.status() >= 400) pending.httpErrors.push({ status: res.status(), url: res.url() });
  });

  const records: StepRecord[] = [];
  let status: JourneyCapture['status'] = 'completed';
  let prevHash = '';
  let prevUrl = '';
  let cursor: Point = { x: vp.width / 2, y: vp.height / 2 };

  // Every journey starts from the app root unless its first step navigates.
  if (!('goto' in journey.steps[0]!)) {
    await page.goto(opts.base.toString());
    await settle(page);
  }

  for (const [i, step] of journey.steps.entries()) {
    const index = i + 1;
    // Intent-neutral file names so the judge is not primed by the script.
    const shot = `${String(index).padStart(2, '0')}.jpg`;
    const label = describe(step);
    const target = targetOf(step);
    const loc = target ? locate(page, target) : undefined;
    const annotatedAt = Date.now();
    cursor = await annotate(page, index, label, loc, cursor);
    // Timed from here so the annotation pause doesn't count as app latency.
    const started = Date.now();
    let error: string | undefined;
    const early: { buf: Buffer; afterMs: number }[] = [];
    try {
      await runStep(page, step, opts.base, loc, opts.env);
      if ('click' in step) await ripple(page, cursor);
      if (changesScreen(step)) {
        const acted = Date.now();
        for (const at of TRANSIENT_AT_MS) {
          await page.waitForTimeout(Math.max(0, at - (Date.now() - acted)));
          early.push({ buf: await snap(page), afterMs: Date.now() - acted });
        }
      }
      await settle(page);
    } catch (e) {
      error = (e as Error).message.split('\n')[0]!.slice(0, 300);
    }
    const durationMs = Date.now() - started;
    const buf = await snap(page);
    writeFileSync(join(opts.outDir, shot), buf);
    const hash = sha1(buf);

    // Keep only in-between frames that show something neither the previous
    // nor the final screen shows.
    const frames: StepRecord['frames'] = [];
    const seen = new Set([prevHash, hash]);
    for (const f of early) {
      const h = sha1(f.buf);
      if (seen.has(h)) continue;
      seen.add(h);
      const file = `${String(index).padStart(2, '0')}-${frames.length + 1}.jpg`;
      writeFileSync(join(opts.outDir, file), f.buf);
      frames.push({ file, afterMs: f.afterMs });
    }

    const signals = pending;
    pending = emptySignals();
    signals.slow = durationMs > SLOW_MS;
    // Compare with the configured width: mobile emulation widens innerWidth
    // to fit overflowing content, which would hide the overflow.
    signals.horizontalOverflow = await page
      .evaluate((w) => document.documentElement.scrollWidth > w + 1, vp.width)
      .catch(() => false);

    const acts = 'click' in step || 'press' in step;
    const unchanged = acts && !error && hash === prevHash && !frames.length && page.url() === prevUrl;
    records.push({
      index,
      label,
      note: step.note,
      status: error ? 'failed' : unchanged ? 'no-change' : 'ok',
      error,
      url: page.url(),
      atMs: annotatedAt - videoStart,
      durationMs,
      frames,
      shot,
      signals,
    });
    prevHash = hash;
    prevUrl = page.url();
    if (error) {
      status = 'blocked';
      break;
    }
  }

  // The recording is finalised only once the context closes.
  const video = page.video();
  await context.close();
  let videoFile: string | undefined;
  if (video) {
    await video.saveAs(join(opts.outDir, 'journey.webm'));
    videoFile = `${journey.id}/journey.webm`;
  }
  rmSync(join(opts.outDir, '.video'), { recursive: true, force: true });
  await browser.close();
  const capture: JourneyCapture = { id: journey.id, status, viewport: opts.viewport, video: videoFile, steps: records };
  writeFileSync(join(opts.outDir, 'steps.json'), JSON.stringify(capture, null, 2));
  return capture;
}

const snap = (page: Page) => page.screenshot({ type: 'jpeg', quality: 72, style: SCREENSHOT_STYLE });

const sha1 = (buf: Buffer) => createHash('sha1').update(buf).digest('hex');

function videoSize(width: number, height: number) {
  const scale = Math.min(1, VIDEO_MAX_WIDTH / width);
  // Video encoders want even dimensions.
  const even = (n: number) => Math.round((n * scale) / 2) * 2;
  return { width: even(width), height: even(height) };
}

/** Steps after which the screen may pass through short-lived states. */
function changesScreen(step: Step): boolean {
  return ['goto', 'click', 'press', 'select', 'check', 'reload', 'back'].some((k) => k in step);
}

function emptySignals(): StepSignals {
  return { consoleErrors: [], httpErrors: [], slow: false, horizontalOverflow: false };
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 3_000 }).catch(() => {});
  await page.waitForTimeout(250);
}

function locate(page: Page, t: Target): Locator {
  if (typeof t === 'string') {
    return page
      .getByRole('button', { name: t })
      .or(page.getByRole('link', { name: t }))
      .or(page.getByLabel(t))
      .or(page.getByPlaceholder(t))
      .or(page.getByText(t))
      .first();
  }
  if ('role' in t) return page.getByRole(t.role as Parameters<Page['getByRole']>[0], { name: t.name }).first();
  if ('label' in t) return page.getByLabel(t.label).first();
  if ('text' in t) return page.getByText(t.text).first();
  if ('placeholder' in t) return page.getByPlaceholder(t.placeholder).first();
  if ('testId' in t) return page.getByTestId(t.testId).first();
  return page.locator(t.css).first();
}

/** The element a step acts on, if any. */
function targetOf(step: Step): Target | undefined {
  if ('click' in step) return step.click;
  if ('fill' in step) return step.fill.target;
  if ('select' in step) return step.select.target;
  if ('check' in step) return step.check;
  if ('hover' in step) return step.hover;
  if ('press' in step && typeof step.press !== 'string') return step.press.target;
  if ('scroll' in step && step.scroll !== 'top' && step.scroll !== 'bottom') return step.scroll;
  return undefined;
}

/** `loc` is the locator for targetOf(step), resolved once by the caller. */
async function runStep(page: Page, step: Step, base: URL, loc: Locator | undefined, env: Record<string, string>) {
  if ('goto' in step) await page.goto(sameOrigin(resolveEnv(step.goto, env), base));
  else if ('click' in step) await loc!.click();
  else if ('fill' in step) await loc!.fill(resolveEnv(step.fill.value, env));
  else if ('select' in step) await loc!.selectOption(resolveEnv(step.select.value, env));
  else if ('check' in step) await loc!.check();
  else if ('hover' in step) await loc!.hover();
  else if ('press' in step) {
    if (typeof step.press === 'string') await page.keyboard.press(step.press);
    else await loc!.press(step.press.key);
  } else if ('see' in step) await page.getByText(step.see).first().waitFor({ state: 'visible' });
  else if ('wait' in step) await page.waitForTimeout(step.wait);
  else if ('scroll' in step) {
    if (step.scroll === 'top') await page.evaluate(() => window.scrollTo(0, 0));
    else if (step.scroll === 'bottom') await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    else await loc!.scrollIntoViewIfNeeded();
  } else if ('reload' in step) await page.reload();
  else if ('back' in step) await page.goBack();
}

const targetText = (t: Target) =>
  typeof t === 'string' ? `"${t}"` : `${Object.keys(t)[0]}=${JSON.stringify(Object.values(t).join(' '))}`;

export function describe(step: Step): string {
  if ('goto' in step) return `open ${step.goto}`;
  if ('click' in step) return `click ${targetText(step.click)}`;
  if ('fill' in step) return `type ${JSON.stringify(step.fill.value)} into ${targetText(step.fill.target)}`;
  if ('select' in step) return `choose ${JSON.stringify(step.select.value)} in ${targetText(step.select.target)}`;
  if ('check' in step) return `check ${targetText(step.check)}`;
  if ('hover' in step) return `hover ${targetText(step.hover)}`;
  if ('press' in step) return typeof step.press === 'string' ? `press ${step.press}` : `press ${step.press.key} in ${targetText(step.press.target)}`;
  if ('see' in step) return `expect to see "${step.see}"`;
  if ('wait' in step) return `wait ${step.wait}ms`;
  if ('scroll' in step) return `scroll to ${typeof step.scroll === 'string' && ['top', 'bottom'].includes(step.scroll) ? step.scroll : targetText(step.scroll)}`;
  if ('reload' in step) return 'reload the page';
  return 'go back';
}
