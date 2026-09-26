import { spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { judgeBrief } from './brief.ts';
import { checkBaseUrl } from './browser.ts';
import { captureJourney, recordSession, signIn } from './capture.ts';
import { envRefs, loadEnv, resolveEnv } from './env.ts';
import { artifactFiles, buildReportData, fixList, renderReport } from './report.ts';
import type { RunManifest } from './schema.ts';
import { HOME, latestRun, loadConfig, loadTriage, loadVerdicts, mergeTriage, previousKeys, readManifest } from './store.ts';
import { TEMPLATE } from './template.ts';

const HELP = `uxaudit — replay key user journeys, judge them from screenshots, triage in one report

Usage:
  uxaudit init [--url URL]              Create .uxaudit/journeys.yaml
  uxaudit run [options]                 Capture every journey (screenshots + signals)
      --url URL                         Override app.url
      --only a,b                        Only these journey ids
      --viewport NAME|WxH               Override viewport for all journeys
      --allow-remote                    Allow a non-local app.url
      --headed                          Show the browser
  uxaudit auth record NAME              Sign in by hand (OAuth, passkey, 2FA…) and save the session
  uxaudit brief [RUN] [--journey ID]    Print the judge prompt (all journeys if no --journey)
  uxaudit validate [RUN]                Check verdicts/*.json; exit 1 on problems
  uxaudit report [RUN] [--artifact]     Write report.html (and report.artifact.html)
  uxaudit fixes [RUN]                   Print the fix list as Markdown
  uxaudit triage import FILE|DIR|-      Merge triage (triage.json, {id: item} JSON, or a dir of <id>.json)

RUN defaults to the latest run under .uxaudit/runs. Use --home DIR to change .uxaudit.
`;

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      home: { type: 'string', default: HOME },
      url: { type: 'string' },
      only: { type: 'string' },
      viewport: { type: 'string' },
      journey: { type: 'string' },
      'allow-remote': { type: 'boolean', default: false },
      headed: { type: 'boolean', default: false },
      artifact: { type: 'boolean', default: false },
      help: { type: 'boolean', short: 'h', default: false },
    },
  });
  const [cmd, ...rest] = positionals;
  const home = resolve(values.home!);
  const cwd = process.cwd();
  const runDir = () => (rest[0] ? resolve(rest[0]) : latestRun(home));

  switch (values.help ? 'help' : cmd) {
    case 'init': {
      const path = join(home, 'journeys.yaml');
      if (existsSync(path)) throw new Error(`${relative(cwd, path)} already exists`);
      mkdirSync(home, { recursive: true });
      writeFileSync(path, TEMPLATE.replace('http://localhost:3000', values.url ?? 'http://localhost:3000'));
      writeFileSync(join(home, '.gitignore'), 'runs/\n.env\n.auth/\n');
      console.log(`Created ${relative(cwd, path)}. Replace the example journey with your product's own.`);
      return;
    }

    case 'run': {
      const config = loadConfig(join(home, 'journeys.yaml'));
      const env = loadEnv(home);
      const root = resolve(home, '..');
      const base = checkBaseUrl(resolveEnv(values.url ?? config.app.url, env), values['allow-remote']!);
      const only = values.only?.split(',').map((s) => s.trim());
      const journeys = only ? config.journeys.filter((j) => only.includes(j.id)) : config.journeys;
      if (!journeys.length) throw new Error(`no journeys match --only ${values.only}`);
      const authNames = [...new Set(journeys.flatMap((j) => (j.auth ? [j.auth] : [])))];

      // Fail before touching the browser if a secret is missing.
      const missing = [...new Set(envRefs([journeys, authNames.map((n) => config.auth[n])]))].filter((n) => env[n] === undefined);
      if (missing.length) {
        throw new Error(`missing environment variables: ${missing.join(', ')} (export them or add them to ${relative(cwd, join(home, '.env'))})`);
      }

      const runId = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const dir = join(home, 'runs', runId);
      mkdirSync(join(dir, 'verdicts'), { recursive: true });
      const manifest: RunManifest = {
        version: 1,
        runId,
        createdAt: new Date().toISOString(),
        app: { name: config.app.name, url: base.toString(), lang: config.app.lang },
        journeys: [],
      };
      const browserOpts = {
        base,
        locale: config.app.lang === 'ja' ? 'ja-JP' : 'en-US',
        env,
        headed: values.headed,
      };

      if (config.setup) runCommand('setup', config.setup.command, root, env);
      // Sessions hold live cookies: keep them out of the run dir (which CI may
      // upload) and delete them when the run ends.
      const authDir = mkdtempSync(join(tmpdir(), 'uxaudit-auth-'));
      try {
        const sessions: Record<string, string> = {};
        for (const name of authNames) {
          const entry = config.auth[name]!;
          const failShot = join(dir, `auth-${name}-failed.jpg`);
          const viewport = config.app.viewport;
          if ('recorded' in entry) {
            const saved = sessionPath(home, name);
            if (!existsSync(saved)) throw new Error(`no recorded session for "${name}". Run: uxaudit auth record ${name}`);
            process.stderr.write(`▸ check recorded session "${name}" … `);
            try {
              await signIn(entry.check, { ...browserOpts, viewport, storageState: saved, failShot });
            } catch (e) {
              process.stderr.write('failed\n');
              throw new Error(
                `the recorded session "${name}" no longer works (${(e as Error).message}). ` +
                  `Sign in again with: uxaudit auth record ${name}. Last screen: ${relative(cwd, failShot)}`,
              );
            }
            sessions[name] = saved;
          } else {
            process.stderr.write(`▸ sign in as ${name} … `);
            const statePath = join(authDir, `${name}.json`);
            try {
              await signIn(entry.steps, { ...browserOpts, viewport, statePath, failShot });
            } catch (e) {
              process.stderr.write('failed\n');
              throw new Error(`sign-in "${name}" ${(e as Error).message}. Last screen: ${relative(cwd, failShot)}`);
            }
            sessions[name] = statePath;
          }
          process.stderr.write('ok\n');
        }

        for (const j of journeys) {
          if (j.before) runCommand(j.id, j.before, root, env);
          const viewport = values.viewport ?? j.viewport ?? config.app.viewport;
          process.stderr.write(`▸ ${j.id} (${viewport}${j.auth ? `, as ${j.auth}` : ''}) … `);
          const capture = await captureJourney(j, {
            ...browserOpts,
            viewport,
            outDir: join(dir, j.id),
            storageState: j.auth ? sessions[j.auth] : undefined,
          });
          const last = capture.steps.at(-1)!;
          process.stderr.write(
            capture.status === 'completed'
              ? `${capture.steps.length} steps\n`
              : `blocked at step ${last.index} (${last.label}): ${last.error}\n`,
          );
          manifest.journeys.push({ id: j.id, title: j.title, focus: j.focus, goal: j.goal, expect: j.expect, auth: j.auth, capture });
        }
      } finally {
        rmSync(authDir, { recursive: true, force: true });
      }
      writeFileSync(join(dir, 'run.json'), JSON.stringify(manifest, null, 2));
      const rel = relative(cwd, dir);
      console.log(`\nCaptured ${manifest.journeys.length} journey(s) → ${rel}`);
      console.log(`Next: judge each journey (uxaudit brief ${rel} --journey <id>), then uxaudit report ${rel}`);
      return;
    }

    case 'auth': {
      const name = rest[1];
      if (rest[0] !== 'record' || !name) throw new Error('usage: uxaudit auth record NAME');
      const config = loadConfig(join(home, 'journeys.yaml'));
      const entry = config.auth[name];
      if (!entry || !('recorded' in entry)) {
        throw new Error(
          `add a recorded auth entry to journeys.yaml first:\n\nauth:\n  ${name}:\n    recorded: true\n    check:            # proves the session still works\n      - goto: /\n      - see: <text only a signed-in user sees>\n`,
        );
      }
      const env = loadEnv(home);
      const base = checkBaseUrl(resolveEnv(values.url ?? config.app.url, env), values['allow-remote']!);
      const statePath = sessionPath(home, name);
      mkdirSync(join(home, '.auth'), { recursive: true });
      ensureIgnored(home, '.auth/');
      console.error(`A browser is opening at ${base.origin}. Sign in as "${name}" the way a user would (Google, passkey, 2FA…).`);
      console.error('Use a test account, not your personal one. Then come back here and press Enter.');
      await recordSession({
        base,
        viewport: config.app.viewport,
        locale: config.app.lang === 'ja' ? 'ja-JP' : 'en-US',
        env,
        headed: true,
        statePath,
        waitForUser: () => waitForEnter(),
      });
      // Live session cookies: readable by this user only, never committed.
      chmodSync(statePath, 0o600);
      console.log(`Saved the session to ${relative(cwd, statePath)} (git-ignored). Journeys with auth: ${name} will reuse it.`);
      return;
    }

    case 'brief': {
      const dir = runDir();
      const run = readManifest(dir);
      const triage = loadTriage(home);
      const ids = values.journey ? [values.journey] : run.journeys.map((j) => j.id);
      console.log(ids.map((id) => judgeBrief(run, dir, id, triage, previousKeys(dir, id))).join('\n---\n\n'));
      return;
    }

    case 'validate': {
      const dir = runDir();
      const { verdicts, problems } = loadVerdicts(dir, readManifest(dir));
      if (problems.length) {
        console.error(`Verdict problems:\n${problems.map((p) => `- ${p}`).join('\n')}`);
        process.exitCode = 1;
      } else {
        console.log(`All ${Object.keys(verdicts).length} verdict(s) are valid.`);
      }
      return;
    }

    case 'report': {
      const dir = runDir();
      const run = readManifest(dir);
      const { verdicts, problems } = loadVerdicts(dir, run);
      for (const p of problems) console.error(`warning: ${p}`);
      const data = buildReportData(dir, run, verdicts, loadTriage(home));
      const out = join(dir, 'report.html');
      writeFileSync(out, renderReport(data, false));
      console.log(relative(cwd, out));
      if (values.artifact) {
        const art = join(dir, 'report.artifact.html');
        writeFileSync(art, renderReport(data, true));
        console.log(relative(cwd, art));
        // Videos are too large to inline; publish them as files next to the page.
        console.log(`artifact files: ${JSON.stringify(artifactFiles(dir, data))}`);
      }
      return;
    }

    case 'fixes': {
      const dir = runDir();
      const run = readManifest(dir);
      const { verdicts } = loadVerdicts(dir, run);
      process.stdout.write(fixList(buildReportData(dir, run, verdicts, loadTriage(home))));
      return;
    }

    case 'triage': {
      if (rest[0] !== 'import' || !rest[1]) throw new Error('usage: uxaudit triage import FILE|DIR|-');
      const src = rest[1];
      let items: Record<string, unknown>;
      if (src !== '-' && statSync(src).isDirectory()) {
        // One <finding id>.json per document, as an artifact database export writes them.
        items = Object.fromEntries(
          readdirSync(src)
            .filter((f) => f.endsWith('.json'))
            .map((f) => [f.slice(0, -5), JSON.parse(readFileSync(join(src, f), 'utf8'))]),
        );
      } else {
        const raw = JSON.parse(src === '-' ? readFileSync(0, 'utf8') : readFileSync(src, 'utf8'));
        // Accept a triage.json ({version, items}) or a bare {id: item} map.
        items = raw && typeof raw === 'object' && 'items' in raw ? raw.items : raw;
      }
      mkdirSync(home, { recursive: true });
      const { added, updated } = mergeTriage(home, items);
      console.log(`triage.json: ${added} added, ${updated} updated`);
      return;
    }

    case 'help':
    case undefined:
      console.log(HELP);
      return;

    default:
      throw new Error(`unknown command "${cmd}"\n\n${HELP}`);
  }
}

const sessionPath = (home: string, name: string) => join(home, '.auth', `${name}.json`);

function ensureIgnored(home: string, entry: string) {
  const file = join(home, '.gitignore');
  const lines = existsSync(file) ? readFileSync(file, 'utf8').split('\n') : [];
  if (!lines.includes(entry)) writeFileSync(file, [...lines.filter(Boolean), entry, ''].join('\n'));
}

function waitForEnter(): Promise<void> {
  return new Promise((done) => {
    process.stdin.resume();
    process.stdin.once('data', () => {
      process.stdin.pause();
      done();
    });
  });
}

/** Run a journeys.yaml command from the project root; its output goes to
 *  stderr so stdout stays machine-readable. */
function runCommand(label: string, command: string, cwd: string, env: Record<string, string>) {
  process.stderr.write(`▸ ${label}: $ ${command}\n`);
  const res = spawnSync(command, { shell: true, cwd, env, stdio: ['ignore', 2, 2] });
  if (res.status !== 0) throw new Error(`command failed (exit ${res.status ?? res.signal}): ${command}`);
}

main().catch((e: Error) => {
  console.error(`uxaudit: ${e.message}`);
  process.exit(1);
});
