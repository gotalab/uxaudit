# Language preamble — reference document

This file enumerates which narrative fields are translated vs which stay verbatim when a user passes `--lang <non-en>`. The `uxaudit-*` subagents embed this contract inline in their own system prompts, so this file is **no longer injected at dispatch time**. It is kept as the authoritative reference — the aggregate / dashboard scripts also key off the enum lists below when rendering translated output.

## Language directive

Write all **narrative** text in 日本語:

- `evidence.details`, every `evidence.matches[].matched_text`, `suggestion`
- Scout: `purpose`, `target_audience`, `viewport_reason`, `discovery_notes`, journey `name` / `goal` / `steps_hint` / `success_criteria`
- Reconciler: `reconciliation_note`
- Proposer: `verdict`, every `proposals[].title` / `summary` / `concrete_steps` / `why_first`, deferred reasons

Keep these **verbatim** — do NOT translate (downstream validators and joins key off the exact strings):

- `check_id` — `scripts/validate_results.py` exact-matches it against the directory name
- `journey_id`, file basenames in `evidence.files` (`001-initial.png`, `<NNN>-final.png`), API endpoints, route paths, code identifiers
- Proper nouns (Tailwind, Next.js, WCAG, ANTHROPIC_API_KEY), numbers, units, code samples
- **Machine enum values, regardless of which field they appear in:**
    - `context` / `contexts` → `cold-start` | `returning` | `power-user`
    - `priority` / `confidence` → `high` | `medium` | `low`
    - `kind` (inside `evidence_basis[*]`) → `e2e` | `scenario-doc` | `route` | `readme` | `category-baseline` | `jtbd` | `external-research`
    - `primary_viewport` → `mobile-sm` | `mobile` | `tablet` | `tablet-pro` | `desktop` | `desktop-lg`
    - `result` (top-level in `result.json`) → `pass` | `fail` | `skipped` | `error` | `unverifiable`
    - Every axis `verdict` inside `journey_evaluation` → same enum as `result`
- Catalog metadata (`name`, `band`, `subtype`, `method`, `severity`, `source`, `rationale`, `pass_criteria`) — these never appear in your dispatch context; the aggregator joins them from `check.json` after you finish. Do not produce them.

The validators reject translated enums and the orchestrator will re-dispatch you in heal mode. **The rule is: translate the narrative AROUND the enum value, never the value itself.**

Use natural Japanese — 体言止め可、敬体不要、専門用語はカタカナ可。When in doubt about a field: if it came from a schema / machine input, keep the original; if you wrote the string yourself, translate it.
