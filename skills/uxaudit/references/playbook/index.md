# Orchestrator playbook — index

This is the navigation page for the literal step-by-step the Claude orchestrator agent follows when the user invokes `/uxaudit <target>`. The playbook is split into **phase files**: load only the file for the phase you are currently executing, plus this index for cross-phase context.

The orchestrator should execute these steps in order, not rephrase them.

## Phase map

| Phase file | Steps | What it covers |
|---|---|---|
| [`00-env-setup.md`](./00-env-setup.md) | 0 | Plugin vs standalone, `$UXAUDIT_DIR`, `NODE_PATH`, `$UXAUDIT_LANG` |
| [`01-discovery.md`](./01-discovery.md) | 1 → 5 | Workspace, project locator (monorepo), URL resolution + auto-launch, Scout, viewport |
| [`02-catalog-run.md`](./02-catalog-run.md) | 6 → 8 | Capture target, run L1/L2 catalog, build evaluation briefs |
| [`03-journey-capture.md`](./03-journey-capture.md) | 9 → 10 | Compile NL journeys to executable scripts (Compiler subagent), parallel L4 capture (Bash + `capture_journey.mjs`) |
| [`04-judge-dispatch.md`](./04-judge-dispatch.md) | 11 → 13 | L3-vision and L4-journey (evidence-only) Judge dispatch, completeness gate, schema gate, cold-start FTUE, journey chains |
| [`05-reconcile-propose.md`](./05-reconcile-propose.md) | 14 → 15 | Reconciler, Proposer (cross-check synthesis) |
| [`06-aggregate-report.md`](./06-aggregate-report.md) | 16 → 18 | Aggregate, dashboard, final report, dev-server cleanup |

Two alternate-mode files compose with the phases above:

| Mode file | When to load | Modifies |
|---|---|---|
| [`../modes/feature-scope.md`](../modes/feature-scope.md) | `--scope feature` is set | Steps 6, 8, 11, 18 |
| [`../modes/library.md`](../modes/library.md) | post-audit views (`--library`, `--archive`, `--unarchive`) | Steps 17–18 only |

## Inputs the user provides

The **public surface arguments** (`<target>`, `--url`, `--electron-app`, `--viewport` / `--viewports`, `--lang`, `--scenario-mode`, `--only`, `--skip`, `--yes` / `-y`) and their semantics are documented in `SKILL.md` → "Argument semantics" — that is the single source of truth. `--yes` (unattended mode) is the only flag that affects orchestrator pause-points; everything else is configuration. The orchestrator must consult [`01-discovery.md`](./01-discovery.md) Step 3 for the exact `--yes` decision tree (cases C/D/E auto-pick safe defaults; cases F and "native without `--url`" still abort).

The flags below are **internal / advanced modes** that don't appear in the SKILL frontmatter `argument-hint`:

- `--no-scenarios` — skip the Scout (no scenario contract synthesized); catalog only
- `--scope feature` — enables feature-scope mode (see [`../modes/feature-scope.md`](../modes/feature-scope.md))
- `--feature-name "<name>"` — required when `--scope feature`
- `--feature-url <url>` — required when `--scope feature`; the URL of the feature being audited
- `--reference-urls <url1,url2,url3>` — required when `--scope feature`; 2–3 URLs from the existing app for the consistency baseline
- `--cold-start` — run L4 journeys in an incognito context (no cookies, no saved data)
- `--workspace <path>` — power-user override for the default `./.agents/uxaudit/<target>/` location
- `--scenario-source-iteration <iter>` — optional source iteration to reuse as the scenario contract when `--scenario-mode locked|hybrid`

The orchestrator stores the `--lang` value internally as `$UXAUDIT_LANG` (NOT `$LANG`, which collides with the standard Unix locale env var). Default is explicit `en` — auto-detection from the shell locale is intentionally avoided so dashboards shared with non-Japanese teammates do not flip to Japanese by accident.

## How to read the dispatch pseudocode

Steps 2, 4, 9, 11, 14, and 15 each spawn a **dedicated subagent role**. Each role is a real Claude Code subagent definition at `${CLAUDE_PLUGIN_ROOT}/agents/<name>.md` with its own frontmatter — the orchestrator passes `subagent_type="<name>"` and Claude Code loads the agent's full system prompt (tool allowlist, model, body text) automatically. **The orchestrator does NOT re-inject the brief into the prompt body.** The dispatch prompt body only carries the per-run variables (paths, `check_id`, `Language: <code>`).

| Pseudocode | What the orchestrator actually does |
|---|---|
| `Agent(subagent_type="uxaudit-<role>", description=…, prompt=…)` | A real `Agent` tool call targeting one of the 7 role definitions below. Model and tools are pinned in the agent frontmatter, not in the call. |
| `{ITER_DIR}`, `{check_id}`, `{journey.name}` | Substitute the per-dispatch values you have in scope at this point in the playbook. |
| `Language: {UXAUDIT_LANG}` | Always include on every dispatch. Each agent has inline language handling and switches narrative output based on this line. |

**The 7 uxaudit subagent roles** (all live at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-*.md`):

| `subagent_type` | Model | Tools | Used in | Output |
|---|---|---|---|---|
| `uxaudit-locator` | sonnet | Read, Glob, Grep, Bash, Write | Phase 01 Step 2 | `project-locator.json` |
| `uxaudit-scout` | opus | Read, Glob, Grep, Write, WebSearch, WebFetch | Phase 01 Step 4 | `project-context.json` |
| `uxaudit-journey-compiler` | sonnet | Read, Write, Bash, WebFetch | Phase 03 Step 9 + 9.6 heal | `journey-scripts/*.json` |
| `uxaudit-l3-judge` | opus | Read, Write | Phase 04 Step 11 (one per L3 check, batched) | `result.json` per check |
| `uxaudit-l4-judge` | opus | Read, Write, Glob | Phase 04 Step 11 (one per journey, batched with L3) | `result.json` per journey |
| `uxaudit-reconciler` | sonnet | Read, Edit, Write, Glob | Phase 05 Step 14 | `reconciliation-summary.json` + in-place `result.json` patches |
| `uxaudit-proposer` | sonnet | Read, Write, Glob | Phase 05 Step 15 | `improvement-proposal.json` |

Tool allowlists are **pinned in the agent frontmatter**. That's the physical isolation layer: the L3 Judge cannot call Bash because it has no Bash tool, not because the prompt told it not to. Similarly, the Scout cannot curl the app because it has no Bash/WebFetch. This prevents subagents from rationalizing around forbidden moves.

**Parallel batching at Step 11**: dispatch one Judge per L3 check AND one Judge per per-journey directory under `core-experience-primary-journey-*`, all batched as multiple `Agent` tool calls **in a single message**, never sequentially. Vision Judges are slow (5–30 s each), so 7 sequential L3 dispatches feel broken (~70 s total) while 7 parallel ones complete in ~15 s. The L4 Judges in Step 11 are evidence-only (Phase 03 already drove the browser), so they're operationally identical to L3 — they can sit in the same parallel batch.

**Parallel capture at Step 10**: `run_all_checks.py` fans `capture_journey.mjs` out across all `journey-scripts/*.json` automatically (up to 4 simultaneous browsers). The orchestrator does not need to manage this — it only needs to ensure Step 9 (the Compiler) ran first.

## Workspace layout (after a run)

Lives at `./.agents/uxaudit/<target>/` (override with `--workspace`). The `.agents/` convention is multi-tool; the `uxaudit/<target>/` sub-namespace keeps multiple targets in one repo from colliding. Add `.agents/` to `.gitignore` if you don't want audits committed. Canonical resolver: `scripts/run_all_checks.py:_resolve_workspace`.

```
.agents/uxaudit/<target>/iteration-N/
  meta.json                         ← per-iteration metadata (`scenario_mode`, source iteration, comparability)
  project-locator.json              ← Step 2
  project-context.json              ← Step 4 (Scout)
  target/{rendered.html,screenshot.png}   ← Step 6
  evaluation-briefs/<id>.json       ← Step 8 (compressed Judge inputs)
  journey-scripts/<journey-id>.json ← Step 9 (Journey Compiler)
  checks/<category>-<check>/{result.json,evidence/*.png}
  checks/core-experience-primary-journey-<N>-<slug>/
    result.json                     ← Step 10 placeholder, Step 11 final verdict
    evidence/{01..99}-*.png         ← Step 10 (capture_journey.mjs)
    evidence/steps.json             ← Step 10 action trace
    evidence/trace.zip              ← Step 10 Playwright trace (debug)
  reconciliation-summary.json       ← Step 14 (if Reconciler ran)
  improvement-proposal.json         ← Step 15 (Proposer)
  benchmark.json                    ← Step 16
```

## Validator gate protocol (applies across all phases)

Every validator call in the playbook — `validate_project_context.py` (Phase 01), `verify_completeness.py` (Phase 04), `validate_results.py` (Phase 04 + Phase 05) — follows the **same 3-step "feedback, don't loop" pattern**. The orchestrator itself is the loop; the validators just hand it actionable errors.

1. **Run the validator with `--json`.** The output is a single JSON object with `errors[]` and `warnings[]`. Every error record carries:
   - `severity` (`error` | `warning`)
   - `file`, `field`, `message` — the raw diagnostic
   - `healing_hint` — an agent-actionable one-liner describing the fix
   - `subagent` — the role that should heal it (`scout`, `judge:<check_id>`, `proposer`, `orchestrator`)
   - `found` / `expected` — the rejected value and what the schema wanted (when known)

2. **If `errors[]` is non-empty**, group the errors by `subagent` and re-dispatch each role ONCE. Each `uxaudit-*` agent's system prompt already contains its own heal-mode section at the bottom, so the re-dispatch prompt body just needs:

   ```
   heal_request: <JSON block with previous_output_path + errors[] routed to this subagent>
   <original per-run inputs — same paths as the first dispatch>
   Language: <code>
   ```

   No separate heal-preamble file injection — the contract is embedded in the agent definition itself. `subagent == "orchestrator"` errors cannot be healed by a subagent — fix them yourself (e.g., restore a missing schema file, correct a workspace path).

3. **Re-run the validator once.** If it still reports errors, **the orchestrator proceeds with the current state and surfaces the persistent errors in the final report**. It does NOT loop a third time. Two tries, then ship with the flaw documented. This cap matches the existing Compiler healing loop (Phase 03 Step 9.5 ↔ 9.6) so nothing in the pipeline can spiral on a stubborn subagent.

**Warnings** are passed forward without re-dispatch by default. Warnings describe quality degradation, not schema corruption — they become coverage caveats in the dashboard. If `--strict` is set, warnings are promoted to errors and go through the same re-dispatch cycle.

The protocol applies uniformly whether the validator is blocking (`validate_project_context.py` in Phase 01) or informational (`validate_results.py --strict` in Phase 04). The only gate that **never** triggers a re-dispatch is `verify_completeness.py` — its "still pending" state means a Judge was never dispatched at all, not that a dispatched Judge wrote garbage, so the fix is to dispatch the missing Judge, not to heal an existing file.

## Critical isolation rule (applies across all phases)

L3/L4 Judge dispatches MUST instruct the subagent to NOT read `project-context.json`, the spec, or any project file. They evaluate ONLY the captured artifacts. This prevents rationalization. The Reconciler is the only place where intent and observation meet.

The L4 split (Phase 03 capture + Phase 04 judge) extends this rule mechanically: the **Compiler** in Step 9 is the only role that simultaneously sees the Scout's narrative intent AND the running app's HTML — and it commits no judgment. The **L4 Judge** in Step 11 reads only screenshots + `steps.json` + the compressed evaluation brief; it cannot read `project-context.json`, the compiled `journey-scripts/`, or any project file. This is what preserves the pixel-only guarantee at judgment time. See [`../concepts/architecture.md`](../concepts/architecture.md) for the rationale and [`03-journey-capture.md`](./03-journey-capture.md) for the capture/judge split design.

## Failure modes the orchestrator must avoid

| Failure | What it looks like | How to avoid |
|---|---|---|
| Letting Judges see the spec | Pass on hope, "this is intentional because…" | Step 11 explicit instruction. Subagent prompts also forbid it. |
| L4 Judge peeks at journey scripts | Verdict echoes the Compiler's intent instead of evaluating the visible result | Step 11 forbids reading `journey-scripts/`. The Compiler in Step 9 keeps selectors out of the evidence directory. |
| Skipping L3/L4 because they're hard | All catalog L1/L2 pass, no real eval done | **Step 12 (verify_completeness.py) blocks the pipeline.** The orchestrator cannot reach Step 16 (aggregate) until every L3/L4 has a real verdict. The new `awaiting evidence-only judge dispatch` sentinel guarantees Phase 03 capture-only runs are flagged as still-pending. |
| Skipping Scout because there's no spec | Generic catalog only, no scenarios | Step 4 still runs and produces a minimal context with one inferred journey. |
| Skipping Step 9 Compiler when journeys exist | L4 capture finds nothing to fan out, all L4 results are skipped | Step 9 is mandatory whenever `project-context.json` has `primary_journeys`. Cache hits via `--scenario-mode locked` are an explicit, deliberate skip. |
| Aggregating before all Judges return | benchmark.json is incomplete | Step 12 is the gate. Never bypass. |
| Reconciler over-applies | Catalog becomes meaningless | The Reconciler brief enumerates EXACTLY which 3 fail patterns it may override. |
| Dispatching L3/L4 sequentially (slow) | Run takes minutes instead of seconds | Batch the Agent calls in Step 11 in a single message. Each L3/L4 takes 5-15s, so 14 checks in parallel = ~15s total instead of ~140s sequential. |
| Running L4 capture serially | Phase 03 takes 10+ minutes for 7 journeys | `run_all_checks.py` already fans `capture_journey.mjs` out at 4-way parallelism — do NOT loop journeys yourself. |
