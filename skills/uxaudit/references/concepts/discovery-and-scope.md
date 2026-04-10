# Discovery, scope, and the limits of UX evaluation

This document answers the hard questions about uxaudit: how it discovers what to evaluate, what it can and cannot judge, and when to use it for whole-app vs feature-scope vs journey-chain evaluation.

## Part 0 — The framing: hypothesis synthesis, not deterministic discovery

A user's actual journey through a product is not deterministically derivable from source code. README, routes, and even e2e tests encode the team's *declared* intent and the *implementation surface* — they don't encode where users actually enter, what they consider first value, or where they get confused. Those are emergent properties of real use, and the Scout cannot read them from disk.

Treat the Scout's `project-context.json` as **an evidence-based hypothesis about what the product is for**, not as ground truth. Three things follow from this:

1. **Every journey carries an evidence basis.** Each entry in `primary_journeys` and `experience_model.jobs` records what it was derived from (`e2e`, `scenario-doc`, `route`, `readme`, `category-baseline`, `jtbd`, `external-research`) and at what confidence level. The downstream pipeline can then weight a fail differently when it lands on a low-confidence hypothesis vs a high-confidence one. A "fail" against a journey backed only by JTBD inference is not the same kind of fail as one backed by an e2e test the team actually runs in CI.

2. **Coverage gaps are surfaced, not silenced.** If the Scout cannot honestly hit a journey count for the project's category, it says so in `discovery_notes` and `experience_model.open_questions`. "We could only find 2 journeys" is more useful than "here are 5 journeys, 3 of them invented." The downstream cannot weight what it cannot see.

3. **The hypothesis becomes a contract by being locked.** `--scenario-mode locked` reuses a previous iteration's `project-context.json` as a fixed **scenario contract**. From that point on, subsequent iterations are **regression runs** against the same measuring stick: the question shifts from "did the Scout discover the right journeys this time?" to "did the same journeys, evaluated the same way, get better or worse since the previous iteration?". `refresh` discards the lock and re-synthesizes (use after major IA / product changes). `hybrid` (the default) keeps the lock but lets the Scout add new candidates without breaking comparability.

Read this whole document with that frame in mind. Everything below — the priority order, the journey count floors, the chain semantics — is the *machinery* that turns a synthesis into a usable contract. The machinery exists because the synthesis cannot be made deterministic, not because we've given up on determinism.

## Part 1 — How journey hypotheses are synthesized

The Scout subagent walks the cwd in this priority order. Higher sources are more reliable because they encode the team's *declared* intent. None of them encode actual user behavior — that's the hypothesis layer, and the Scout makes its uncertainty explicit via `evidence_basis` and `confidence`.

| Priority | Source | Why it's reliable | Limit |
|---|---|---|---|
| 1 | `tests/e2e/`, `playwright/`, `cypress/` | Recorded user flows the team actually validates against | Tests cover happy paths only; unhappy paths and friction are invisible |
| 2 | `docs/user-journeys.md`, `docs/scenarios.md`, `harness/state/scenarios.md` | Hand-written scenarios encode product-team intent | Often stale; the team writes them once and forgets |
| 3 | Route definitions in code (`pages/`, `app/`, `routes.ts`, FastAPI/Django/Rails route files) | Source-of-truth for what URLs exist | Routes exist != users use them |
| 4 | `README.md`, `docs/spec.md`, `harness/state/spec.md` | States the product's purpose and target audience | "Purpose" rarely contains step-by-step flows |
| 5 | **Category baselines** (`../knowledge/category-baselines.md`) | Standard journey set for the app's category, validated by the category leaders | Generic — may miss the app's unique value |
| 6 | JTBD inference from README nouns/verbs | Last-resort reasoning | Speculation |

The Scout combines these into `project-context.json` with a `discovery_notes` field documenting what it found vs inferred. **The orchestrator should always read those notes before trusting the journey list.**

### Route discovery (added)

The Scout now also searches for route patterns in source code, not just docs:

- **Next.js**: `pages/**/*.{js,jsx,ts,tsx}`, `app/**/page.{js,jsx,ts,tsx}` (App Router)
- **React Router**: `<Route path="...">` patterns in `*.tsx`
- **Vue/Nuxt**: `pages/**/*.vue`
- **SvelteKit**: `src/routes/**/+page.svelte`
- **Astro**: `src/pages/**/*.astro`
- **FastAPI**: `@app.get("...")`, `@router.get("...")`
- **Django**: `urls.py` `path()` calls
- **Rails**: `config/routes.rb` `get/post/resources` declarations
- **Express**: `app.get/post/...("path", ...)` patterns
- **Hono / Elysia**: similar patterns

Each discovered route becomes a candidate destination for journey definition. The Scout filters routes that look like API endpoints (return JSON only, named `/api/*`) and keeps the ones that render UI.

The Scout should also emit an `experience_model` (see [`experience-model.md`](./experience-model.md)) so downstream evaluation can distinguish:

- what must be understood quickly
- what decisions are legitimate
- what should be defaulted / automated
- what counts as progress
- where recovery matters

When multiple jobs are present, journeys should point back to them with `job_ids` rather than collapsing the whole product into one generic main flow.

## Part 2 — How many journeys is enough

Empirical floor for a meaningful evaluation:

| Product type | Minimum journeys | What they cover |
|---|---|---|
| **Marketing landing page** | 2 | (a) read & understand value prop, (b) take primary CTA |
| **CRUD app (todo, notes, expenses)** | 4 | (a) onboard, (b) create, (c) edit, (d) delete with undo |
| **Two-sided marketplace** | 6 | (a) buyer browse, (b) buyer purchase, (c) seller list, (d) seller fulfill, (e) buyer review, (f) dispute resolve |
| **Social / content platform** | 6–8 | (a) discover, (b) consume, (c) save, (d) share, (e) post/upload, (f) settings/privacy |
| **SaaS team tool** | 6–10 | (a) onboard solo, (b) invite teammate, (c) main work loop, (d) collaborate, (e) export/integrate, (f) admin/billing |
| **Complex platform (Spotify, Notion)** | 10–20+ | Multiple chained discover→consume→save→share loops, plus admin, settings, social |

**Diminishing returns kick in around 7–10 journeys.** Beyond that, you're better off chaining existing journeys than adding new ones.

If the Scout produces fewer than these floors, **the right move is to surface the gap explicitly**, not to silently invent the missing entries. The Scout writes the shortfall into `discovery_notes` and `experience_model.open_questions`, marks the journeys it did synthesize with their actual `confidence`, and lets the downstream weight the result accordingly. A two-journey audit honestly labelled "we could not find evidence for the other 5" is more useful than a five-journey audit where 3 are JTBD speculation pretending to be ground truth.

## Part 3 — Journey chains (the connecting flows)

Real product experiences are not isolated tasks; they are chains. The Spotify example:

```
discover-music ─→ play-music ─→ save-to-playlist ─→ share-playlist
                       │
                       └─→ adjust-quality ─→ download-offline
```

The current schema supports this via `next_journey` pointers and a `previous_journey.success_state` starting URL:

```json
{
  "primary_journeys": [
    {
      "id": "discover",
      "name": "Discover new music",
      "starting_url": "/",
      "success_criteria": "user is viewing a track detail page",
      "next_journey": "play"
    },
    {
      "id": "play",
      "name": "Play the discovered track",
      "starting_url": "@discover.success_state",
      "previous_journey": "discover",
      "success_criteria": "audio is playing and the playback bar is visible",
      "next_journey": "save"
    },
    {
      "id": "save",
      "name": "Save to a playlist",
      "starting_url": "@play.success_state",
      "previous_journey": "play",
      "success_criteria": "the track shows a 'saved' state and appears in 'My Library'"
    }
  ]
}
```

The L4 dispatcher walks the chain in order, carrying state forward. Each link is scored independently AND the chain as a whole gets a verdict (did the user reach the chain's end?). Breaks at any link fail the chain.

## Part 4 — First-time vs returning user

These are different evaluations. Currently the catalog assumes "first-time visitor" by default. Three explicit context modes:

| Mode | When to use | What changes |
|---|---|---|
| **cold-start** | First-time user, no cookies, no account | Computer-use opens an incognito context. Empty data. Onboarding flows must work. |
| **returning** | Logged-in user, populated data | Skip onboarding. Test the actual work loop. |
| **power-user** | Returning user with realistic-volume data | Test scale, density, search/filter, keyboard shortcuts |

The Scout inference picks the mode from the journey: a "first time" journey runs cold-start; a "weekly planning" journey runs returning. The orchestrator playbook documents which is which.

**Important first-time-user-only checks:**
- Onboarding completion rate
- Empty state guidance (already exists as `usability/empty-state-guidance`)
- Time-to-first-value (clicks until the user accomplishes something meaningful)
- Account creation friction
- Permission requests timing

These aren't all built yet — see the catalog status table.

## Part 5 — Whole-app vs feature-scope evaluation

Two distinct modes the orchestrator supports:

### Whole-app mode (default)

```bash
/uxaudit <target> --url http://localhost:5173
```

- Captures the home / entry URL
- Runs the entire catalog against that single page
- Uses Scout-discovered journeys for L4
- Tells you the overall floor of craft + the main journey health

Use when: you want a holistic snapshot, post-launch audit, periodic health check.

### Feature-scope mode

```bash
/uxaudit <target> --url http://localhost:5173 \
  --scope feature \
  --feature-name "playlist sharing" \
  --feature-url /playlist/123/share \
  --reference-urls /,/library,/settings
```

- Captures the FEATURE URL specifically
- Captures 2–3 reference URLs from the existing app for consistency baseline
- Runs catalog L1/L2 on the feature page only
- Dispatches L3-vision Judges with the feature page **plus** the references, asking:
  - Does this feature feel consistent with the rest of the app? (`usability/feature-consistency`)
  - Are there unnecessary steps in this feature's flow? (`usability/excise-detection`)
  - Does the new feature have its own clear primary action? (existing `usability/visual-hierarchy`)
  - Is the new feature's copy in the same voice? (existing `desirability/copy-craft`)
- Optionally dispatches L4 with the feature's specific journey
- Outputs a "feature audit" dashboard variant

Use when: you've added or refactored a feature, you want to know if it fits, and you want to know if any steps could be cut.

### Diff mode (future, not yet built)

```bash
/uxaudit <target> --url ... --scope diff --git-base main
```

Reads the git diff between current branch and `main`, identifies which routes/components were touched, and runs feature-scope evaluation on JUST those. Closes the loop with PR review.

## Part 6 — Cooper's excise: detecting unnecessary work

Alan Cooper (*About Face*) defines **excise** as "work the user must do that does not directly serve their goal." Common excise:

| Excise pattern | Example | Fix |
|---|---|---|
| **Confirmation on reversible actions** | "Are you sure you want to mark as read?" | Just do it; offer undo |
| **Modal interruption mid-task** | "Quick — rate this app!" while user is checking out | Never interrupt active tasks |
| **Required fields that should be optional** | "Phone number *" on a newsletter signup | Mark optional or remove |
| **Multi-step where one step works** | Wizard for 3 inputs | Single form |
| **Acknowledgment of trivial actions** | "✓ Saved" toast for an autosaved field | Subtle inline state, no toast |
| **Re-asking for known info** | "What's your email?" after login | Pre-fill from session |
| **Forced account creation** | "Sign up to read more" on a content site | Allow guest read |
| **Cookie consent that blocks reading** | Full-screen consent before any content | Bottom banner, defer until interaction |
| **Decorative animations on every action** | Confetti for clicking "save" | Reserve for genuine moments |
| **Cluttered settings** | 50 toggles when 5 matter | Default sensibly, hide the rest |

The new check `usability/excise-detection` (L3-vision) scans for these. Per-instance, in concrete terms.

## Part 7 — The "Spotify quality" gap — what we can and can't evaluate

This is the hardest question and deserves an honest answer.

### What we CAN evaluate today

| Capability | Method | Confidence |
|---|---|---|
| **Catalog floor** — does it avoid AI slop, follow WCAG, pass Nielsen heuristics | L1/L2/L3 catalog | High |
| **Specific task completion** — can a user complete a defined journey | L4 pixel-only journey evaluation | High when journey is well-defined |
| **Visual craft level** — does it look templated or designed | L3-vision (`desirability/visual-craft`) | Medium-high |
| **Copy specificity** — is the language vague or concrete | L3-vision (`desirability/copy-craft`) | High |
| **Value prop clarity** — 5-second test | L3-vision (`core-experience/value-prop-clarity`) | High |
| **Excise / wasted steps** | L3-vision (new `usability/excise-detection`) | Medium |
| **Delight moments** | L3-vision (new `desirability/delight-moments`) | Medium — biased toward visible delight |
| **Consistency with existing app** | L3-vision (new `usability/feature-consistency`) | Medium |
| **Comparison to a reference** | L3-vision with reference screenshot in context | Medium-high |

### What we CANNOT evaluate (be honest)

| Limitation | Why | Alternative |
|---|---|---|
| **Long-term retention** — would users keep using this in 6 months | One session can't see this | Real product analytics, cohort retention curves |
| **Emotional resonance over time** — does the app build loyalty | Subjective, longitudinal | User interviews, NPS, qualitative research |
| **Word-of-mouth quality** — would users recommend it | Cultural / social signal | Net Promoter Score, social listening |
| **Cultural fit** — does the brand voice land in the target market | Requires market context | Localized user testing |
| **Habit formation** — does this become part of user routine | Requires weeks of observation | Behavior cohort analysis |
| **True intuition** — "this just feels right" | Tacit, not cognitive | Senior designer review |

### The honest claim

uxaudit can get you to "this clearly avoids the AI-slop floor, completes its main tasks, has a clear value prop, and shows evidence of craft." That covers maybe 70% of what makes an app feel good. The remaining 30% — sustained delight, emotional resonance, habit formation — needs real users and time.

**The skill's job is to eliminate the obvious failures so the remaining 30% has a chance to matter.** A poorly-crafted app with retention problems can't tell whether the retention problem is the craft or the product. uxaudit closes off the craft excuse.

The multiplier on top of the catalog is **project-shaped evaluation against a locked scenario contract**. Fixed catalog checks are necessary but not sufficient; the Scout's `experience_model`, once locked, is what lets uxaudit ask better questions for *this* app — and ask them the same way every iteration so iter-to-iter comparison actually means something. The Scout's job is not to be the oracle of "what this product is for"; it is to assemble the best evidence-based hypothesis available at this point in time and hand it to the human (or to `--scenario-mode locked`) to decide whether to ratify it as the contract.

## Part 8 — Recommended workflow per project

A concrete recipe for how to use this skill across the lifecycle.

### Phase 1 — Initial build
1. Run `/uxaudit <target>` against the first deployable build
2. Get the catalog floor score
3. Fix anything in **Action required** until pass rate ≥ 80% on the `ux` band
4. Save the dashboard as the v0 baseline

### Phase 2 — Ratify the scenario contract
1. Open `project-context.json` and review the Scout's **journey hypothesis**: which journeys it found, what `evidence_basis` and `confidence` each carries, and what's listed in `experience_model.open_questions`
2. Edit the file directly to fix wrong inferences, add the journeys the Scout missed, and downgrade or remove anything that turned out to be speculation
3. Identify which journeys CHAIN (the Spotify pattern) and add `next_journey` pointers
4. Tag each journey as `cold-start`, `returning`, or `power-user`
5. Re-run with `--scenario-mode locked` to **ratify the edited file as the scenario contract** for this project. Subsequent iterations now regress against this contract instead of re-synthesizing

### Phase 3 — Per-feature iteration
1. For each new feature: `/uxaudit <target> --scope feature --feature-url ... --reference-urls ...`
2. Read the feature audit
3. Specifically check: excise-detection findings, feature-consistency findings
4. Fix before merging

### Phase 4 — Periodic health check
1. Weekly or monthly: re-run whole-app audit
2. Open History mode to see trajectory
3. Investigate any band or UX subtype that regressed

### Phase 5 — Pre-launch
1. Run all journeys including chains (L4-journey)
2. Run cold-start mode with a fresh incognito or otherwise fresh context
3. Confirm pass rate on the `ux` band AND `core-experience`
4. Reconciler runs with full project-context

That's the playbook. Discover, define, iterate, monitor.
