# Feature-scope mode

An alternative to whole-app mode, activated when the user passes `--scope feature` along with `--feature-name`, `--feature-url`, and `--reference-urls` (2–3 URLs from the existing app to anchor a consistency baseline).

In whole-app mode the orchestrator answers "is the entire app usable end to end?". In feature-scope mode it answers "is this **specific feature** consistent with the rest of the app, and does it complete its own micro-journey?". Feature-scope mode is what you reach for after shipping a single new screen — it costs less than a full audit and lands the verdict on the thing you actually changed.

The pipeline is the same Steps 0–18 from the playbook (`references/playbook/index.md`) with these modifications:

## Step 6 — Capture (modified)

- Capture the **feature URL** as `target/screenshot.png` (the usual primary capture)
- Additionally capture each `--reference-urls` URL into `references/ref-N-<slug>/screenshot.png`
- The reference captures become input for the `usability/feature-consistency` Judge dispatch in Step 11

## Step 7 — Catalog (modified)

Run the L1/L2 catalog **only on the feature page** — never on the references. References exist solely as a consistency anchor; they are not under audit.

## Step 9 — Journey Compiler (modified)

If the Scout matched `--feature-name` to an entry in `project-context.json.primary_journeys`, the Compiler emits **only** that journey script (and any chained `next_journey` links). Other journeys are skipped. If no match is found, the Compiler derives a single feature-specific journey from the feature URL alone (single-page interaction) and emits one script for it.

## Step 11 — Judges (modified)

- Dispatch the standard L3-vision Judges on the feature page (same as whole-app mode)
- **Additionally** dispatch `usability/feature-consistency` with the feature page screenshot AND the reference screenshots as inputs
- L4 dispatch reads only the per-journey evidence directories produced by Step 10 (same evidence-only contract as whole-app mode); the Compiler in Step 9 already narrowed the journey set

## Step 18 — Report (modified)

- Lead with the **feature audit verdict**, NOT the overall app verdict
- Specifically surface: feature-consistency findings, excise-detection findings, value-prop-clarity for the feature
- The dashboard renders a "feature audit" badge in the header so reviewers know what they're looking at

## Example invocation

```bash
/uxaudit shop-app \
  --url http://localhost:3000 \
  --scope feature \
  --feature-name "playlist sharing" \
  --feature-url http://localhost:3000/playlist/abc/share \
  --reference-urls http://localhost:3000/,http://localhost:3000/library,http://localhost:3000/settings
```
