#!/usr/bin/env node
/**
 * Capture a target: rendered HTML, computed styles, screenshots, all CSS.
 *
 * Usage:
 *   node capture.mjs <url> <output-dir> [--viewport mobile|tablet|desktop|WxH]
 *   node capture.mjs --electron-app <path> <output-dir>
 *
 * Output structure:
 *   <output-dir>/
 *   ├── rendered.html        ← full DOM after JS execution
 *   ├── visible-text.txt     ← user-visible text only
 *   ├── computed-styles.json ← computed styles for sampled elements
 *   ├── stylesheets.css      ← all CSS concatenated
 *   ├── screenshot.png       ← full-page screenshot
 *   ├── viewport.png         ← initial viewport screenshot
 *   └── meta.json            ← URL, timestamp, viewport, target kind
 *
 * Requires: playwright (auto-installs)
 */
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { openTarget, closeTarget, getArg } from './_target.mjs';

// Argument parsing. Accepts:
//   capture.mjs <url> <outDir> [--viewport ...]
//   capture.mjs --electron-app <path> <outDir>
// We strip every `--flag value` pair from argv first, then treat the
// remaining tokens as positional. This avoids brittle index math.
const FLAGS_WITH_VALUE = new Set(['viewport', 'electron-app']);
const argv = process.argv.slice(2);
const positional = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    const name = a.slice(2);
    if (FLAGS_WITH_VALUE.has(name)) i++; // consume value
    continue;
  }
  positional.push(a);
}
const electronApp = getArg('electron-app');
const viewportArg = getArg('viewport');
const url = electronApp ? null : positional[0];
const outDir = electronApp ? positional[0] : positional[1];

if (!outDir || (!url && !electronApp)) {
  console.error('Usage:');
  console.error('  node capture.mjs <url> <output-dir> [--viewport mobile|tablet|desktop|WxH]');
  console.error('  node capture.mjs --electron-app <path> <output-dir>');
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

console.error(electronApp
  ? `[capture] launching electron app: ${electronApp}`
  : `[capture] navigating to ${url} (viewport=${viewportArg || 'desktop'})`);

const target = await openTarget({ url, electronApp, viewport: viewportArg });
const { page, viewport, kind } = target;

// Wait a bit more for SPA / electron hydration
await page.waitForTimeout(1500);

// 1. Rendered HTML
const html = await page.content();
writeFileSync(join(outDir, 'rendered.html'), html);

// 2. Visible text only (what a user actually sees)
const visibleText = await page.evaluate(() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const parts = [];
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentElement;
    if (!parent) continue;
    const style = window.getComputedStyle(parent);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') continue;
    const text = node.textContent.trim();
    if (text) parts.push(text);
  }
  return parts.join('\n');
});
writeFileSync(join(outDir, 'visible-text.txt'), visibleText);

// 3. Computed styles for representative elements
const computedStyles = await page.evaluate(() => {
  const props = [
    'background', 'background-image', 'background-color',
    'color', 'font-family', 'font-size', 'font-weight',
    'box-shadow', 'border-radius', 'border',
    'padding', 'margin',
  ];
  const samples = {};
  const selectors = ['body', 'main', 'nav', 'header', 'footer', 'h1', 'h2', 'button', '[class*="card"]', '[class*="hero"]'];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const styles = {};
    const computed = window.getComputedStyle(el);
    for (const prop of props) {
      styles[prop] = computed.getPropertyValue(prop);
    }
    samples[sel] = styles;
  }
  return samples;
});
writeFileSync(join(outDir, 'computed-styles.json'), JSON.stringify(computedStyles, null, 2));

// 4. All CSS (resolved)
const allCss = await page.evaluate(() => {
  const out = [];
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) {
        out.push(rule.cssText);
      }
    } catch (e) {
      // Cross-origin stylesheet — skip
    }
  }
  return out.join('\n');
});
writeFileSync(join(outDir, 'stylesheets.css'), allCss);

// 5. Screenshots
await page.screenshot({ path: join(outDir, 'viewport.png'), fullPage: false });
await page.screenshot({ path: join(outDir, 'screenshot.png'), fullPage: true });

// 6. Meta — record viewport + kind so downstream tools (and the dashboard)
// can show "captured at iPhone 13 size" or "Electron app".
const meta = {
  url: url || null,
  electron_app: electronApp || null,
  kind,                                    // "web" | "electron"
  captured_at: new Date().toISOString(),
  viewport: { width: viewport.width, height: viewport.height, preset: viewport._name || null },
  title: await page.title().catch(() => ''),
};
writeFileSync(join(outDir, 'meta.json'), JSON.stringify(meta, null, 2));

console.error(`[capture] done → ${outDir}`);
await closeTarget(target);
