import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type * as PW from 'playwright';

/** Resolve Playwright from the normal module graph, or from
 *  $UXAUDIT_NODE_MODULES (set by the plugin's bin wrapper, which installs
 *  dependencies into the plugin data dir instead of the user's project). */
export async function loadPlaywright(): Promise<typeof PW> {
  try {
    return await import('playwright');
  } catch (first) {
    const dir = process.env.UXAUDIT_NODE_MODULES;
    if (dir) {
      const req = createRequire(join(dir, 'noop.js'));
      // Resolved by path, Playwright loads as CommonJS: the API is on `default`.
      const mod = await import(pathToFileURL(req.resolve('playwright')).href);
      return mod.default ?? mod;
    }
    throw new Error(
      'Playwright is not installed. Run `npm i -D playwright && npx playwright install chromium`, ' +
        'or use the uxaudit Claude Code plugin which installs it on first run.\n' +
        `(${(first as Error).message})`,
    );
  }
}

interface ViewportPreset {
  width: number;
  height: number;
  deviceScaleFactor: number;
  isMobile: boolean;
  hasTouch: boolean;
  userAgent?: string;
}

const IPHONE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const IPAD_UA =
  'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';

// Mobile presets set isMobile so <meta viewport> is honoured; without it the
// page lays out at 980px and mobile media queries never fire.
export const VIEWPORTS: Record<string, ViewportPreset> = {
  'mobile-sm': { width: 375, height: 667, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: IPHONE_UA },
  mobile: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: IPHONE_UA },
  tablet: { width: 820, height: 1180, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: IPAD_UA },
  desktop: { width: 1440, height: 900, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  'desktop-lg': { width: 1920, height: 1080, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
};

export function resolveViewport(spec: string): ViewportPreset {
  const preset = VIEWPORTS[spec];
  if (preset) return preset;
  const m = /^(\d{3,4})x(\d{3,4})$/.exec(spec);
  if (!m) throw new Error(`unknown viewport "${spec}" (use ${Object.keys(VIEWPORTS).join(', ')} or WIDTHxHEIGHT)`);
  return { width: Number(m[1]), height: Number(m[2]), deviceScaleFactor: 1, isMobile: false, hasTouch: false };
}

const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

/** Journeys are drafted by an agent from repository content, so by default
 *  the browser may only reach a local dev server. */
export function checkBaseUrl(raw: string, allowRemote: boolean): URL {
  const url = new URL(raw);
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error(`app.url must be http(s): ${raw}`);
  const local = LOOPBACK.has(url.hostname) || url.hostname.endsWith('.localhost') || url.hostname.endsWith('.test');
  if (!local && !allowRemote) {
    throw new Error(`app.url ${url.origin} is not a local dev server. Pass --allow-remote to audit it anyway.`);
  }
  return url;
}

export function sameOrigin(path: string, base: URL): string {
  const next = new URL(path, base);
  if (next.origin !== base.origin) throw new Error(`goto must stay on ${base.origin}: ${path}`);
  return next.toString();
}
