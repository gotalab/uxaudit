# Heal request contract — reference document

This file is the **canonical heal-request contract** — the common shape and procedure every `uxaudit-*` subagent follows when re-dispatched after a validator error. Each `uxaudit-*` agent definition in `${CLAUDE_PLUGIN_ROOT}/agents/` embeds the relevant parts inline (the "If re-dispatched with a heal_request" section), so you are rarely reading this file directly at runtime.

Who should read this file:

- Authors adding a new subagent role to uxaudit — copy the inline heal section into your new agent's system prompt.
- Anyone debugging why a heal re-dispatch produced the wrong patch.

At re-dispatch time, the orchestrator passes two things in the prompt body:

1. A `heal_request` JSON block listing the specific errors you must patch (schema below)
2. The original per-run inputs (same paths the first dispatch saw)

Your job is to walk the `heal_request` entries and patch them. No fresh re-evaluation, no re-discovery.

## The heal_request block

```json
{
  "heal_request": {
    "previous_output_path": "<absolute path to the file you wrote last time>",
    "errors": [
      {
        "severity": "error",
        "field": "<JSON path e.g. experience_model.jobs[0].contexts[0]>",
        "message": "<the validator's raw diagnostic>",
        "found": "<the value you wrote, or null for missing/structural>",
        "expected": "<short description of what was expected>",
        "healing_hint": "<agent-actionable one-liner — follow this literally>",
        "subagent": "<your role — confirms you were routed correctly>"
      }
    ]
  }
}
```

Every record is self-describing. You do NOT need additional context to act — `field` tells you WHERE, `healing_hint` tells you WHAT, `found`/`expected` disambiguate when the hint is ambiguous.

## Procedure (applies to every role)

1. **Read the file at `previous_output_path`.** This is the output you wrote in the previous dispatch. It is NOT a placeholder.
2. **For each error in order, locate the `field` path inside that file and patch it** using the `healing_hint` literally. Most hints name the exact change.
3. **Do NOT touch any field that is not in the errors list.** Those fields passed validation. Rewriting them risks new errors and wastes the single healing pass — the orchestrator re-validates ONCE and then ships the state as-is.
4. **Re-Write the file to the same path.** Use `Edit` if you are only changing a few fields in a large file; use `Write` only if you need to restructure.
5. **Return a 1-line summary** listing the fields you patched (e.g. `"patched 3 fields: experience_model.jobs[0].contexts (enum), purpose (required), primary_journeys[2].id (duplicate)"`).

## Do not

- Do NOT re-do your original work from scratch (no re-discovery, no re-evaluating evidence, no re-clustering)
- Do NOT add fields that weren't in the errors list
- Do NOT argue with the validator — if you disagree with an error, patch it anyway; disagreement belongs in a separate follow-up
- Do NOT call the validator yourself

## Common heal cases by role

### Scout

| Error pattern | Fix |
|---|---|
| `contexts[N]` / `context` / `priority` / `confidence` / `kind` is not in enum | Machine enum — do not translate under `--lang ja`. Pick the canonical English token closest to the original semantic intent. |
| Required field missing (`purpose`, `target_audience`, etc.) | Add only that field; leave every other field alone. |
| Duplicate id | Rename one duplicate to a distinct slug and update every cross-reference (`journey_chains`, `job_ids`, `next_journey`). |
| `references unknown id` | Either add the missing entry (with honest `confidence: low` if you're inferring) or remove the reference. |
| Too many jobs (warning promoted) | Merge jobs whose actors/outcomes overlap. Keep only jobs with a concrete `evidence_basis` at `confidence: medium` or better. |

### L3 / L4 Judge

| Error pattern | Fix |
|---|---|
| **Rule A rollup violation** (sub-verdict `fail`, top `pass`) | Change the top-level `result` to `fail`. Keep sub-verdicts unless you actually disagree — in which case fix THAT axis. |
| **Rule B rollup violation** (`unverifiable` axis, top `pass`) | Change the top-level `result` to `unverifiable`. A pass requires complete evidence on every axis. |
| `suggestion` missing when `result == fail` | Add a concrete one-sentence suggestion. Name the specific change, not "improve X". |
| `check_id` does not match directory | Use the exact `category/name` string the dispatch prompt gave you. Per-journey L4 checks all share `core-experience/primary-journey` — never invent a per-journey slug. |
| `evidence.details` too short (< 12 chars) | Expand with at least one concrete visual observation from a specific screenshot. |
| Invalid JSON | Usually an unterminated string or raw newline inside `details`. Use `\n` inside JSON strings. |
| `step` must be integer (in `excise_attribution`) | Write `"step": 5`, never `"step": "5"` or `"step": "step-5"`. |

### Proposer

| Error pattern | Fix |
|---|---|
| `check_id` references an id that doesn't exist | Re-read each `result.json` — the canonical `check_id` is the FIELD inside the file, not the directory name. All L4 journey checks share `core-experience/primary-journey`; distinguish journeys in narrative prose via `journey_name`. |
| `addresses_root_causes` empty when `root_causes` exist | Point every proposal at ≥1 root cause by exact `name` match. |
| `title` too long / not imperative | Rewrite the title in plain language as a deliverable ("Make every recipe tile clickable"), not a diagnosis. |

## Language

When the original dispatch was `--lang ja`, the healing_hint strings are already in English (they're validator output) but your patched narrative fields stay in Japanese. Machine fields — `check_id`, enum values, file basenames, route paths — stay verbatim regardless of language.
