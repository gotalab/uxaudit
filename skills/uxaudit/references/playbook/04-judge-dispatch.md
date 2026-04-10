# Phase 04 — Judge dispatch (L3/L4) and post-dispatch gates

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`03-journey-capture.md`](./03-journey-capture.md) · **Next phase:** [`05-reconcile-propose.md`](./05-reconcile-propose.md)
> **Subagents dispatched in this phase:** `uxaudit-l3-judge` (Read + Write only, opus) and `uxaudit-l4-judge` (Read + Write + Glob only, opus). Each agent's full system prompt — output contract, rollup rules, three-stage WebJudge protocol, forbidden moves, inline language handling — lives in `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-l3-judge.md` and `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-l4-judge.md` and is loaded automatically by Claude Code. [`../subagents/judge-output-format.md`](../subagents/judge-output-format.md) is kept as a reference document only — it is NOT injected into dispatches anymore.

This phase is what makes `/uxaudit` a real audit instead of a stub. **Skipping it is not allowed.** The completeness verifier in [Step 12](#step-12--completeness-gate) will fail loud if any L3/L4 check is left in a pending state — including the new `awaiting evidence-only judge dispatch (capture complete)` sentinel that Phase 03 leaves on every per-journey result.json.

L3 and L4 Judges are dispatched in **the same parallel batch** in Step 11. Both read evidence files only — neither drives a browser, neither inspects DOM. The split between Phase 03 (capture) and this phase (judge) is what preserves the pixel-only guarantee at judgment time while letting the L4 capture phase be deterministic. See [`03-journey-capture.md`](./03-journey-capture.md) for the rationale.

## Step 11 — L3 / L4 Judge dispatch (one subagent per check) — MANDATORY

The orchestrator dispatches one Judge subagent per L3/L4 check, in parallel where possible (multiple `Agent` tool calls in a single message). The vision and journey checks are slow (5-30 sec each), so dispatching them sequentially makes the run feel broken — always batch.

For each check whose `check.json` has `method: "L3-vision"` or `"L4-journey"`:

### Output contract lives in the agent definition

Every Judge subagent writes `result.json` conforming to `schemas/check-result.schema.json`. The output contract (required fields, canonical example, forbidden moves, three-stage WebJudge protocol, rollup rules) is **pre-loaded** by Claude Code from the agent frontmatter file — you do NOT need to inject it into every dispatch:

- L3 Judges load their system prompt from `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-l3-judge.md`
- L4 Judges load their system prompt from `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-l4-judge.md`

The per-dispatch prompt body only carries the **per-check variables** (`check_id`, paths, language directive) + the check-specific rubric (`prompt.md`). This is a materially smaller prompt than the old "inject judge-output-format.md preamble everywhere" pattern.

The legacy preamble file at [`../subagents/judge-output-format.md`](../subagents/judge-output-format.md) is kept as a **reference document** for authors of new L3/L4 checks — read it when designing a new check's `prompt.md`. It is NOT re-injected at dispatch time.

### Language handling (inline in the agent)

Both `uxaudit-l3-judge` and `uxaudit-l4-judge` handle language inline: the dispatch prompt body includes a `Language: <code>` line, and the agent's system prompt contains the translation contract. The separate [`../subagents/language-preamble.md`](../subagents/language-preamble.md) file is retained only for roles that do NOT have inline language handling (historically the old generic-purpose Judge path) — the new `uxaudit-*` agents do not need it.

On `--lang ja` runs, include `Language: ja` in the dispatch prompt body for every Scout / Journey-Compiler / L3-Judge / L4-Judge / Reconciler / Proposer dispatch. On `--lang en` runs, include `Language: en` (explicit is better than implicit).

**`check_id` is always verbatim** (`validate_results.py` exact-matches it against the directory name). **Catalog metadata is never in the dispatch at all** — `name`, `band`, `subtype`, `method`, `severity`, `source`, `rationale`, `pass_criteria` all live in `check.json` and `aggregate.py` joins them into the dashboard record after the run. Judges never read or write any of them, on purpose: knowing the citation, the author's "why", or the catalog's own classification biases the verdict toward agreeing with that frame.

### L3-vision dispatch

For each L3 check (`desirability/aesthetic-first-impression`, `desirability/visual-craft`, `desirability/copy-craft`, `usability/visual-hierarchy`, `usability/empty-state-guidance`, `usability/system-status-visibility`, `core-experience/value-prop-clarity`):

```python
# Pseudocode — dispatch one per L3 check, batched in a single message
Agent(
  subagent_type="uxaudit-l3-judge",
  description=f"L3-vision judge for {check_id}",
  prompt=f"""
check_id: {check_id}
prompt_path: {UXAUDIT_DIR}/checks/{check_id}/prompt.md
screenshot_path: {ITER_DIR}/target/screenshot.png
brief_path: {ITER_DIR}/evaluation-briefs/{check_id}.json   # only for project-shaped checks
output_path: {ITER_DIR}/checks/{check_dir}/result.json
Language: {UXAUDIT_LANG}
""",
)
```

The `uxaudit-l3-judge` agent frontmatter pins `tools: Read, Write` (no Bash, no WebFetch, no Glob, no Grep) and `model: opus`. The agent cannot physically drive a browser, curl the running app, or wander project source code — the tool surface IS the rationalization gate.

The Judge writes `result.json` per the contract embedded in its system prompt. [Step 13](#step-13--result-schema-gate) (`validate_results.py`) will catch any schema violation post-dispatch.

**Why Opus for L3**: Sonnet's vision is generous on craft tells (false-passes generic AI-slop layouts as "bespoke"). Opus is noticeably stricter on the "cite 3+ specific details" rubric. The model is pinned in the agent frontmatter.

### L4-journey dispatch (evidence-only — NO browser)

This is the second half of the L4 split. Phase 03 already drove Playwright through every primary journey and produced screenshots + a per-step action trace. Step 11 reads only that evidence. The `uxaudit-l4-judge` agent frontmatter pins `tools: Read, Write, Glob` — no Bash, no WebFetch — so the Judge physically **cannot** open a browser, curl the app, or read project source files. Its entire input surface is the screenshots + `steps.json` + the compressed evaluation brief. The three-stage WebJudge protocol and the Rule A/B rollup live in the agent's system prompt.

Discovery loop: enumerate `<iter-dir>/checks/core-experience-primary-journey-*/` in alphabetical order. Each per-journey directory was created in Phase 03 with a placeholder `result.json` whose details begin with `L4-judge: awaiting evidence-only judge dispatch`. Dispatch one Judge per directory.

```python
# Pseudocode — dispatch one per L4 journey, batched in the same message as L3
Agent(
  subagent_type="uxaudit-l4-judge",
  description=f"L4-journey judge for {journey_dir.name}",
  prompt=f"""
check_id: core-experience/primary-journey
journey_name: {journey_name_from_context}
prompt_path: {UXAUDIT_DIR}/checks/core-experience/primary-journey/prompt.md
evidence_dir: {ITER_DIR}/checks/{journey_dir.name}/evidence/
steps_json_path: {ITER_DIR}/checks/{journey_dir.name}/evidence/steps.json
brief_path: {ITER_DIR}/evaluation-briefs/{journey_id}.json
output_path: {ITER_DIR}/checks/{journey_dir.name}/result.json
Language: {UXAUDIT_LANG}
""",
)
```

The FTUE journey uses the same subagent but with `check_id: usability/first-time-user-experience` and `prompt_path` pointing at the FTUE check's `prompt.md`.

**Why Opus for L4**: 6–12 screenshots per journey, sometimes a mid-journey error frame, and a four-axis rubric. Opus's multi-frame fact extraction is materially better than Sonnet's at noticing "the form submitted but the success page is missing the freshly-created entity". Model is pinned in the agent frontmatter.

#### Reading `evidence/steps.json`

`capture_journey.mjs` writes a structured trace of every action it executed:

```json
{
  "journey_id": "create-first-recipe",
  "started_at": "2026-04-09T08:14:22Z",
  "ended_at": "2026-04-09T08:14:48Z",
  "viewport": { "width": 1440, "height": 900 },
  "steps": [
    { "idx": 0, "action": "wait", "ms": 800, "status": "ok" },
    { "idx": 1, "action": "screenshot", "name": "01-initial", "status": "ok" },
    { "idx": 2, "action": "navigate", "url": "/recipe/new", "status": "ok" },
    { "idx": 3, "action": "type", "selector": "input[placeholder*='Tomato']", "text": "L4 verification recipe", "status": "ok" },
    ...
    { "idx": 14, "action": "click", "selector": "text=Publish Recipe", "status": "error", "error": "selector did not resolve" }
  ],
  "failed_at": 14,
  "non_fakeable_skips": [
    { "step_hint_index": 3, "reason": "AI generation step would burn LLM tokens; captured ready-to-submit state instead." }
  ]
}
```

Use it to:

- Match each PNG name to the action that produced it (`01-initial.png` → `idx=1 screenshot`)
- Detect mid-journey failures: if `failed_at` is set, the screenshot named `99-after-error.png` is the failure state, NOT a passing endpoint
- Recognize deliberate omissions: anything in `non_fakeable_skips` is a Compiler-side decision, not a UX failure

`steps.json` is **not** the verdict source. The rubric is what you can see in the PNGs. `steps.json` only disambiguates ordering and intent.

#### Discovery fallback

If `<iter-dir>/checks/core-experience-primary-journey-*/` is empty (no per-journey directories), the L4 capture phase did not run — either Phase 03 was skipped, the Compiler failed, or `node`/`capture_journey.mjs` is missing. In that case the orchestrator falls back to the legacy `core-experience-primary-journey/` directory (singular) whose placeholder still says `awaiting agent dispatch`. Two recovery routes:

1. **Re-run Phase 03**, then come back here. This is the preferred path on local dev environments.
2. **Accept the skip honestly**: write a single result.json with `result: "skipped"` and a reason that names the actual obstacle (`"node not installed"`, `"no primary_journeys discovered"`). Do NOT fabricate a fail-or-pass verdict from a single screenshot when the journey wasn't actually traversed.

If `project-context.json` has only 1–2 journeys for a product that clearly looks like SaaS / marketplace / team software, surface that in the final run summary as a coverage warning. A passing audit with weak journey discovery should not look fully trustworthy.

## Step 12 — Completeness gate

```bash
python3 $UXAUDIT_DIR/scripts/verify_completeness.py "$ITER_DIR"
```

Exits non-zero if **any** L3/L4 check is still in a pending state. The pending sentinels recognized are:

- `awaiting agent dispatch` (legacy single-placeholder L4 path)
- `requires agent dispatch` (older variant)
- `awaiting evidence-only judge dispatch` (set by Phase 03 on every per-journey result.json before Step 11 overwrites it)

If it fails, the orchestrator MUST loop back to Step 11 and dispatch the missing checks. Do not proceed to aggregation with missing verdicts — an incomplete audit is worse than an honest skip because it silently undercounts failures.

Expected output:

```
✅ All N L3/L4 checks have verdicts in iteration-N
```

## Step 13 — Result schema gate (post-flight validator)

```bash
python3 $UXAUDIT_DIR/scripts/validate_results.py "$ITER_DIR"
```

Walks every `result.json` in `$ITER_DIR/checks/` and validates each one against `schemas/check-result.schema.json`. Catches malformed Judge output that the completeness gate misses:

- A Judge wrote `result: "fail"` but forgot the required `suggestion` field
- A Judge used a `category`/`layer`/`method` outside the schema enum
- A Judge mistyped `check_id` so it doesn't match the directory name
- A Judge wrote a result.json that's not even valid JSON (truncated, syntax error)

Errors block the run; warnings are surfaced but non-blocking. If errors are present, the orchestrator must re-dispatch the affected check (loop back to Step 11 for that specific check id), not aggregate broken data.

L1/L2 results always pass this gate because `check_lib.write_result()` is hard-coded against the schema. The gate is primarily for L3/L4 — its presence is what makes them safe to operationalize. Without it, any Judge subagent could quietly write a malformed `result.json` and the dashboard would render gibberish.

`validate_results.py` also walks `improvement-proposal.json` if present and validates it against `schemas/improvement-proposal.schema.json` — so the same script doubles as the [Step 15](./05-reconcile-propose.md#step-15--proposer-cross-check-synthesis) (Proposer) gate. Re-run it after Step 15 returns and re-dispatch the Proposer if its output is malformed.

Expected output:

```
Checked N result(s)
  errors:   0
  warnings: 0

All result.json files conform to the schema.
```

If you see anything else, fix it before continuing to [Phase 05](./05-reconcile-propose.md).

## FTUE + journey chains

**FTUE** (`usability/first-time-user-experience`) is structurally identical to any other evidence-only L4 dispatch — the Compiler already emitted `_ftue.json`, `capture_journey.mjs` wrote cold-start evidence into `checks/usability-first-time-user-experience/evidence/`, and Step 11 dispatches one more Judge in the same parallel batch using the pseudocode above with `check_id: usability/first-time-user-experience`. No special casing.

**Journey chains** (`project-context.json.primary_journeys[].next_journey`) are also handled without special casing: Phase 03's compiler emits one script per link, capture walks them in alphabetical order, and Step 11 dispatches an independent Judge per link. If an upstream link captured a failure, downstream links usually show a failure state the Judge verdicts against on its own. The Reconciler in Phase 05 is the only role that recognizes chain context and can produce a chain-level rollup.
