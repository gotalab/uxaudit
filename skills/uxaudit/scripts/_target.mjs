/**
 * Shared helpers for uxaudit Node scripts.
 *
 * Resolves a "target" — the thing being audited — into a Playwright
 * browser/context/page tuple. Three target types are supported:
 *
 *   1. Web URL (default)        — `--url http://localhost:3000`
 *   2. Mobile/tablet web        — `--url ... --viewport mobile|tablet|<WxH>`
 *   3. Electron application     — `--electron-app /path/to/main.js` (no --url)
 *
 * Returns: { browser, ctx, page, viewport, mode, kind } where:
 *   - kind   ∈ "web" | "electron"
 *   - mode   = the human-readable preset name (e.g., "mobile", "1024x768")
 *   - viewport = {width, height}
 *
 * Callers must `await close({ browser, ctx, kind })` when done.
 *
 * Why a shared helper: capture.mjs, capture_journey.mjs, and every L2
 * run.mjs need the same target-resolution logic. Centralizing it here
 * means adding a new L2 check is `import { openTarget }` and nothing
 * else needs to know about Electron or viewport presets.
 *
 * Plugin-mode note: we intentionally do NOT set `PLAYWRIGHT_BROWSERS_PATH`
 * here. Chromium binaries live in Playwright's default per-user cache
 * (`~/Library/Caches/ms-playwright/` on macOS) which is shared across every
 * Playwright project on the machine. This means:
 *   - A developer who already has Chromium from another Playwright project
 *     does not pay the ~300 MB download twice.
 *   - `npx playwright install chromium` in the SessionStart hook is a cheap
 *     no-op when the expected version is already present.
 * The cost is that uninstalling the uxaudit plugin does not garbage-collect
 * the Chromium binary — but that's the user's shared resource, not ours,
 * and other Playwright projects on the machine likely depend on it.
 */
import { chromium, _electron as electron } from 'playwright';

// --- Viewport presets ---------------------------------------------------------
//
// Coverage strategy: 6 presets that span the practical device spectrum audit
// authors actually need, without the maintenance burden of tracking every
// model Apple / Samsung ship.
//
//   CSS size    | Preset       | Typical device              | DSF | isMobile
//   ------------|--------------|-----------------------------|-----|---------
//   375 × 667   | mobile-sm    | iPhone SE (2nd/3rd gen)     |  2  | yes
//   390 × 844   | mobile       | iPhone 13/14/15/16          |  3  | yes   (default mobile)
//   820 × 1180  | tablet       | iPad (std), iPad Air        |  2  | yes
//  1024 × 1366  | tablet-pro   | iPad Pro 12.9"              |  2  | yes
//  1440 × 900   | desktop      | MacBook Air/Pro 13"         |  1  | no    (default desktop)
//  1920 × 1080  | desktop-lg   | 1080p external monitor      |  1  | no
//
// Decisions encoded here:
//   - Mobile/tablet presets all set `isMobile: true` — this is what makes
//     Chromium honor `<meta viewport>` so media queries at `max-width: 640px`
//     actually fire. Without it, layout viewport defaults to 980 CSS px even
//     at a declared 390×844 context size (observed during smoke test).
//   - Tablet presets use an **iPad user agent** — the previous version used
//     the default Mac UA which broke any site that branches on `/iPad/` in
//     `navigator.userAgent`.
//   - 4K monitors are omitted: modern OS scaling (macOS Retina, Windows HiDPI
//     150–200 %) renders 4K displays at 1920 × 1080 CSS px or similar, so
//     adding a physical-4K preset would be redundant with `desktop-lg`.
//   - iPhone Pro Max (430 × 932) is omitted: the 40 px delta from `mobile`
//     rarely reveals distinct layout bugs, and users can always specify
//     `--viewport 430x932` when they need it.
//
// Shape: each preset is a flat object with { width, height, dsf?, isMobile?,
// hasTouch?, ua? } so parseViewport + openTarget can treat them uniformly.
// Custom `WxH` inputs produce a preset with just {width, height} and inherit
// desktop-like defaults (DSF=1, no mobile UA).

const IPHONE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 ' +
  '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

const IPAD_UA =
  'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 ' +
  '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

export const VIEWPORT_PRESETS = {
  'mobile-sm':  { width: 375,  height: 667,  dsf: 2, isMobile: true,  hasTouch: true,  ua: IPHONE_UA },
  'mobile':     { width: 390,  height: 844,  dsf: 3, isMobile: true,  hasTouch: true,  ua: IPHONE_UA },
  'tablet':     { width: 820,  height: 1180, dsf: 2, isMobile: true,  hasTouch: true,  ua: IPAD_UA },
  'tablet-pro': { width: 1024, height: 1366, dsf: 2, isMobile: true,  hasTouch: true,  ua: IPAD_UA },
  'desktop':    { width: 1440, height: 900,  dsf: 1, isMobile: false, hasTouch: false },
  'desktop-lg': { width: 1920, height: 1080, dsf: 1, isMobile: false, hasTouch: false },
};

/**
 * Parse `--viewport` flag value into a preset-shaped object.
 *
 *   "mobile-sm" | "mobile" | "tablet" | "tablet-pro" | "desktop" | "desktop-lg"
 *                                    → named preset with UA/DSF/isMobile
 *   "390x844"                        → custom, desktop-like defaults
 *   undefined / null                 → desktop default
 *
 * Returned object always has at least {width, height, _name}. Named presets
 * additionally carry {dsf, isMobile, hasTouch, ua}.
 */
export function parseViewport(value) {
  if (!value) return { ...VIEWPORT_PRESETS.desktop, _name: 'desktop' };
  const v = String(value).toLowerCase().trim();
  if (VIEWPORT_PRESETS[v]) return { ...VIEWPORT_PRESETS[v], _name: v };
  const m = v.match(/^(\d+)\s*x\s*(\d+)$/);
  if (m) {
    return {
      width: parseInt(m[1], 10),
      height: parseInt(m[2], 10),
      _name: `${m[1]}x${m[2]}`,
    };
  }
  // Unknown value — fall back to desktop but warn
  console.error(`[uxaudit] unknown --viewport "${value}", using desktop. ` +
    `Valid presets: ${Object.keys(VIEWPORT_PRESETS).join(', ')} or <WIDTH>x<HEIGHT>`);
  return { ...VIEWPORT_PRESETS.desktop, _name: 'desktop' };
}

/**
 * Pull a flag value out of process.argv (long-form, space-separated).
 *   getArg('viewport') → "mobile" if argv has "--viewport mobile"
 */
export function getArg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1 || i === process.argv.length - 1) return fallback;
  return process.argv[i + 1];
}

export function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

const LOOPBACK_HOSTNAMES = new Set(['localhost', '127.0.0.1', '0.0.0.0', '[::1]']);

function isLoopbackHostname(hostname) {
  return LOOPBACK_HOSTNAMES.has(String(hostname || '').toLowerCase()) ||
    String(hostname || '').toLowerCase().endsWith('.localhost');
}

export function validateLoopbackUrl(rawUrl, label = 'url') {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`${label} must be an absolute URL`);
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error(`${label} must use http:// or https://`);
  }
  if (!isLoopbackHostname(url.hostname)) {
    throw new Error(`${label} must target localhost/loopback`);
  }
  return url.toString();
}

export function resolveSameOriginUrl(rawUrl, startingUrl, label = 'step.url') {
  const base = new URL(validateLoopbackUrl(startingUrl, 'starting_url'));
  let next;
  try {
    next = new URL(rawUrl, base);
  } catch {
    throw new Error(`${label} must be a valid URL or path`);
  }
  if (!['http:', 'https:'].includes(next.protocol)) {
    throw new Error(`${label} must use http:// or https://`);
  }
  if (next.origin !== base.origin) {
    throw new Error(`${label} must stay on the same origin as starting_url`);
  }
  return next.toString();
}

/**
 * Open a target. Options:
 *   - url           : web URL  (mutually exclusive with electronApp)
 *   - electronApp   : path to electron entry (main.js / package dir)
 *   - viewport      : preset name OR "WxH" string OR {width,height}
 *   - recordVideo   : when truthy, record a webm to dir (object with .dir + .size)
 *
 * Returns { browser, ctx, page, viewport, kind }.
 *
 * For Electron, viewport is informational only — Electron windows have their
 * own size set by the app's BrowserWindow constructor. We still capture it
 * in metadata so the dashboard can show "Electron 1280×800 (declared)".
 */
export async function openTarget({ url, electronApp, viewport, recordVideo, coldStart = false } = {}) {
  const vp = (viewport && typeof viewport === 'object' && 'width' in viewport)
    ? viewport
    : parseViewport(viewport);

  if (electronApp) {
    // Electron path. The first BrowserWindow becomes our `page`.
    const app = await electron.launch({ args: [electronApp] });
    const page = await app.firstWindow();
    // Wait for first paint
    try { await page.waitForLoadState('domcontentloaded', { timeout: 15000 }); } catch {}
    return {
      browser: app,        // Playwright's ElectronApplication has .close() like browser
      ctx: null,            // Electron has no separate context
      page,
      viewport: vp,
      kind: 'electron',
    };
  }

  // Web path
  const browser = await chromium.launch();
  const ctxOptions = {
    viewport: { width: vp.width, height: vp.height },
    // Preset fields are applied uniformly. Custom WxH (no preset fields)
    // gets DSF=1 / desktop-like defaults — matching browser DevTools's
    // "Responsive" mode with no device selected.
    deviceScaleFactor: vp.dsf || 1,
    isMobile: vp.isMobile || false,
    hasTouch: vp.hasTouch || false,
  };
  if (vp.ua) ctxOptions.userAgent = vp.ua;
  if (recordVideo) ctxOptions.recordVideo = recordVideo;
  // Cold-start semantics: every new context is already stateless in
  // Playwright (no cookies, no localStorage, no session). The flag adds
  // two things on top:
  //   1. An explicit Cache-Control: no-cache header so the dev server's
  //      HTTP cache can't serve a partially-warmed response from an earlier
  //      audit run.
  //   2. A post-navigate clearBrowserData step that wipes localStorage +
  //      sessionStorage for the starting origin, defending against apps
  //      that persist via `navigator.storage` before we get a chance to
  //      take the first screenshot.
  // The flag is also the intent marker — it surfaces in steps.json so
  // the L4 FTUE Judge can confirm the capture actually ran fresh.
  if (coldStart) {
    ctxOptions.extraHTTPHeaders = {
      ...(ctxOptions.extraHTTPHeaders || {}),
      'Cache-Control': 'no-cache',
    };
  }
  const ctx = await browser.newContext(ctxOptions);
  const page = await ctx.newPage();
  if (url) {
    const safeUrl = validateLoopbackUrl(url);
    try {
      await page.goto(safeUrl, { waitUntil: 'networkidle', timeout: 30000 });
    } catch (e) {
      console.error(`[uxaudit] navigation warning: ${e.message}`);
    }
    if (coldStart) {
      // Best-effort storage wipe. SecurityError on cross-origin is ignored.
      try {
        await page.evaluate(() => {
          try { window.localStorage.clear(); } catch {}
          try { window.sessionStorage.clear(); } catch {}
        });
        await ctx.clearCookies();
      } catch {}
    }
  }
  return { browser, ctx, page, viewport: vp, kind: 'web', coldStart: !!coldStart };
}

/**
 * Symmetric closer for openTarget(). Pass back what openTarget returned.
 */
export async function closeTarget({ browser, ctx, kind }) {
  if (ctx && kind === 'web') {
    try { await ctx.close(); } catch {}
  }
  if (browser) {
    try { await browser.close(); } catch {}
  }
}
