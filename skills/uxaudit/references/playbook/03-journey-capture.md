# Phase 03 — Journey compile + capture (L4 evidence collection)

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`02-catalog-run.md`](./02-catalog-run.md) · **Next phase:** [`04-judge-dispatch.md`](./04-judge-dispatch.md)
> **Subagent dispatched in this phase:** `uxaudit-journey-compiler` (Step 9 + conditional Step 9.6 healing). Full system prompt at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-journey-compiler.md` (frontmatter: `tools: Read, Write, Bash, WebFetch`, `model: sonnet`). Inline language handling — `Language: <code>` in the dispatch prompt body controls narrative translation; [`../subagents/language-preamble.md`](../subagents/language-preamble.md) is only injected to the legacy L3/L4 Judges in Phase 04 for English-only enforcement.

Phase 03 has four sub-steps that compose the L4 capture pipeline:

| Sub-step | Who | What |
|---|---|---|
| Step 9 | Compiler subagent (sonnet) | Translate Scout's natural-language journeys into executable JSON action scripts |
| **Step 9.5** | **`validate_journey_scripts.mjs`** | **Dry-run every script in Playwright; flag broken selectors + capture DOM excerpts** |
| Step 9.6 (conditional) | Compiler subagent in healing mode | Re-patch failed selectors from validation reports |
| Step 10 | `run_all_checks.py` (parallel `capture_journey.mjs`) | Take real screenshots and write `evidence/` |

The Step 9.5 ↔ Step 9.6 loop runs at most **2 healing iterations**. After that, any remaining broken steps are marked `unverifiable` and the affected `journey_evaluation` axes will be reported as such by the L4 Judge in Phase 04 — they no longer pollute the app's pass/fail tally.

This phase exists because of a hard architectural reality: subagents in Claude Code do **not** have a persistent Playwright session, and the L4 journey check needs both browser navigation AND screenshot-based judgment. Trying to do both in a single subagent dispatch fails — there's no way for one ephemeral subagent to drive a multi-step UI flow and reason about it visually at the same time.

The fix is **split L4 into two phases**: **capture** (this phase) and **judge** ([phase 04](./04-judge-dispatch.md)). This phase compiles the Scout's natural-language journeys into executable scripts and runs them through Playwright in parallel, producing screenshots + an action trace per journey. Phase 04 reads only the resulting evidence — no live browser. This preserves the "pixel-only" guarantee at judgment time while letting capture be deterministic.

The Stagehand cache pattern from Browserbase informs this design: **navigate-time selectors are cacheable across iterations, verdict-time visual judgment is always fresh**. See [`../concepts/architecture.md`](../concepts/architecture.md) for the longer-form rationale.

## Step 9 — Compile journey scripts (subagent)

Spawn a `uxaudit-journey-compiler` subagent. Its full system prompt (selector preference order, NEVER-hardcode-dynamic-IDs rule, FTUE journey, audit_policy, pre-write self-check) is loaded automatically by Claude Code from `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-journey-compiler.md`. The Compiler reads `project-context.json` and writes one executable journey script per primary journey to `<iter-dir>/journey-scripts/<journey-id>.json`.

```python
# Pseudocode the orchestrator follows
Agent(
  subagent_type="uxaudit-journey-compiler",
  description="Journey compiler",
  prompt=f"""
## Inputs
- project-context.json: {ITER_DIR}/project-context.json
- Base URL: {URL}                                # e.g. http://127.0.0.1:3000
- Output directory: {ITER_DIR}/journey-scripts/
- Viewport: {VIEWPORT}                           # e.g. desktop
- Language: {UXAUDIT_LANG}
""",
)
```

The Compiler's tool allowlist (`Read, Write, Bash, WebFetch`) is pinned in the agent frontmatter — it can `WebFetch` / `Bash curl` the running app to peek at HTML structure for selector hints. It physically cannot read project source code (no `Glob`, no `Grep`) or previous audit artifacts.

When `--scenario-mode locked` reuses a previous iteration's `project-context.json`, the orchestrator can also reuse that iteration's `journey-scripts/` directory verbatim:

```bash
# Cache hit: reuse compiled scripts from the source iteration. Skip Step 9.
cp -R "$WORKSPACE/iteration-$SOURCE_ITER/journey-scripts" "$ITER_DIR/journey-scripts"
```

The cache only helps when the UI structure has not changed. When `capture_journey.mjs` in Step 10 records errors for several journeys, that's a signal the cache is stale — re-run with `--scenario-mode hybrid` to force re-compilation.

If `--no-scenarios` is set OR no `primary_journeys` exist in `project-context.json`, **skip Step 9 and Step 10 entirely**. The L4 check will fall through to the legacy "awaiting agent dispatch" placeholder, which the orchestrator can either dispatch in mode-1 (subagent-drives-Playwright, where supported) or accept as a clean skip.

Compiler output (one file per journey):

```
<iter-dir>/journey-scripts/
├── create-first-recipe.json
├── cook-from-recipe.json
├── discover-by-search-and-filter.json
├── save-and-organize-with-cookbook.json
├── ai-meal-plan-and-shopping-list.json
├── fork-and-annotate-recipe.json
└── rate-review-and-follow.json
```

Each file conforms to the journey schema documented in [`../concepts/architecture.md`](../concepts/architecture.md) and consumed by `capture_journey.mjs`.

## Step 9.5 — Validate compiled journey scripts (Playwright dry-run)

```bash
node $UXAUDIT_DIR/scripts/validate_journey_scripts.mjs \
    "$ITER_DIR/journey-scripts" \
    ${VIEWPORT:+--viewport "$VIEWPORT"}
```

For each `<id>.json` in `journey-scripts/`, the validator opens Playwright once, walks the steps without taking screenshots, and writes a sibling `<id>.validation.json` with per-step status. On the **first** failure of a journey it captures a 3KB DOM excerpt around the failure site so the next-step healing pass has ground truth instead of having to re-curl.

Output shape:

```json
{
  "journey_id": "ai-meal-plan",
  "validated_at": "2026-04-09T08:14:22Z",
  "starting_url": "http://localhost:3000/meal-planner",
  "viewport": { "width": 1440, "height": 900 },
  "ok": false,
  "first_error_step": 10,
  "total_steps": 16,
  "steps": [
    { "idx": 0, "action": "initial-load", "status": "ok" },
    { "idx": 4, "action": "click", "selector": "button:has-text(\"Vegetarian\")", "status": "ok" },
    {
      "idx": 10, "action": "type",
      "selector": "input[placeholder*='rice, olive oil']",
      "status": "error",
      "error": "TimeoutError: locator.waitFor: Timeout 8000ms exceeded.",
      "dom_excerpt": "<form>...<textarea placeholder='e.g. olive oil, garlic, ...'>...</textarea>...</form>"
    }
  ]
}
```

The validator never modifies the journey scripts. The orchestrator reads the reports next.

### Healing decision (orchestrator)

After the validator returns:

1. Read every `<id>.validation.json`. Build a list of journeys with `ok: false`.
2. If the list is empty → proceed to Step 10. No healing needed.
3. If the list is non-empty AND `$HEAL_ATTEMPTS < 2` → run **Step 9.6 healing dispatch**.
4. If the list is non-empty AND `$HEAL_ATTEMPTS == 2` → accept the remaining failures. Their L4 Judge will mark the affected axes as `unverifiable` (see [phase 04 / unverifiable verdict](./04-judge-dispatch.md)).

The healing-attempts counter is per-iteration and lives in memory only — it does not persist across runs.

## Step 9.6 — Healing dispatch (conditional)

When Step 9.5 reports failures and the cap is not yet reached, re-dispatch the Compiler in **healing mode**. The healing protocol (read validation reports, patch only failing steps, do NOT touch passing journeys) is part of the agent definition at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-journey-compiler.md` — you only need to pass the per-run inputs plus a `heal_request` marker:

```python
# Pseudocode the orchestrator follows
Agent(
  subagent_type="uxaudit-journey-compiler",
  description="Journey compiler (healing pass)",
  prompt=f"""
heal_request: true

## Inputs (this dispatch)
- Failed journey scripts: {ITER_DIR}/journey-scripts/<id>.json (only the broken ones)
- Validation reports:    {ITER_DIR}/journey-scripts/<id>.validation.json (only the broken ones)
- Base URL: {URL}
- Viewport: {VIEWPORT}
- Language: {UXAUDIT_LANG}

After patching, **return** — the orchestrator will re-run Step 9.5 to
check whether the patches actually fix the failures.
""",
)
```

After healing returns, the orchestrator loops back to Step 9.5 to re-validate. If the cap is reached, it accepts the remaining failures and proceeds to Step 10.

`unverifiable_reason` field: when the Compiler determines that a step **cannot be made to work** (e.g., the page genuinely lacks the required affordance), it marks the step with `"unverifiable_reason": "<short explanation>"`. This is a signal to the orchestrator and to the eventual L4 Judge that this step is intentionally broken at the schema level — capture should still proceed (so we get the partial evidence) but the corresponding axis verdict in `journey_evaluation` becomes `unverifiable` rather than `fail`.

## Step 10 — Capture journeys in parallel (Bash + capture_journey.mjs)

Step 10 is integrated into `run_all_checks.py`. When you call:

```bash
python3 $UXAUDIT_DIR/scripts/run_all_checks.py \
    "$target" --url "$URL" \
    ${VIEWPORT:+--viewport "$VIEWPORT"} \
    --workspace "$WORKSPACE" \
    --reuse-iteration $ITER \
    --no-capture --no-dashboard
```

…the orchestrator script automatically detects `<iter-dir>/journey-scripts/*.json` and fans `capture_journey.mjs` out in parallel (up to 4 simultaneous browsers, one process per journey). Each journey lands in its own per-journey directory:

```
<iter-dir>/checks/core-experience-primary-journey-1-create-first-recipe/
├── result.json                ← placeholder; the L4 Judge in Step 11 overwrites this
└── evidence/
    ├── 001-initial.png         ← always written first
    ├── 002-form-meta-filled.png
    ├── 003-ingredient-filled.png
    ├── ...
    ├── NNN-final.png           ← always written last (NNN = final step counter)
    ├── steps.json              ← per-step status/action trace
    └── trace.zip               ← Playwright trace (debug)
```

The N in `core-experience-primary-journey-<N>-<slug>` is a 1-based index (alphabetical order of the journey-script filenames); the `<slug>` is the journey id verbatim (matches `journey-scripts/<id>.json`).

Screenshot filenames use a 3-digit zero-padded counter (`001-`, `002-`, …) so they sort lexicographically even past 99. A typical journey is 6–12 frames, but long forms or error-recovery loops can spike past 100 — the padding is sized to tolerate that without breaking the dashboard waypoint strip or the L4 Judge's frame ordering. **Consumers should glob `*.png` and sort the result lexicographically**, not hard-code an upper bound on the counter. The final screenshot is always named `<NNN>-final.png` (or `<NNN>-after-error.png` if the journey hit a mid-flight failure); do not assume the value of NNN.

Per-journey timeout is 5 minutes. Total wall time for 7 journeys at 4-way parallelism is typically under 2 minutes on a local dev server.

### What Step 10 does NOT do

- It does **not** decide a verdict. Each per-journey `result.json` is left as a placeholder with `result: "skipped"` and `details: "L4-judge: awaiting evidence-only judge dispatch (capture complete)"`. The completeness gate ([Step 12](./04-judge-dispatch.md#step-12--completeness-gate)) recognizes this sentinel as still-pending.
- It does **not** delete the evaluation briefs. The Judge in Step 11 still reads them.
- It does **not** look at iteration-1 outputs. Capture is fresh every iteration.

### Failure handling

- A journey that errors mid-capture still produces an `evidence/` directory with whatever screenshots got captured before the failure, plus a final `99-after-error.png` of the failure state. `steps.json` records `failed_at: <step-idx>`. The Judge in Step 11 reads this and makes a verdict against the failure evidence.
- If `node` or `capture_journey.mjs` is missing, Step 10 prints an error and skips L4 capture entirely. The legacy "awaiting agent dispatch" placeholder remains and the orchestrator can route to mode-1 or accept the skip.
- A timeout (300s per journey) is logged and treated as a capture failure for that journey only — other parallel captures are unaffected.

### Why parallelism is capped at 4

Four simultaneous browsers exhaust most local dev servers' ability to serve hot-reloaded SPA bundles smoothly, but 4 is enough that 7-journey runs finish in two batches. Larger numbers risk HMR or SQLite write-lock contention. Hard-coded in `run_l4_journey_captures`.

## Cold-start FTUE journey

The Compiler is required to emit `_ftue.json` alongside the primary-journey scripts (§ Mandatory FTUE journey in `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-journey-compiler.md`). Filename must be exactly `_ftue.json`, `cold_start: true` is mandatory, `starting_url` is the app root. `capture_journey.mjs` routes its evidence to `checks/usability-first-time-user-experience/evidence/`; the Phase 04 Judge dispatch picks it up as just another evidence-only L4 dispatch with `check_id: usability/first-time-user-experience`.
