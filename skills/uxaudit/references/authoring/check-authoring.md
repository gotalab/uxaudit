# Check authoring guide

This is the file you read **before** adding a new check to uxaudit. It exists so the next agent (or you in a future session) can add a check correctly without reading every existing example by trial and error.

If you ignore one thing on this page, ignore the prose. **Read [the schema](../../schemas/check-manifest.schema.json) first**, then [an existing exemplar](#exemplars), then run [the validator](#validator) on your draft. Those three steps stop 95% of mistakes.

---

## When to add a check

Don't add a check because it "seems useful." Add it when **all four** are true:

1. **Observed in ≥3 real projects** — not theoretical, not a hypothetical edge case. You found the same anti-pattern across multiple captures.
2. **Grounded in published research** — WCAG, Nielsen, NN/g, Krug, Norman, Cooper, Christensen, ISO 9241, peer-reviewed paper. No internal opinion. The full allow-list and the "don't invent" rule are in [`../knowledge/sources.md`](../knowledge/sources.md). Self-evident anti-patterns (lorem ipsum, "Coming soon" stubs) don't need a research anchor because they aren't judgment calls.
3. **Two judges agree** — your `pass_criteria` is concrete enough that two reviewers reading only that string and looking only at the captured artifact would reach the same verdict ≥90% of the time.
4. **Right band + subtype** — see [classification choice](#classification-choice). If you can't decide where it fits, the check probably isn't ready yet.

If any of those four are false: don't add the check yet. Park it until you can document the third sighting and the second source.

---

## File layout

```
checks/<category>/<name>/
  check.json                  ← REQUIRED — manifest, validated against the schema
  detect.py                   ← REQUIRED for L1-script
  run.mjs                     ← REQUIRED for L2-script
  prompt.md                   ← REQUIRED for L3-vision and L4-journey
  fixtures/                   ← STRONGLY ENCOURAGED for L1 (regression test layer)
    fail/                     ← MUST produce result == "fail"
      rendered.html
      stylesheets.css
      visible-text.txt
      computed-styles.json
    pass/                     ← MUST produce result == "pass"
      ...
    fail-second-case/         ← optional: multiple failure cases with labeled suffix
    pass-edge-case/           ← optional: multiple pass cases
```

The directory **must** be `checks/<category>/<name>/` with the manifest's `id` matching `<category>/<name>` exactly. The validator enforces this. There is no separate `category` field in `check.json` — the directory layout (and the first segment of `id`) is the single source of truth, and `aggregate.py` derives the category from `check_id` when joining the dashboard record.

The five existing categories are `accessibility`, `ai-slop`, `core-experience`, `desirability`, `usability`. Adding a new one means creating a new top-level directory under `checks/` AND teaching the dashboard renderer about it; don't do it casually.

### Fixtures (the regression test layer)

The schema validator catches **manifest** drift. It cannot catch **logic** drift. If you change a threshold inside `detect.py` from 2 to 5, the validator stays green but the detector now silently catches half what it used to. The only safety net for that is per-check fixtures.

Convention:
- Each subdirectory under `fixtures/` is a captured target. Its name encodes the expected verdict via the prefix: `pass`, `fail`, or `skipped`.
- Optional `-<label>` suffix lets you have multiple fixtures of the same expected verdict (e.g., `fail-purple-gradient`, `fail-stripe-bootstrap`, `pass-monochrome`).
- Inside each subdirectory, only provide the files the detector actually reads (e.g., `coming-soon-text` only needs `visible-text.txt`).

**Important**: the captured CSS in `stylesheets.css` is **browser-normalized** form (it comes from CSSOM via Playwright). This means:
- `0` becomes `0px` (e.g., `box-shadow: 0px 1px 3px ...`)
- `rgba(0,0,0,.1)` becomes `rgba(0, 0, 0, 0.1)` (with spaces and full decimal)
- Shorthand colors expand
- Hex codes stay as hex

If your fixture uses raw stylesheet syntax (`0 1px 3px`), the detector that matches normalized form (`0px 1px 3px`) will miss it. **Always model fixtures after a real captured CSS**, not what you'd type by hand.

Run the runner after every detect.py edit:

```bash
python scripts/test_checks.py                      # all L1 checks
python scripts/test_checks.py --check ai-slop/purple-gradient
python scripts/test_checks.py --category ai-slop
python scripts/test_checks.py --strict             # fail if any L1 check has no fixtures/
```

The runner discovers fixtures automatically; no registration step. Exit code 1 means at least one fixture mismatched its expected verdict — a logic regression. The output names the failing check, the fixture, the expected verdict, and what the detector actually said.

---

## The 10 manifest fields

Read `schemas/check-manifest.schema.json` for the formal definition. Below is the *intent* of each field, which the schema can't express.

| Field | Intent | Common mistake |
|---|---|---|
| `id` | `<category>/<name>`, lowercase kebab-case. Must match the on-disk path. The first segment IS the category — there is no separate `category` field. | Typo (`ai-slop/typoed` doesn't match `ai-slop/typoed-name/`). The validator catches it. |
| `name` | Short label shown in the dashboard. State what the check verifies, **not what fails**. | "purple gradient" (bad — sounds like a feature). "No purple/violet/indigo default gradient" (good — names the absence). |
| `band` | Top-level dashboard bucket: `ux` or `ui-risk`. `ux` = the user can understand / decide / act / recover. `ui-risk` = the UI shows risky, templated, or sloppy patterns that tend to degrade the experience. | Creating extra buckets. Keep it binary. |
| `subtype` | **Required when band == `ux`**, **forbidden when band == `ui-risk`**. One of: `understand` (can the user parse what they're seeing?), `decide` (can they decide what to do next?), `act` (can they execute the decision?), `recover` (can they recover when something goes wrong?). See [classification choice](#classification-choice). | Forgetting subtype on a `ux` check, or setting it on a `ui-risk` check. The validator catches both. |
| `method` | `L1-script` / `L2-script` / `L3-vision` / `L4-journey`. Must match the implementation file (`detect.py` / `run.mjs` / `prompt.md`). | Declaring `L2-script` and writing `detect.py`. The validator catches it. |
| `severity` | `critical` (blocks shipping) / `major` (should fix) / `minor` (polish). | Calling everything `major` because "it matters." Most checks are `minor`. Critical = WCAG AA blockers, broken core flow. |
| `source` | Citation chain from the [`sources.md`](../knowledge/sources.md) allow-list. Single-source is fine when one canonical anchor covers the check (e.g., Cooper Ch 11 for excise) or for self-evident anti-patterns. Cap at 3 citations joined with `+`; the validator warns at 4+. | Inventing a source the reader can't verify. Citing proprietary skills, tweets, blog posts, or popular frameworks (Hulick, Ellis, "aha moment"). Stacking 4+ design-system citations that all repeat the same Nielsen heuristic. |
| `description` | What the check inspects. Concrete and concise (1-3 sentences, ≤600 chars). | Marketing copy. Just say what the scanner does. |
| `rationale` | Why this matters, grounded in research. **No vague boost-words.** | "improves usability" (vague). Cite the specific principle and the concrete cost the user pays. |
| `pass_criteria` | What "pass" means, in measurable terms. **Two judges should agree from this string alone.** | Adjectives like "well", "good", "reasonable". Use thresholds: counts, ratios, ranges, exact patterns. |

The validator emits warnings when `source` exceeds 3 citations, `rationale` is adjective-heavy, or `pass_criteria` lacks thresholds. Warnings don't block — but each warning is a quality cost you accept. Single-source is allowed; what's not allowed is invention. See [`../knowledge/sources.md`](../knowledge/sources.md).

---

## Classification choice

Two axes determine where a check shows up in the dashboard:

**`band`** (required, 2 values):

| `band` | Use when |
|---|---|
| `ux` | The check is about whether a user can understand / decide / act / recover in this UI. Failing it means a real user gets stuck or confused. |
| `ui-risk` | The check flags templated, sloppy, or AI-slop UI patterns. Failing it doesn't necessarily block the user — it signals the team wasn't paying attention. |

**`subtype`** (required when band is `ux`, forbidden when band is `ui-risk`, 4 values):

| `subtype` | The user-flow question | Example checks |
|---|---|---|
| `understand` | Can I parse what I'm seeing at all? | `core-experience/value-prop-clarity`, `desirability/copy-craft`, `accessibility/font-hierarchy` |
| `decide` | Do I know what to do next? Which thing is the primary action? | `usability/visual-hierarchy`, `usability/empty-state-guidance`, `usability/excise-detection` |
| `act` | Can I actually execute the decision? Does the journey complete? | `accessibility/axe-core`, `core-experience/primary-journey`, `usability/first-time-user-experience` |
| `recover` | When something goes wrong, do I know what state I'm in and how to recover? | `usability/system-status-visibility` |

If you can't decide between two subtypes, prefer the **earlier** one in the flow (`understand` < `decide` < `act` < `recover`). A check that fails at "understand" matters more than one that fails at "act" because the user never gets that far.

---

## Method choice (L1 → L4)

Pick the cheapest method that can give a verdict. Don't pay for L3 vision when L1 regex works.

| Method | Use when | Avoid when |
|---|---|---|
| **L1-script** (`detect.py`) | The pattern has a deterministic textual / CSS fingerprint (specific hex codes, regex match, count thresholds). Cheap, fast, reproducible. | The verdict requires aesthetic judgment (e.g., "is this typography distinctive?"). |
| **L2-script** (`run.mjs`) | You need a real browser to evaluate (Playwright + axe-core, computed styles, runtime DOM measurements). Still deterministic, but needs the page actually rendered. | A simple regex on `rendered.html` would suffice. |
| **L3-vision** | The verdict requires looking at the screenshot and forming an aesthetic / gestalt judgment (visual craft, copy voice, delight moments). | A deterministic check would work. Vision is expensive and slow. |
| **L4-journey** | The verdict requires operating the app (clicking through a flow, completing a journey). | The state can be evaluated from a single capture. |

**Rule of thumb**: if your check can be expressed as "find pattern X in the captured artifact", it's L1 or L2. If it requires judgment about whether the result *feels* right, it's L3. If it requires *trying to do something* in the live app, it's L4.

---

## Exemplars

When adding a new check, **copy from one of these** rather than starting blank:

| Method | Best exemplar | Why |
|---|---|---|
| L1-script (text) | [`ai-slop/coming-soon-text/`](../../checks/ai-slop/coming-soon-text/) | Clean text-pattern detection with both English + Japanese support |
| L1-script (CSS) | [`ai-slop/purple-gradient/`](../../checks/ai-slop/purple-gradient/) | CSS gradient parsing, hex+rgb dual matching, balanced detail |
| L1-script (DOM scan) | [`ai-slop/shadcn-signature/`](../../checks/ai-slop/shadcn-signature/) | Class-attribute scanning with multiple signatures + threshold |
| L2-script | [`accessibility/axe-core/`](../../checks/accessibility/axe-core/) | Playwright + axe-core via the shared `_target.mjs` helper |
| L3-vision | [`desirability/visual-craft/`](../../checks/desirability/visual-craft/) | Vision prompt with explicit rubric and forbidden context-leak rules |
| L4-journey | [`core-experience/primary-journey/`](../../checks/core-experience/primary-journey/) | Computer-use journey with success criteria and step waypoints |

The cheapest way to add a check is: `cp -r checks/ai-slop/purple-gradient/ checks/ai-slop/your-new-check/` and edit. The validator will tell you what's wrong.

---

## detect.py contract (L1)

Every L1 detect.py:

1. Imports `run_detect` and `write_result` from `check_lib` via the standard path-insert (see any existing example)
2. Defines `def detect(*, manifest, target, evidence_dir, output_path):`
3. Reads from `target` dict — keys: `rendered.html`, `visible-text.txt`, `stylesheets.css`, `computed-styles.json`, `meta`
4. Calls `write_result(output_path, manifest, result="pass"|"fail"|"skipped"|"error", details=..., matches=..., suggestion=..., confidence=0.0..1.0)`
5. Ends with `if __name__ == "__main__": run_detect(detect)`

The shared helper handles argparse, error handling, and consistent result schema. **Do not bypass it.** If you need extra capability (e.g., loading a custom evidence file), extend `check_lib.py`, not your detect.py.

`details` should describe what was scanned. `matches` is a list of dicts (each with `type`, `matched_text`, optional `count`/`indicators`/etc.) used by the dashboard. `suggestion` is the actionable fix shown to the developer; write it as plain language, not jargon.

---

## prompt.md contract (L3 / L4)

The prompt is read by a Judge subagent. It MUST:

1. State the goal in one sentence
2. Provide a measurable rubric (the same `pass_criteria` from `check.json`, expanded)
3. Explicitly forbid reading `project-context.json`, `spec.md`, `README.md`, or any project file (the rationalization gate — see [`../concepts/architecture.md`](../concepts/architecture.md))
4. Tell the Judge to write its verdict to the path the orchestrator gives it, in the standard `result.json` schema (including `band`)
5. State the evidence-file policy explicitly: L3 should usually attach `0` or `1` supporting screenshot/crop only when it materially helps; L4 should attach ordered journey waypoints

The prompt may NOT:
- Reference the check's `rationale` (Judges should evaluate, not justify)
- Allow looking at the spec (rationalization)
- Use vague directives ("evaluate the design quality") — the rubric must be measurable
- Encourage dumping multiple decorative screenshots into `evidence.files`

---

## Validator

```bash
python scripts/validate_checks.py                # validate everything
python scripts/validate_checks.py --strict       # warnings become errors
python scripts/validate_checks.py --json         # machine-readable
python scripts/validate_checks.py --quiet        # silent on success
```

The validator runs **automatically** as a pre-flight gate inside `run_all_checks.py`. You can bypass with `--skip-validate`, but don't — that's the moment a malformed check ships.

The validator catches:
- **Schema violations**: missing/extra fields, wrong types, enum mismatches, length bounds, regex patterns
- **Structural mismatches**: id ≠ path, missing implementation file for declared method, subtype set on a `ui-risk` check (or missing on a `ux` check)
- **Soft signals**: too-many-source citations (4+), vague rationale (warning), adjective-heavy pass_criteria (warning)

Errors block the run. Warnings surface but don't block — they're the "next time, do better" lane.

---

## Common mistakes (from real review history)

1. **Invented or unverifiable citations**: proprietary skills, tweets, blog posts, fabricated arXiv papers, popular frameworks (Hulick, Ellis, "aha moment"). The rule isn't "cite everything," it's **don't invent**. See [`../knowledge/sources.md`](../knowledge/sources.md) for the allow-list.
2. **id mismatch**: Renamed the directory but forgot to update `id` inside check.json. The validator errors.
3. **method ↔ implementation mismatch**: Declared `L2-script` and wrote `detect.py`. The validator errors.
4. **Vague pass_criteria**: "Shows a distinctive visual identity" → two judges disagree. Express it in counts/ratios/ranges. The validator warns.
5. **Wrong subtype**: putting a tap-target check in `understand` because "you can't read it." Tap target is about whether you can `act` on the decision. The earlier-in-flow rule is a tiebreaker, not an excuse to push every check to `understand`.
6. **Threshold of 1**: a single match shouldn't fail unless you're highly confident. Most pattern checks need 2+ to clear false positives. shadcn-signature uses 2, emoji-as-icon uses 3, dark-toggle uses 6.
7. **Forgetting to test against a real capture**: the new check passes the validator and your slop fixture, but errors silently on a real project capture. Always smoke-test against `.agents/uxaudit/slop-app/iteration-N/target/` AND a real product capture before declaring done.

---

## Adding a check, end-to-end checklist

```
[ ] Identified the pattern in ≥3 real projects?
[ ] Found a verifiable source from the [`sources.md`](../knowledge/sources.md) allow-list (or the check is a self-evident anti-pattern)?
[ ] Picked the right band + subtype (or null subtype if `ui-risk`)? Picked the cheapest method that works?
[ ] Copied an exemplar from the table above (don't start blank)
[ ] Wrote check.json — id matches path, all required fields present, source is from the allow-list
[ ] Wrote the implementation file (detect.py / run.mjs / prompt.md) matching method
[ ] Ran scripts/validate_checks.py — 0 errors, 0 warnings
[ ] (L1 only) Created fixtures/fail/ and fixtures/pass/ — ran scripts/test_checks.py and got 2 ok
[ ] Smoke-tested negative case (real product capture) — passes as expected
[ ] Confirmed the new check appears in `discover_checks(only="<category>")`
```

If all 10 boxes are checked, the check is ready. Otherwise, fix what's broken before merging.
