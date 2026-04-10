#!/usr/bin/env node
/**
 * Run axe-core against a URL and write a result.json compatible with uxaudit.
 *
 * Usage:
 *   node run.mjs --url <url> --output <result.json> --manifest <check.json>
 */
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { createRequire } from 'module';
import { openTarget, closeTarget, getArg } from '../../../scripts/_target.mjs';

const url = getArg('url');
const outputPath = getArg('output');
const manifestPath = getArg('manifest');
const viewportArg = getArg('viewport');
const electronApp = getArg('electron-app');

if ((!url && !electronApp) || !outputPath || !manifestPath) {
  console.error('Usage: run.mjs --url <url> --output <result.json> --manifest <check.json> [--viewport mobile|...] [--electron-app PATH]');
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));

function writeResult(data) {
  // Verdict-shaped result.json. Catalog metadata (name/band/subtype/method/
  // severity/source/rationale/pass_criteria) is joined in by aggregate.py
  // from check.json, and `category` is derived from check_id. So we only
  // write the verdict side here.
  mkdirSync(dirname(outputPath), { recursive: true });
  const out = {
    check_id: manifest.id,
    ...data,
  };
  writeFileSync(outputPath, JSON.stringify(out, null, 2));
}

function loadAxeSource() {
  const require = createRequire(import.meta.url);
  const axeSourcePath = require.resolve('axe-core/axe.min.js');
  return readFileSync(axeSourcePath, 'utf-8');
}

let axeSource = '';
try {
  axeSource = loadAxeSource();
} catch (e) {
  writeResult({
    result: 'error',
    evidence: {
      details: `Local axe-core dependency is unavailable: ${e.message}`,
      matches: [],
      files: [],
    },
    suggestion: 'Run `npm install` in `skills/uxaudit` or let the plugin dependency bootstrap complete, then re-run the audit.',
  });
  process.exit(0);
}

const target = await openTarget({ url, electronApp, viewport: viewportArg });
const { page } = target;

await page.waitForTimeout(1500);

// Inject axe-core from the local dependency bundle so audits stay offline.
try {
  await page.addScriptTag({
    content: axeSource,
  });
} catch (e) {
  writeResult({
    result: 'error',
    evidence: { details: `Failed to load axe-core: ${e.message}`, matches: [], files: [] },
    suggestion: '',
  });
  await closeTarget(target);
  process.exit(0);
}

const results = await page.evaluate(async () => {
  // @ts-ignore
  return await axe.run();
});

await closeTarget(target);

const violations = results.violations || [];
const serious = violations.filter(v => v.impact === 'serious' || v.impact === 'critical');
const moderate = violations.filter(v => v.impact === 'moderate');
const minor = violations.filter(v => v.impact === 'minor');

const matches = violations.slice(0, 30).map(v => ({
  id: v.id,
  impact: v.impact,
  description: v.description,
  help: v.help,
  helpUrl: v.helpUrl,
  nodes: v.nodes.length,
  sample_target: v.nodes[0]?.target?.[0] || '',
}));

const total = violations.length;
const passResult = serious.length === 0;

const summary = (
  `${total} violation(s): ${serious.length} serious/critical, ${moderate.length} moderate, ${minor.length} minor.`
);

const suggestion = passResult
  ? (total === 0
      ? ''
      : `Address moderate/minor accessibility issues when convenient. Top items: ${matches.slice(0, 3).map(m => m.id).join(', ')}.`)
  : (
      `Fix all serious/critical accessibility violations. Top items: ${serious.slice(0, 5).map(v => `${v.id} (${v.nodes.length} occurrences)`).join('; ')}. ` +
      `Each is detailed at the helpUrl in the matches.`
    );

writeResult({
  result: passResult ? (total === 0 ? 'pass' : 'pass') : 'fail',
  evidence: {
    details: summary,
    matches,
    files: [],
    counts: {
      total,
      serious: serious.length,
      moderate: moderate.length,
      minor: minor.length,
    },
  },
  suggestion,
});
