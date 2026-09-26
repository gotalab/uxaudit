import { z } from 'zod';

// ─── journeys.yaml ──────────────────────────────────────────────────────────

/** How a step names the element it acts on. A bare string is matched against
 *  button/link names, labels, placeholders, then visible text. */
export const Target = z.union([
  z.string().min(1),
  z.object({ role: z.string(), name: z.string().optional() }).strict(),
  z.object({ label: z.string() }).strict(),
  z.object({ text: z.string() }).strict(),
  z.object({ placeholder: z.string() }).strict(),
  z.object({ testId: z.string() }).strict(),
  z.object({ css: z.string() }).strict(),
]);
export type Target = z.infer<typeof Target>;

const note = { note: z.string().optional() };

export const Step = z.union([
  z.object({ goto: z.string(), ...note }).strict(),
  z.object({ click: Target, ...note }).strict(),
  z.object({ fill: z.object({ target: Target, value: z.string() }).strict(), ...note }).strict(),
  z.object({ select: z.object({ target: Target, value: z.string() }).strict(), ...note }).strict(),
  z.object({ check: Target, ...note }).strict(),
  z.object({ hover: Target, ...note }).strict(),
  z.object({ press: z.union([z.string(), z.object({ target: Target, key: z.string() }).strict()]), ...note }).strict(),
  z.object({ see: z.string(), ...note }).strict(),
  z.object({ wait: z.number().int().min(0).max(30_000), ...note }).strict(),
  z.object({ scroll: z.union([z.enum(['top', 'bottom']), Target]), ...note }).strict(),
  z.object({ reload: z.literal(true), ...note }).strict(),
  z.object({ back: z.literal(true), ...note }).strict(),
]);
export type Step = z.infer<typeof Step>;

/** A shell command run from the project root, e.g. to seed or reset data. */
const Command = z.string().min(1);
const AUTH_NAME = /^[a-z0-9][a-z0-9-]*$/;

export const Focus = z.enum(['first-value', 'recovery', 'feedback', 'data', 'other']);

export const Journey = z
  .object({
    id: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, 'use kebab-case ids'),
    title: z.string(),
    focus: Focus.default('other'),
    goal: z.string(),
    expect: z.array(z.string()).default([]),
    viewport: z.string().optional(),
    /** Start signed in with this `auth` entry. */
    auth: z.string().regex(AUTH_NAME).optional(),
    /** Command to run right before this journey (seed or reset its data). */
    before: Command.optional(),
    steps: z.array(Step).min(1),
  })
  .strict();
export type Journey = z.infer<typeof Journey>;

export const Config = z
  .object({
    version: z.literal(1),
    app: z
      .object({
        name: z.string().optional(),
        url: z.string().min(1),
        viewport: z.string().default('desktop'),
        lang: z.enum(['en', 'ja']).default('en'),
      })
      .strict(),
    /** Commands run once before any journey. */
    setup: z.object({ command: Command }).strict().optional(),
    /** Named sign-in flows. Each runs once per `uxaudit run`; journeys that
     *  name it start from the resulting session. */
    auth: z
      .record(
        z.string().regex(AUTH_NAME),
        z.union([
          z.object({ steps: z.array(Step).min(1) }).strict(),
          // Signed in by hand with `uxaudit auth record <name>` (OAuth,
          // passkeys, 2FA…). `check` proves the saved session still works.
          z.object({ recorded: z.literal(true), check: z.array(Step).min(1) }).strict(),
        ]),
      )
      .default({}),
    journeys: z.array(Journey).min(1),
  })
  .strict()
  .superRefine((c, ctx) => {
    for (const [i, j] of c.journeys.entries()) {
      if (j.auth && !c.auth[j.auth]) {
        ctx.addIssue({ code: 'custom', path: ['journeys', i, 'auth'], message: `no auth entry named "${j.auth}"` });
      }
    }
  });
export type Config = z.infer<typeof Config>;

// ─── capture output (steps.json / run.json) ─────────────────────────────────

export type StepStatus = 'ok' | 'failed' | 'no-change';

export interface StepSignals {
  consoleErrors: string[];
  httpErrors: { status: number; url: string }[];
  slow: boolean;
  horizontalOverflow: boolean;
}

/** A screenshot taken while a step was still settling (a toast, a spinner). */
export interface TransientFrame {
  file: string;
  afterMs: number;
}

export interface StepRecord {
  index: number;
  label: string;
  note?: string;
  status: StepStatus;
  error?: string;
  url: string;
  /** When the step started, relative to the start of the journey video. */
  atMs: number;
  durationMs: number;
  /** Frames that differ from both the previous and the final screen, in order. */
  frames: TransientFrame[];
  shot: string;
  signals: StepSignals;
}

export interface JourneyCapture {
  id: string;
  status: 'completed' | 'blocked';
  viewport: string;
  /** Recording of the whole journey, relative to the run directory. */
  video?: string;
  steps: StepRecord[];
}

export interface RunManifest {
  version: 1;
  runId: string;
  createdAt: string;
  app: { name?: string; url: string; lang: 'en' | 'ja' };
  journeys: (Pick<Journey, 'id' | 'title' | 'focus' | 'goal' | 'expect' | 'auth'> & { capture: JourneyCapture })[];
}

// ─── judge output (verdicts/<journey>.json) ─────────────────────────────────

export const Severity = z.enum(['blocker', 'major', 'minor']);
export const Stage = z.enum(['understand', 'decide', 'act', 'recover']);

export const Finding = z
  .object({
    key: z.string().regex(/^[a-z0-9][a-z0-9-]{2,60}$/, 'key must be a kebab-case slug (3-61 chars)'),
    title: z.string().min(1),
    severity: Severity,
    stage: Stage,
    steps: z.array(z.number().int().min(1)).min(1),
    observation: z.string().min(1),
    suggestion: z.string().min(1),
  })
  .strict();
export type Finding = z.infer<typeof Finding>;

export const Verdict = z
  .object({
    journey: z.string(),
    verdict: z.enum(['pass', 'fail', 'unclear']),
    summary: z.string().min(1),
    findings: z.array(Finding),
  })
  .strict()
  .superRefine((v, ctx) => {
    const serious = v.findings.some((f) => f.severity !== 'minor');
    if (v.verdict === 'pass' && serious) {
      ctx.addIssue({ code: 'custom', message: 'verdict "pass" is not allowed with blocker/major findings' });
    }
    if (v.verdict === 'fail' && v.findings.length === 0) {
      ctx.addIssue({ code: 'custom', message: 'verdict "fail" needs at least one finding' });
    }
  });
export type Verdict = z.infer<typeof Verdict>;

// ─── triage (.uxaudit/triage.json) ──────────────────────────────────────────

// `open` records an explicit reset so it survives merges like any other status.
export const TriageStatus = z.enum(['open', 'fix', 'accepted', 'false-positive']);
export type TriageStatus = z.infer<typeof TriageStatus>;

export const TriageItem = z.object({
  status: TriageStatus,
  note: z.string().default(''),
  title: z.string().optional(),
  updatedAt: z.string(),
});
export type TriageItem = z.infer<typeof TriageItem>;

export const Triage = z.object({
  version: z.literal(1),
  items: z.record(z.string(), TriageItem),
});
export type Triage = z.infer<typeof Triage>;

/** Stable id for a finding across runs and the artifact db doc id. */
export const findingId = (journey: string, key: string) => `${journey}:${key}`;
