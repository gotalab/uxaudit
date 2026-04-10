# Phase 02 — Catalog run (capture, L1/L2, evaluation briefs)

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`01-discovery.md`](./01-discovery.md) · **Next phase:** [`03-journey-capture.md`](./03-journey-capture.md)

## Step 6 — Capture target

```bash
# Web target — pass --viewport when set; capture.mjs handles default itself
node $UXAUDIT_DIR/scripts/capture.mjs "$URL" "$ITER_DIR/target" \
    ${VIEWPORT:+--viewport "$VIEWPORT"}

# Electron target (no --url; capture.mjs launches the app via playwright._electron)
node $UXAUDIT_DIR/scripts/capture.mjs --electron-app "$ELECTRON_APP" "$ITER_DIR/target"
```

Produces `rendered.html` and `screenshot.png` for catalog evaluation. The captured viewport (and `kind: web|electron`) is recorded in `meta.json` so the dashboard can show which size each iteration was audited at.

## Step 7 — Catalog checks (L1 + L2 only, automated)

```bash
python3 $UXAUDIT_DIR/scripts/run_all_checks.py \
    "$target" --url "$URL" \
    ${VIEWPORT:+--viewport "$VIEWPORT"} \
    --workspace "$WORKSPACE" \
    --reuse-iteration $ITER \
    --no-capture --no-dashboard
```

For Electron targets, swap `--url "$URL"` for `--electron-app "$ELECTRON_APP"` (no `--viewport`; Electron windows have their own size).

This runs every L1-script and L2-script check. L3/L4 checks are written as `skipped: awaiting agent dispatch` (the L4 placeholder is later overwritten by the per-journey directories that Phase 03's capture step produces).

## Step 8 — Build evaluation briefs (when project-context exists)

If `project-context.json` exists, derive compressed Judge inputs before the L4 capture phase begins:

```bash
python3 $UXAUDIT_DIR/scripts/generate_evaluation_briefs.py \
    "$ITER_DIR/project-context.json" \
    --output-dir "$ITER_DIR/evaluation-briefs"
```

These files are the safe middle layer between Scout and Judge. Keep them narrow. Generate them only for project-shaped UX checks, not for every L3/L4 check. Phase 04's L4 Judges read the per-journey brief at `evaluation-briefs/core-experience-primary-journey-<N>-<slug>.json`, so this step must complete before Phase 03's compiler runs (the compiler does not read briefs, but the Judge in Phase 04 will fail without them).
