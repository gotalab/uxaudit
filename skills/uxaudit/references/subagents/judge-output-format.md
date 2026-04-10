# Judge output format (L3 vision / L4 journey) — reference document

Canonical contract for what an L3/L4 Judge subagent must write. The shape is intentionally tiny — verdict + evidence + suggestion. The formal JSON Schema is at [`schemas/check-result.schema.json`](../../schemas/check-result.schema.json).

**Who should read this file**:

- Authors of new L3/L4 checks (when writing a new check's `prompt.md`).
- Anyone debugging why a Judge's `result.json` failed `validate_results.py`.

**This file is NOT injected into Judge dispatches at runtime.** The new `uxaudit-l3-judge` and `uxaudit-l4-judge` subagents embed the contract inline in their own system prompts (`${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-l3-judge.md` / `uxaudit-l4-judge.md`), loaded automatically by Claude Code. The content below is the authoritative reference the agent definitions are derived from.

Catalog metadata (`name`, `band`, `subtype`, `method`, `severity`, `source`, `rationale`, `pass_criteria`) lives in `check.json` and is joined into the dashboard record by `aggregate.py` after you finish. **You never write those fields, on purpose**: the published citation and the author's framing would anchor your verdict toward agreeing with them. Your only rubric is the check's `prompt.md` plus what you observe.

## What the Judge writes

The orchestrator gives you an output path (typically `iteration-N/checks/<check-id>/result.json`). That path already exists as a placeholder — in Claude Code, writing to an existing file requires you to `Read` it first, then `Write` the real verdict back. Do not try to `Write` first.

```json
{
  "check_id": "<category>/<name>",
  "result": "pass",
  "evidence": {
    "details": "<one paragraph: what you observed and why the verdict is what it is>",
    "matches": [
      { "type": "<finding-type>", "matched_text": "<a specific observation>" }
    ],
    "files": ["<optional-supporting-screenshot-or-crop.png>"]
  },
  "suggestion": "<required when result==fail; one sentence; names the specific change>"
}
```

### Field rules

| Field | Required | Notes |
|---|---|---|
| `check_id` | yes | Must be the exact `<category>/<name>` value from the dispatch prompt. `scripts/validate_results.py` exact-matches it against the directory name. **L4 journey checks all share `core-experience/primary-journey`** — never invent per-journey slugs; distinguish journeys via `journey_name` or narrative prose. |
| `result` | yes | One of `pass` / `fail` / `skipped` / `error` / `unverifiable`. Never punt to `skipped` because the call is hard — pick `pass` or `fail`. See the L4 rollup rules below for how `unverifiable` is used. |
| `evidence.details` | yes | Plain-language explanation, shown verbatim in the dashboard. Be specific — name what you saw (numbers, hex, copy). |
| `evidence.matches` | recommended | ≤10 `{type, matched_text}` pairs. Each `type` is a check-specific tag the check's `prompt.md` enumerates (e.g., `craft-detail`, `slop-tell`, `primary-cta`, `waypoint`). |
| `evidence.files` | recommended for L4, optional for L3 | Relative paths inside `evidence_dir`. **Prefer the smallest useful set.** For L3, usually `[]` or a single crop/screenshot when it materially helps the reviewer — do not dump galleries. For L4, list the ordered waypoint screenshots you actually cite in your verdict (see the L4 section below), not every frame captured. |
| `suggestion` | **required when `result == "fail"`** | Concrete, actionable fix. Not "improve clarity" — name the specific change. When `result` is anything else, `suggestion` is the empty string `""`, **never `null`** (the schema rejects `null`). |

Checks may write additional top-level or `evidence.*` fields when their own `prompt.md` says so (the schema's `additionalProperties: true` allows this) — e.g., `core-experience/primary-journey` writes `journey_name` and `journey_evaluation`; `usability/first-time-user-experience` writes `evidence.metrics` with `clicks_to_first_value` / `seconds_to_first_value`.

## Language

When the orchestrator passed `--lang <non-en>` to `/uxaudit`, the dispatch prompt body carries a `Language: <code>` line. Each `uxaudit-*` agent system prompt includes the translation contract inline (distilled from [`language-preamble.md`](./language-preamble.md)): write `evidence.details`, every `evidence.matches[].matched_text`, and `suggestion` in the requested language. Keep `check_id` and every enum value verbatim — the validators exact-match them.

## Voice — write for the reader, not for the catalog

`evidence.details`, `journey_evaluation.<axis>.evidence` (L4), and `suggestion` are read by humans on the dashboard and quoted to PMs and designers. Write them in plain language a non-engineer can act on.

- **Be specific**, but stop short of naming internal abstractions. "Border-radius is uniform 8px" is fine — `8px` is a fact. "Nielsen heuristic #1 is violated" is not — that's a citation the catalog already carries.
- **Do not use internal jargon in prose**: `rollup`, `L3`, `L4`, `band`, `subtype`, `Compiler`, `Reconciler`, `Proposer`, axis machine names like `value_delivery` (use the human label instead).
- **`suggestion` is for the team.** Name the specific change. Engineer-facing pointers (`Wrap RecipeCard.tsx in <Link>`) are fine when paired with a user-facing sentence a PM can read.

## Forbidden moves

You MUST NOT:

1. **Read project files** — `project-context.json`, `README.md`, `spec.md`, `harness/state/*`, `.agents/project-memory/*`, source code. Your verdict must come from the artifact alone. This is the rationalization gate.
2. **Read previous audit artifacts** — `.agents/uxaudit/**`, earlier `benchmark.json`, earlier `result.json`, prior dashboards. Prior verdicts contaminate the current judgment.
3. **Read extra reference files** — you already received this preamble plus the check-specific `prompt.md`. Do not go read `architecture.md` or other skill-bundle references.
4. **Read the compiled `journey-scripts/*.json`** (L4 only) — the Compiler's selectors would contaminate your visual judgment. You would start "seeing" the UI the Compiler claimed was there, not what the pixels actually show.
5. **Drive a browser, call WebFetch, run curl** (L4 only) — the capture is already done. Your only inputs are the PNG files, `steps.json`, and the per-journey `evaluation-briefs/` file.
6. **Pass on hope.** "The design probably intends X" → fail. If the evidence isn't there, that absence IS the finding.
7. **Use vague language** in `details` or `matches`. "Looks polished" is not evidence. "Headline uses 700 weight against 400 body, with -2 % letter-spacing on the headline only" is evidence.
8. **Trust screenshot filename intent over pixel content.** Filenames on disk are counter-only (`001.png`, `002.png`, …). The Compiler's original name hint lives in `steps.json` as `intent`. If a step's `intent` says "recipe-detail-page" but the pixels in `004.png` are visually identical to `003.png` (and `identical_to_previous: true` in `steps.json`), the intent was a wish — the verdict is `fail` or `unverifiable`, never `pass`.
9. **Skip writing the file.** If you finish evaluating you MUST write `result.json` even if the verdict is `error`. `verify_completeness.py` fails the run otherwise.

## Pre-write self-check (MANDATORY — walk this before Write)

Walk this checklist before calling `Write`. The post-flight `validate_results.py` catches items 1-5 structurally and item 6 at parse time, but catching them yourself saves a heal re-dispatch.

1. **`suggestion` is a string.** When `result == "fail"`, `suggestion` is a concrete one-sentence fix. Otherwise `""` (empty string). **Never `null`.**
2. **`check_id` matches the dispatch prompt exactly.** No invented per-journey slugs.
3. **Enum values are canonical English tokens** regardless of language: `result` and every `journey_evaluation.*.verdict` ∈ `{pass, fail, skipped, error, unverifiable}`. Never translate these.
4. **L4 rollup rules are obeyed.** Walk your four `journey_evaluation.*.verdict` values:
   - **Rule A** — any `fail` → top-level `result` MUST be `fail`.
   - **Rule B** — no `fail` but any `unverifiable` → top-level `result` MUST be `unverifiable`.
   - All four `pass` (or a mix of `pass` and `skipped` with an explanation) → top-level `result` is `pass`.

   The rollup is strict on purpose: the whole reason there are four axes is to surface kinds of failure that single-axis evaluation hides. Letting "feels mostly OK" override a failing axis would defeat the model. If you want to soften the impact of a particular axis on the overall verdict, that's what `severity` (catalog metadata) and the dashboard's per-axis breakdown are for — not the rollup.
5. **`step` fields are JSON integers**, not strings. `"step": 5`, never `"step": "5"`. Same for `actual_steps`, `intentional_steps`, `unintentional_excess`.
6. **The JSON parses.** Mentally walk the braces and quotes of your largest prose field (`evidence.details`, usually). **Unescaped `"` inside a string is the #1 Judge bug** — if you wrote `the "+ New Recipe" button`, the inner `"` chars terminate the string early. Escape them as `\"`. Use `\n` for line breaks inside strings, never a raw newline. This rule is especially load-bearing on non-English runs where English UI copy is quoted inside non-English narrative.

## Example: a passing L3 verdict

```json
{
  "check_id": "desirability/visual-craft",
  "result": "pass",
  "evidence": {
    "details": "Body uses Söhne against IBM Plex Mono for code, with -1 % letter-spacing on the display face only. Border-radius is consistently 2px on interactive elements but 12px on cards and modals — a deliberate two-radius rhythm. Spacing follows a custom 6/14/24/48 scale rather than Tailwind's 4/8/12/16. Primary accent is a desaturated terracotta #c75b39.",
    "matches": [
      {"type": "craft-detail", "matched_text": "Two-radius rhythm: 2px on buttons/inputs, 12px on cards/modals"},
      {"type": "craft-detail", "matched_text": "Söhne display face paired with IBM Plex Mono for code"},
      {"type": "craft-detail", "matched_text": "Custom 6/14/24/48 spacing scale, not Tailwind defaults"},
      {"type": "craft-detail", "matched_text": "Desaturated terracotta #c75b39 as primary accent"}
    ],
    "files": []
  },
  "suggestion": ""
}
```

## Example: a failing L3 verdict

```json
{
  "check_id": "desirability/visual-craft",
  "result": "fail",
  "evidence": {
    "details": "I cannot name three specific craft details. Border-radius is uniform rounded-lg (~8px) everywhere. Body font is Inter at a single weight. Spacing is default Tailwind 4/8/16. Colors are out-of-the-box Tailwind indigo/gray. The absence of craft IS the finding.",
    "matches": [
      {"type": "craft-detail", "matched_text": "None found — zero details that distinguish it from a Tailwind UI sample"},
      {"type": "slop-tell", "matched_text": "Centered hero, three identical feature cards with shadow-md rounded-lg"},
      {"type": "slop-tell", "matched_text": "Default Inter at single weight, no display/body contrast"}
    ],
    "files": []
  },
  "suggestion": "Pick a single asymmetric layout decision and commit to it (one full-bleed feature with a real photo, two narrower secondary features below). Add a deliberate typographic contrast (Fraunces 800 headline against Inter 400 body). Choose a non-Tailwind border-radius rhythm (2px squared on buttons, 24px on cards)."
}
```

## L4 journey-specific contract

L4 journey checks (`core-experience/primary-journey`, `usability/first-time-user-experience`, any future `method: L4-journey` check) are evaluated in two phases the orchestrator already ran before dispatching you:

1. **Capture** (orchestrator playbook Phase 03) — `capture_journey.mjs` walks each journey through Playwright using Compiler-authored selectors, takes screenshots, and writes a `steps.json` action trace. **No verdict is produced here.**
2. **Judge** (Phase 04 — you) — you receive paths to the captured PNGs + `steps.json` + the per-journey evaluation brief. You Read them, you never drive a browser, you produce the verdict.

The pixel-only guarantee works because the selectors that drove capture live in `journey-scripts/` (forbidden to you), while the visible result lives in PNGs (your only input). You cannot rationalize a verdict by inspecting code paths because you have no access to any.

### Three-stage Judge protocol (WebJudge-inspired)

Walk these three stages in order. The strict-verdict format resists drift — studies of LLM-as-judge consistency (WebJudge COLM 2025) show verbose rubrics drift and binary verdicts + 1-sentence justification stay calibrated. Resist writing "partial pass" or "mostly fine".

**Stage 1 — Relevance scoring.** Read `steps.json` to learn the action sequence. Glob `evidence/*.png` and sort lexicographically (they're 3-digit zero-padded, so sort order matches capture order even past 100 frames). Mark 3-5 screenshots as "primary evidence":
- `001.png` (entry — always relevant for the `value_delivery` baseline)
- The screenshot immediately AFTER the most decisive action (the click that should produce closure)
- The final frame (success or error state)
- Any frame flagged `status: error` or `status: no-state-change` in `steps.json` — these ARE the failure evidence

**Stage 2 — Per-screenshot fact extraction.** For each primary frame, Read it and write 1-3 concrete visual facts. Facts, not verdicts. Example:
- `002.png`: "Form shows title='L4 verification recipe', cook time=15. Publish button enabled (red, top-right)."
- `004.png`: "Page URL still /recipe/new. No toast or banner. Form still populated. **No closure.**"
- `012.png`: "Visually identical to 004. Did not reach /recipe/[id]."

The facts must come from pixels, not from `steps.json` text or Compiler `intent` strings.

**Stage 3 — Per-axis rollup.** For each of the four axes (`value_delivery`, `task_completion`, `operating_cost`, `feedback_quality`), pick a strict verdict drawing from your Stage 2 facts, then apply Rules A + B from the pre-write checklist above.

### Reading `steps.json` + `frame_diff`

`steps.json` has this shape (fields you care about):

```json
{
  "name": "...",
  "starting_url": "...",
  "success_criteria": "...",
  "total_steps": 12,
  "completed_steps": 11,
  "failed_at": null,
  "frame_diff": {
    "total_frames": 11,
    "unique_frames": 9,
    "max_identical_run": 2,
    "capture_made_progress": true
  },
  "steps": [
    { "idx": 0, "action": "initial-load", "status": "ok", "screenshot": "001.png", "frame_hash": "b53560e6416a", "identical_to_previous": false },
    { "idx": 8, "action": "click", "selector": "text=Publish Recipe", "status": "ok",
      "expect_change": {"kind": "navigation", "timeout_ms": 5000},
      "state_changed": true, "state_change_observed": {"url_changed": true, "dom_size_delta": -15644} },
    { "idx": 10, "action": "final-state", "status": "ok", "screenshot": "012.png", "frame_hash": "6e7d29ab0d13", "identical_to_previous": false }
  ]
}
```

Load-bearing L4 cues, in decreasing order of authority:

1. **`frame_diff.capture_made_progress: false`** (i.e. `unique_frames < 3`) → the capture showed the user essentially one or two page states. The default verdict for `value_delivery` and `task_completion` is `fail` or `unverifiable`, **never `pass`** — a flow that never visually advanced cannot have delivered value.
2. **`status: "no-state-change"`** on any step → the capture layer has already concluded the click resolved in Playwright but produced no visible URL/DOM change. The affected axis is a `fail`. Do not override it by rationalizing from an adjacent screenshot.
3. **`identical_to_previous: true`** on the screenshot right after a click with `expect_change` → the click did nothing user-visible. Evidence of a `fail`, not a `pass`.
4. **`failed_at` non-null** → that step's screenshot is a failure state screenshot. Make it primary evidence in Stage 1.
5. **`selector` fields** → fine to read for counting and ordering. Do NOT let them influence the verdict. The verdict is built from pixels in Stage 2.

### Counting `operating_cost`

Use `steps.json` to count `actual_steps` = user-meaningful actions (`click`, `navigate`, `type` that submits, modal acknowledgments). Do NOT count `screenshot`, `wait`, or system-driven redirects. Then partition the result according to this identity:

```
actual_steps = core_flow_steps + intentional_steps + unintentional_excess
```

- **`core_flow_steps`** are baseline work for the journey's goal — not tracked in either counter, not listed in `excise_attribution`. They're the floor.
- **`intentional_steps`** — actions that semantically match an entry in the brief's `intentional_friction[].matches`. **Match by meaning, not string** — `"type DELETE to confirm"` in the contract matches a real-journey step that asks the user to type the literal word DELETE, regardless of how the UI phrases it.
- **`unintentional_excess`** — actions that are neither core flow nor intentional friction (Cooper's excise).

Fill `excise_attribution` with one entry per intentional-or-unintentional step (NOT core-flow steps), using integer `step` fields. Pass criterion: `unintentional_excess == 0`. Even one unjustified interstitial is a fail.

### `journey_evaluation` block shape

```json
{
  "check_id": "core-experience/primary-journey",
  "journey_name": "Complete a purchase",
  "result": "fail",
  "evidence": { "...": "..." },
  "suggestion": "...",
  "journey_evaluation": {
    "value_delivery":   { "verdict": "pass|fail|skipped|unverifiable", "evidence": "1-3 sentence explanation ≥12 chars" },
    "task_completion":  { "verdict": "pass|fail|skipped|unverifiable", "evidence": "..." },
    "operating_cost": {
      "verdict": "pass|fail|skipped|unverifiable",
      "evidence": "...",
      "actual_steps": 11,
      "intentional_steps": 2,
      "unintentional_excess": 4,
      "excise_attribution": [
        { "step": 5, "kind": "intentional",   "rationale": "Re-enter password matches contract: shoulder-surf guard" },
        { "step": 6, "kind": "unintentional", "rationale": "Survey popup blocked the flow before payment" }
      ]
    },
    "feedback_quality": { "verdict": "pass|fail|skipped|unverifiable", "evidence": "..." }
  }
}
```

The per-axis rubric (what each axis measures, how to score it, failure signals) lives in `checks/core-experience/primary-journey/prompt.md`. Do not restate it here — the check's prompt is dispatched alongside this preamble.

### `evidence.files` for L4

Ordered waypoint screenshots, not a gallery:

```json
"files": ["001.png", "004.png", "008.png", "012.png"]
```

Include the frames you actually cite in your verdict. The dashboard renders them as a journey strip. Counter-only filenames are intentional: the Compiler's `intent` hint stays in `steps.json`, not in the filename — see Forbidden moves rule 8.

### When to use `skipped` for a sub-verdict

`skipped` is narrower than `unverifiable`. Use it only when:

- The contract is missing required inputs for that specific axis (e.g., no `first_value` and no `first_value_signals` → `value_delivery: skipped` with a one-sentence explanation). The other three axes still apply and are scored normally.

Outside that case, do not use `skipped`. Pick `pass`, `fail`, or `unverifiable` honestly.

### When to use `unverifiable` (L4 axes)

`unverifiable` distinguishes "the app failed" from "we couldn't check". Use it when:

- A step in `steps.json` carries `unverifiable_reason` set by the Compiler — the Compiler concluded the affordance does not exist in the running app. The axis depending on that step is `unverifiable`, NOT `fail`. Failing the app for lacking an affordance the Compiler tried to assume is misattribution; the Reconciler / Proposer will surface "the app does not afford X" as a structural finding.
- The journey errored mid-flight at step N. Axes that depend on post-step-N state become `unverifiable`. Axes you CAN evaluate from steps 0..N-1 get honest `pass`/`fail`.
- The capture phase produced zero usable evidence (first step errored). All four axes `unverifiable`, top-level `unverifiable`.

`unverifiable` is NEVER appropriate when:

- You can see from the screenshots that the user got stuck and the failure is in the app's UI. That's a real `fail`.
- You're uncertain but you DO have the evidence. Pick `pass` or `fail` honestly.

**Overriding a Compiler `unverifiable_reason` to `fail`** is allowed ONLY if you can point to a specific screenshot where the affordance would be visible if it existed AND state in `evidence.details` that you are overriding on that visual basis. If the screenshots don't definitively rule out "it exists but elsewhere" (scroll, modal, hover state, a panel behind a step you couldn't reach), keep `unverifiable`.

## If re-dispatched with validator errors

The orchestrator may re-dispatch a Judge with a `heal_request` block — patch only the listed fields, re-Write the same path, do NOT re-run the three-stage protocol. The heal contract is embedded inline in each `uxaudit-*-judge` agent definition. [`heal-preamble.md`](./heal-preamble.md) is kept as a reference document describing the same contract.

## Validation (for reference — you don't run this)

`scripts/validate_results.py <iteration-dir>` runs automatically after every dispatch. It enforces the schema and the Rule A/B rollup. Errors trigger re-dispatch, warnings go through unchanged.
