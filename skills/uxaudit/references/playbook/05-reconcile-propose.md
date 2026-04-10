# Phase 05 — Reconcile and Propose

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`04-judge-dispatch.md`](./04-judge-dispatch.md) · **Next phase:** [`06-aggregate-report.md`](./06-aggregate-report.md)
> **Subagents dispatched in this phase:** `uxaudit-reconciler` (Step 14, optional), `uxaudit-proposer` (Step 15). Full system prompts at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-reconciler.md` (sonnet, Read/Edit/Write/Glob) and `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-proposer.md` (sonnet, Read/Write/Glob). Claude Code loads them automatically — the orchestrator only passes per-run inputs.

## Step 14 — Reconciler (optional, only if project-context.json exists)

Spawn a `uxaudit-reconciler` subagent. Its rule set — what it MAY flip (narrow aesthetic overrides: brand color, font intent, tagline domain match) and what it MUST NOT flip (usability / accessibility / core-experience / desirability) — is part of the agent definition and loaded automatically.

```python
Agent(
  subagent_type="uxaudit-reconciler",
  description="Catalog-vs-intent reconciler",
  prompt=f"""
iter_dir: {ITER_DIR}
project_context_path: {ITER_DIR}/project-context.json
checks_dir: {ITER_DIR}/checks/
summary_path: {ITER_DIR}/reconciliation-summary.json
Language: {UXAUDIT_LANG}
""",
)
```

The Reconciler writes overrides into the existing `result.json` files (adding `result_after_reconciliation`, `reconciliation_note`, `reconciled_at`) and produces `reconciliation-summary.json`.

## Step 15 — Proposer (cross-check synthesis)

Spawn a `uxaudit-proposer` subagent. It is the **first** role allowed to see BOTH the verdicts and `project-context.json` — verdicts are already locked in by Step 14, so the rationalization risk is gone. Its job is the synthesis layer: cluster fails by root cause, write 2–3 ranked proposals, defer the rest. The full voice guide (PM/designer voice for headlines, engineer voice for `concrete_steps`) and the Cap-at-3-proposals-and-3-root-causes rule live in the agent definition.

```python
# Pseudocode the orchestrator follows
Agent(
  subagent_type="uxaudit-proposer",
  description="Improvement proposal generator",
  prompt=f"""
checks_dir: {ITER_DIR}/checks/
project_context_path: {ITER_DIR}/project-context.json
reconciliation_summary_path: {ITER_DIR}/reconciliation-summary.json
output_path: {ITER_DIR}/improvement-proposal.json
schema_path: {UXAUDIT_DIR}/schemas/improvement-proposal.schema.json
Language: {UXAUDIT_LANG}
""",
)
```

The `uxaudit-proposer` frontmatter pins `tools: Read, Write, Glob` — no `Grep`, no `Bash` — so it physically cannot grep the user's codebase. Its `estimated_files` guesses must come from the information surfaced in `project-context.json` alone; if it can't infer a path with confidence, it leaves `estimated_files` empty rather than fabricating.

If the run has zero fails, the Proposer still writes the file with an empty `proposals` array and `verdict: "All checks passing in this iteration."`.

After the Proposer returns, re-run `validate_results.py "$ITER_DIR"` — it will pick up `improvement-proposal.json` and validate it against the proposal schema. Re-dispatch on errors.
