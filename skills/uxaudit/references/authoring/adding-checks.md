# Adding new checks (worked walkthroughs)

This file shows **end-to-end working examples** for each check method (L1, L2, L3, L4). For the contract, validation rules, and field semantics, read [`check-authoring.md`](./check-authoring.md) first — that's the source of truth.

uxaudit is **trivially extensible**: the catalog is just a directory of `checks/<category>/<check-name>/` folders, each one self-contained. There is no central registry to update — `aggregate.py` and `run_all_checks.py` discover checks by walking the filesystem, and `validate_checks.py` enforces the manifest schema as a pre-flight gate.

## The 30-second mental model

```
checks/<category>/<check-name>/
├── check.json          ← REQUIRED (schema-validated)
└── detect.py | run.mjs | prompt.md   ← ONE of these depending on `method`
```

`check.json` declares **what** the check measures. The implementation file declares **how** to measure it. The validator pairs them.

## Validate before you write

```bash
python scripts/validate_checks.py
```

Run this after every edit. It catches typos, missing implementation files, enum violations, and id-vs-path mismatches before the orchestrator spends time running anything. The validator also runs automatically as a pre-flight gate inside `run_all_checks.py`.

## check.json schema (10 fields)

| Field | Type | Notes |
|---|---|---|
| `id` | string, `<category>/<name>` | Must match the on-disk path. Lowercase kebab-case. The category is the first segment of `id`; the directory layout is the single source of truth and there is no separate `category` field. |
| `name` | string, 6-120 chars | Short label for the dashboard. |
| `band` | enum | `ux` / `ui-risk`. Top-level dashboard bucket. |
| `subtype` | enum, conditional | `understand` / `decide` / `act` / `recover`. **Required when band is `ux`, forbidden when band is `ui-risk`.** |
| `method` | enum | `L1-script` / `L2-script` / `L3-vision` / `L4-journey` |
| `severity` | enum | `critical` / `major` / `minor` |
| `source` | string 8-400 | Citation from the [`sources.md`](../knowledge/sources.md) allow-list. Single-source is fine when one canonical anchor covers the check; cap at 3 joined with `+`. |
| `description` | string 20-600 | What the check inspects. Concrete, not marketing. |
| `rationale` | string ≥40 | Why it matters, grounded in research. **No vague boost-words.** |
| `pass_criteria` | string ≥20 | Measurable definition of "pass". Two judges should agree from this string alone. |

The full schema is at [`schemas/check-manifest.schema.json`](../../schemas/check-manifest.schema.json).

## Choosing a method (L1 → L4)

Pick the cheapest one that can answer your question.

| Method | Use when... | Implementation file |
|---|---|---|
| **L1-script** | Pattern is a deterministic regex / CSS / DOM scan over the captured artifacts. | `detect.py` |
| **L2-script** | You need a real browser (Playwright + axe-core, computed styles, runtime measurements). | `run.mjs` |
| **L3-vision** | Verdict needs aesthetic / gestalt judgment from a screenshot. | `prompt.md` (vision subagent) |
| **L4-journey** | Verdict requires *operating* the app across multiple steps. | `prompt.md` (pixel-only journey Judge) |

Rule of thumb: if you can grep it, use L1. If you need the page rendered, use L2. If a human would only know by looking, L3. If they'd only know by clicking, L4.

---

## Walkthrough A — L1 (script) check

Goal: detect any visible "TODO" token in user-facing copy.

**Step 1.** Copy an existing exemplar to start from.

```bash
cp -r checks/ai-slop/coming-soon-text/ checks/ai-slop/todo-text/
```

**Step 2.** Edit `checks/ai-slop/todo-text/check.json`.

```json
{
  "id": "ai-slop/todo-text",
  "name": "No 'TODO' in user-visible copy",
  "band": "ui-risk",
  "method": "L1-script",
  "severity": "minor",
  "source": "Krug DMMT Law #3 ('half the words')",
  "description": "Scans the rendered visible text for a literal 'TODO' token outside script/style. Each occurrence indicates an unfinished label that escaped to production.",
  "rationale": "Visible 'TODO' tokens advertise the product's incompleteness to the visitor in the first second. Krug's Law #3 (cut half the words) treats noise like this as the highest-priority deletion target — every visible TODO is a token the user must scan past, costing attention without paying it back.",
  "pass_criteria": "No occurrence of the literal token 'TODO' (case-sensitive, word-bounded) in the visible text extracted from rendered.html."
}
```

**Step 4.** Edit `checks/ai-slop/todo-text/detect.py`.

```python
#!/usr/bin/env python3
"""Detect a literal 'TODO' token in user-visible copy."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

TODO_RE = re.compile(r"\bTODO\b")


def detect(*, manifest, target, evidence_dir, output_path):
    text = target.get("visible-text.txt") or ""
    if not text:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No visible-text.txt captured.",
        )
        return

    matches = [m.group(0) for m in TODO_RE.finditer(text)]
    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No 'TODO' tokens in visible copy.",
        )
        return

    write_result(
        output_path, manifest,
        result="fail",
        confidence=0.95,
        details=f"Found {len(matches)} 'TODO' token(s) in user-visible text.",
        matches=[{"type": "text", "matched_text": m} for m in matches[:10]],
        suggestion="Replace each TODO with the real label, or remove the element entirely if the feature isn't built yet. A missing element is honest; a TODO is a stub that lies.",
    )


if __name__ == "__main__":
    run_detect(detect)
```

**Step 5.** Validate.

```bash
python scripts/validate_checks.py
```

If the validator passes, the check is wired. `run_all_checks.py` will auto-discover it on the next run.

### L1 detect.py contract (binding)

- Import `run_detect` and `write_result` from `check_lib` via the standard `sys.path.insert` shown above. Do not import `emit_result` or `visible_text` — those don't exist.
- Define `def detect(*, manifest, target, evidence_dir, output_path):`
- Read from `target` dict — keys: `rendered.html`, `visible-text.txt`, `stylesheets.css`, `computed-styles.json`, `meta`
- Call `write_result(output_path, manifest, result="pass"|"fail"|"skipped"|"error", details=..., matches=..., suggestion=..., confidence=0.0..1.0)`
- End with `if __name__ == "__main__": run_detect(detect)`

The shared helper handles argparse, error wrapping, and consistent result schema. **Do not bypass it.**

---

## Walkthrough B — L2 (DOM) check

Goal: every form input must have a visible label.

**check.json:**

```json
{
  "id": "accessibility/input-labels",
  "name": "Every form input has a visible label",
  "band": "ux",
  "subtype": "act",
  "method": "L2-script",
  "severity": "major",
  "source": "WCAG 2.1 SC 3.3.2 (Labels or Instructions, https://www.w3.org/TR/WCAG21/#labels-or-instructions)",
  "description": "Walks every <input>, <select>, and <textarea> in the live DOM and checks for an associated <label>, aria-label, or aria-labelledby. Hidden inputs are skipped.",
  "rationale": "Unlabeled form fields are unusable for screen readers (assistive tech announces only the field type, not its purpose) and ambiguous for sighted users when placeholder text disappears on focus. WCAG 2.1 SC 3.3.2 makes labeling a level-A requirement; failing it locks out users who depend on assistive tech and degrades clarity for everyone.",
  "pass_criteria": "Every visible <input>, <select>, and <textarea> has at least one of: an associated <label for=...>, an aria-label attribute, or an aria-labelledby attribute pointing to a visible element. Zero unlabeled inputs allowed."
}
```

**run.mjs:**

```js
#!/usr/bin/env node
// L2 check: every form input needs a label.
import { openTarget, closeTarget, getArg, hasFlag } from "../../../scripts/_target.mjs";
import { writeFileSync } from "node:fs";

const url = getArg("--url");
const electronApp = getArg("--electron-app");
const viewport = getArg("--viewport");
const outputPath = getArg("--output");
const manifestPath = getArg("--manifest");

const manifest = JSON.parse((await import("node:fs")).readFileSync(manifestPath, "utf8"));

const handle = await openTarget({ url, electronApp, viewport });
const { page } = handle;

const unlabeled = await page.$$eval("input, select, textarea", (els) =>
  els
    .filter((el) => el.type !== "hidden" && el.offsetParent !== null)
    .filter((el) => {
      const id = el.id;
      const labelFor = id && document.querySelector(`label[for="${id}"]`);
      const wrapping = el.closest("label");
      return !labelFor && !wrapping &&
             !el.getAttribute("aria-label") &&
             !el.getAttribute("aria-labelledby");
    })
    .map((el) => ({
      tag: el.tagName.toLowerCase(),
      name: el.name || el.id || "(unnamed)",
    }))
);

await closeTarget(handle);

const result = unlabeled.length === 0
  ? {
      result: "pass",
      confidence: 1.0,
      evidence: { details: "All visible form inputs have an accessible label.", matches: [], files: [] },
    }
  : {
      result: "fail",
      confidence: 0.95,
      evidence: {
        details: `${unlabeled.length} form input(s) have no accessible label.`,
        matches: unlabeled.slice(0, 20).map((u) => ({ type: u.tag, matched_text: u.name })),
        files: [],
      },
      suggestion: "Wrap each input in a <label>, add an aria-label, or point an aria-labelledby at a visible element. Placeholder-only fields fail this check.",
    };

writeFileSync(outputPath, JSON.stringify({
  check_id: manifest.id,
  ...result,
}, null, 2));
```

`result.json` is **verdict-shaped** — only `check_id`, `result`, `evidence`, and (when failing) `suggestion`. Catalog metadata (`name`, `band`, `subtype`, `method`, `severity`, `source`, `rationale`, `pass_criteria`) lives in `check.json` and is joined into the dashboard record by `aggregate.py` after the run. Don't copy catalog fields into result.json — it's the duplication this whole separation exists to prevent.

The L2 helper `_target.mjs` handles browser launch, viewport presets, mobile UA, and Electron mode. Use `openTarget()` / `closeTarget()` rather than calling `chromium.launch()` directly so viewport / Electron support stays consistent across checks.

For a real production example see [`checks/accessibility/axe-core/run.mjs`](../../checks/accessibility/axe-core/run.mjs).

---

## Walkthrough C — L3 (vision) check

Goal: judge whether the page presents one unambiguous primary CTA.

**check.json:**

```json
{
  "id": "usability/visual-hierarchy",
  "name": "Clear visual hierarchy and primary CTA",
  "band": "ux",
  "subtype": "decide",
  "method": "L3-vision",
  "severity": "major",
  "source": "Krug DMMT Ch3 'Billboard Design 101' + NN/g First Impressions / 50ms (https://www.nngroup.com/articles/first-impressions-human-automaticity/)",
  "description": "A vision-LLM looks at the captured screenshot and judges whether ONE element is unambiguously the visual primary action — the element a first-time visitor's eye would land on within 50ms.",
  "rationale": "Krug's 'Billboard Design 101' argues that scanning depends on the page communicating its hierarchy in the first second. Lindgaard's 50ms first-impression research shows that users form aesthetic+hierarchy judgments before they consciously read anything. When two or more elements compete for first-fixation, the page is asking the user to think — exactly what Krug's Law #1 forbids.",
  "pass_criteria": "Exactly one visible interactive element is the unambiguous first-fixation target — visually dominant in size, color, or contrast relative to all other actions on the page. Two or more competing elements of equal weight fail."
}
```

**prompt.md:**

```markdown
You are a vision-LLM Judge for the uxaudit `usability/visual-hierarchy` check.

You will receive ONE screenshot. You must NOT read project-context.json, README, spec, or any project file. Evaluate as a first-time visitor seeing the page for the first time.

## Pass criterion (the only thing that matters)

Exactly one visible interactive element is the unambiguous first-fixation target. Two or more competing buttons of equal weight fail.

## How to evaluate

1. Look at the screenshot for ≤5 seconds.
2. Identify the single element your eye lands on first.
3. Identify the single primary CTA the page most wants you to click.
4. Pass if (2) and (3) are unambiguous AND match each other. Fail if multiple elements compete for first-fixation OR if there is no clear primary action.

## Output

Use the orchestrator-provided write helper to emit `result.json` with the standard schema. The orchestrator will tell you the exact output path.

The result must include:
- `band`: copied verbatim from `check.json`
- `result`: "pass" | "fail"
- `confidence`: 0.0–1.0
- `evidence.details`: 1–2 sentences describing what you saw
- `evidence.matches`: list of `{type, matched_text}` for: first-fixation element, primary-cta element, any competing-primary elements
- `evidence.files`: `[]` by default, or one supporting screenshot/crop if it materially clarifies the verdict
- `suggestion`: 1 sentence on how to make the hierarchy unambiguous (only if failing)

## Forbidden

- Do NOT read project-context.json, README, spec.md, or any project file
- Do NOT use the rationale to justify a pass — your only job is to apply the pass_criterion to what you see
- Do NOT pass on hope ("the design probably intends X")
```

The orchestrator dispatches a vision-enabled subagent with the screenshot and this prompt. The subagent writes `result.json` to the path the orchestrator provides. **The subagent isolation rule is non-negotiable** — see [`../concepts/architecture.md`](../concepts/architecture.md) for why.

Keep L3 evidence files minimal. The dashboard opens them on demand, so one supporting crop is useful; a gallery is noise.

---

## Walkthrough D — L4 (journey) check

Same shape as L3, but the prompt instructs a pixel-only journey Judge to *operate* the app over multiple steps, capturing waypoint screenshots into `evidence_dir/01-initial.png`, `02-...png`, ..., `99-final.png`. The Judge should prefer Playwright when it can directly own the runtime and escalate to `computer-use` only when the interaction leaves that runtime. See [`checks/core-experience/primary-journey/prompt.md`](../../checks/core-experience/primary-journey/prompt.md) for a complete example with success criteria, anti-cheating rules, and the evidence-naming convention.

The orchestrator passes journey context (starting URL, success criteria, steps_hint) from `project-context.json` into the prompt as variables, but the journey check's prompt itself MUST NOT read project-context.json or any other project file directly.

---

## Severity guide

| Severity | Use for |
|---|---|
| **critical** | Failure blocks the user from doing anything (e.g., axe-core critical, value-prop unintelligible, primary CTA broken) |
| **major** | Failure makes the experience worse but the user can recover (low contrast on body text, vague button labels, unlabeled forms) |
| **minor** | Failure is a polish issue (generic font stack, lorem ipsum in a tooltip, default Tailwind shadow) |

The dashboard sorts failures by severity. Calibrate against existing checks before assigning — most ai-slop checks are `minor` because they're polish; most accessibility checks are `major` or `critical` because they lock users out.

## Citing sources (don't invent)

Every judgment-call check is anchored in a publicly-verifiable source from the [`../knowledge/sources.md`](../knowledge/sources.md) allow-list. The rule is **don't invent**, not "cite everything." Self-evident anti-patterns (lorem ipsum, "Coming soon" stubs, "John Doe" placeholder data) ship without an academic anchor because they aren't judgment calls.

Single-source is fine when one canonical anchor covers the check (e.g., Cooper Ch 11 for excise-detection). Cap at 3 joined with `+`; the validator warns at 4+. Examples that work:

- `"WCAG 2.1 SC 1.4.3 (Contrast Minimum)"`
- `"Krug DMMT Law #3 ('half the words')"`
- `"NN/g 'AI Prototyping in Real Design Contexts' (nngroup.com/articles/ai-prototyping/)"`
- `"ISO 9241-11:2018 Effectiveness + Nielsen's 10 Usability Heuristics #5 (error prevention)"`

What's NOT accepted as a `source`: proprietary or internal guidance (vendor skills, internal style guides), tweets and social posts, single-author blog posts without peer review, popular frameworks without empirical grounding (Hulick, Sean Ellis, "aha moment"), and stacking 4+ design-system citations that all repeat the same Nielsen heuristic. See [`../knowledge/sources.md`](../knowledge/sources.md) for the full rule and the allow-list.

If you cannot anchor a judgment-call check in the allow-list, the check is probably an opinion rather than a heuristic. Park it until you find a real anchor.

## Done checklist

Before declaring a new check ready:

```
[ ] Copied an exemplar (don't start blank)
[ ] check.json: id matches path, all 10 fields present (subtype only when band==ux), source from the allow-list
[ ] Implementation file exists (detect.py / run.mjs / prompt.md) for declared method
[ ] python scripts/validate_checks.py → 0 errors, 0 warnings
[ ] Smoke-tested positive case (synthetic fixture or known-bad capture) → fails
[ ] Smoke-tested negative case (real product capture) → passes
[ ] discover_checks(only="<category>") returns the new check
```

For the contract / quality bar / common mistakes, see [`check-authoring.md`](./check-authoring.md).
