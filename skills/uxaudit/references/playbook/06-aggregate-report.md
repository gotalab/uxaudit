# Phase 06 — Aggregate, dashboard, report

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`05-reconcile-propose.md`](./05-reconcile-propose.md)

## Step 16 — Aggregate

```bash
python3 $UXAUDIT_DIR/scripts/aggregate.py \
    "$ITER_DIR" --target "$target" --url "$URL" \
    ${UXAUDIT_LANG:+--language "$UXAUDIT_LANG"}
```

This produces `benchmark.json` with the unified summary. The aggregator embeds the Proposer's `improvement-proposal.json` (if present) into the benchmark so the dashboard can render it without re-reading a separate file.

When `--language` is set, the aggregator records it under `metadata.language` so the dashboard's `currentLang` initializer can pick it up automatically — this is how an audit run with `--lang ja` opens straight into Japanese mode without requiring the user to click the EN/JA toggle.

## Step 17 — Dashboard

```bash
python3 $UXAUDIT_DIR/scripts/generate_dashboard.py \
    "$ITER_DIR" --target "$target"
```

The dashboard auto-detects mode (audit / History / compare) and serves on a local port. Internally the mode key is still `timeline`; user-facing copy says `History`. The "Top fixes" section is rendered from the embedded improvement proposal when present.

**Slim by default in audit-run path**: server mode and the per-workspace static `dashboard.html` (auto-written into `<workspace>/dashboard.html`) skip inlining per-check evidence files (screenshots/videos) — they reference them via absolute `file://` URLs instead. This shrinks the dashboard from 10–100s of MB to a few hundred KB without changing what renders. Pass `--static <path>` for a portable export (defaults to embedding so the file is shareable across machines); add `--no-embed-files` to force slim even on `--static`.

**Auto-refreshed Library**: every audit run also rewrites `~/.agents/uxaudit/library.html` (the standalone cross-project Library page). The "Open full Library →" link in every per-workspace dashboard's Library tab targets this file, so cross-project Compare always reaches an up-to-date page without an explicit `--library` invocation. The exact directory follows the precedence in [`references/modes/library.md`](../modes/library.md#where-the-registry-lives) — `$UXAUDIT_HOME` → plugin data → `$XDG_DATA_HOME/uxaudit` → `~/.agents/uxaudit/`.

**History (Timeline) view**: opens on the new **Δ Delta** sub-view by default — surfaces the top 3 actionable changes since iter 1 (regressed / new-fail / persistent-fail / flapping), a counter strip, filter chips, and a check×iteration matrix with drill-down rows. Clicking an iteration stop on the strip drops into that iteration's full audit body (the legacy per-iter view).

## Step 18 — Report + dev-server cleanup

The orchestrator summarizes the run for the user:

- **Verdict**: `<passed>/<total> passing, <failed> failed (X% pass rate)` + the Proposer's `verdict` line
- **UX summary**: `<ux-passed>/<ux-applicable> passing` + `UI Risk <n> flagged`
- **Top 3 fixes** — pulled from `improvement-proposal.json` (rank 1, 2, 3 titles), NOT a hand-rolled list
- **Dashboard URL**

### Dev server cleanup (MANDATORY if we started it)

After printing the report — pass, fail, or error — release any dev server Step 3 launched during *this* run (see Step 3 → "Cleanup boundaries" in [`01-discovery.md`](./01-discovery.md)):

```bash
SHELL_FILE="$WORKSPACE/.dev-server-shell"
if [ -f "$SHELL_FILE" ]; then
  SHELL_ID=$(head -1 "$SHELL_FILE")
  SERVED_URL=$(sed -n 2p "$SHELL_FILE")
  # KillShell(SHELL_ID)   ← orchestrator uses the harness KillShell tool
  rm -f "$SHELL_FILE"
  echo "[uxaudit] stopped dev server at $SERVED_URL"
fi
```
