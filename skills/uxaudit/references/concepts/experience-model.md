# Experience Model

This is the missing middle layer in uxaudit.

Today the catalog is strong at the universal floor:

- accessibility
- AI-slop / templated UI tells
- hierarchy
- empty states
- status visibility

What decides whether uxaudit becomes genuinely valuable is the layer above that floor:

- what this product's users need to understand quickly
- which decisions are essential vs needless
- what counts as first value here
- what progress and recovery should look like in this domain

Those are not fixed checks. They are **project-shaped evaluation contracts** — and contracts only become useful when they are both (a) honest about how they were derived and (b) ratifiable as the stable measuring stick for future iterations.

The experience model is therefore a **synthesis**, not a discovery. The Scout combines whatever local evidence the project actually contains (e2e tests, scenario docs, routes, README, category baselines, JTBD inference) with explicit per-source `confidence` markers, and writes its best hypothesis to disk. A human (or `--scenario-mode locked`) then ratifies that hypothesis as the contract this project will be evaluated against. If the contract is wrong, the fix is to edit the file and re-lock — not to ask the Scout to "discover better." There is no deterministic "more correct" answer the Scout could converge on; there is only an evidence-backed proposal that humans accept, edit, or reject. See [`./discovery-and-scope.md`](./discovery-and-scope.md) Part 0 for the longer-form rationale.

## Core idea

Keep the top-level reading model simple:

- `UX`
- `UI Risk`

Inside `UX`, keep the same fixed lenses:

- `understand` — *"Can users see what's there?"*
- `decide` — *"Can users decide what to do?"*
- `act` — *"Can users actually act on it?"*
- `recover` — *"Can users recover when something goes wrong?"*

The left-hand identifier is the internal key (used in `check.json`, `benchmark.json`, and the dashboard data model). The right-hand sentence is the user-subject framing surfaced in the dashboard UI — the orchestrator and Judges continue to use the short internal IDs, while the report always phrases findings from the user's point of view ("N places where users can't decide").

Do not treat the lenses as fixed checks. Treat them as fixed questions whose concrete rubric changes per project.

Current implementation note:

- the model keeps all 4 lenses because they are the right mental model
- the current brief pipeline only materializes `understand` and `act`
- `decide` and `recover` are still valuable fields in `experience_model`, but they are not yet first-class brief targets

That distinction matters: the conceptual model is intentionally ahead of the currently injected Judge context.

## What the Scout should produce

The Scout should **synthesize** an `experience_model` from local evidence and write it into `project-context.json`. Every job carries an `evidence_basis` array so a downstream reader can see exactly what each part of the model is grounded in.

Suggested shape:

```json
{
  "experience_model": {
    "jobs": [
      {
        "id": "find-recipe-fast",
        "name": "Find a recipe and start cooking",
        "priority": "high",
        "actor": "first-time home cook",
        "outcome": "Get to a trustworthy recipe detail page quickly",
        "contexts": ["cold-start", "returning"],
        "first_value": "A recipe detail page is open with ingredients and steps visible",
        "must_understand": [
          "This app is for browsing and saving cooking recipes",
          "I can search by dish name or browse by category"
        ],
        "key_decisions": [
          "Which recipe should I open?",
          "Do I search or browse by category?"
        ],
        "decisions_to_default": [
          "Do not force cuisine selection before the user has seen any recipes"
        ],
        "progress_signals": [
          "Visible recipe count",
          "Active category / filter state",
          "Recently added or saved-state indicators"
        ],
        "recovery_points": [
          "Back from recipe detail to the same filtered list",
          "Clear search / filters easily"
        ],
        "simplicity_rules": [
          "Opening a recipe should take 1 click from the landing page",
          "Browsing should not require signup"
        ],
        "evidence_basis": [
          {
            "source": "tests/e2e/home-to-recipe.spec.ts",
            "kind": "e2e",
            "confidence": "high"
          }
        ]
      }
    ],
    "open_questions": [
      "Is saving recipes a primary loop or secondary behavior?"
    ]
  }
}
```

This is intentionally lightweight. It is not a PRD clone.

## Field intent

### Job-level fields (`experience_model.jobs[*]`)

| Field | Why it exists |
|---|---|
| `id`, `name` | Stable handle for wiring journeys and check briefs |
| `priority` | Lets the orchestrator emphasize the jobs that define the product |
| `actor` | Prevents the model from judging for a generic user |
| `outcome` | Forces the Scout to define what success actually is |
| `contexts` | Separates cold-start / returning / power-user expectations |
| `first_value` | The anchor for FTUE and journey evaluation. Abstract — answers "what value did the user come to get?" Validated per-journey via `first_value_signals` (below). |
| `must_understand` | Feeds the `understand` lens |
| `key_decisions` | Feeds the `decide` lens |
| `decisions_to_default` | Captures where the UI should reduce choice rather than ask |
| `progress_signals` | Feeds the `act` and `recover` lenses |
| `recovery_points` | Defines where undo / back / confirmation matter |
| `simplicity_rules` | Captures domain-specific “do less” expectations |
| `evidence_basis` | Makes it explicit what was found vs inferred — each entry carries `kind` + `confidence` |

### Journey-level fields (`primary_journeys[*]`)

| Field | Why it exists |
|---|---|
| `id`, `name`, `goal`, `starting_url`, `success_criteria`, `context` | Existing operational fields — what the journey is, where it starts, what counts as done, who is running it |
| `derived_from` | The primary source the Scout used to synthesize this journey (`e2e:tests/...`, `route:/checkout`, `category-baseline:music-streaming`, etc.) |
| `confidence` | **Hypothesis strength**: `high` for journeys backed by an actively maintained source (CI e2e, recent scenario doc), `medium` for routes / README inference, `low` for category-baseline adaptation and JTBD reasoning. The downstream pipeline weights fails by this value — a fail on a `low` journey is information about the hypothesis as much as about the product. Optional but strongly recommended; absent = treated as `medium`. |
| `first_value_signals` | **Concrete observable indicators that the job's `first_value` was actually delivered on this specific journey**. Different journeys to the same job often have different completion signals. Example for "find a recipe" job, journey A "search by ingredient": `["Search results page lists ≥1 matching recipe", "Detail page shows ingredient list and steps"]`. The L4 Judge uses these to evaluate the `value_delivery` axis of `journey_evaluation`. Optional — when absent, the Judge falls back to interpreting the abstract `first_value` string. |
| `intentional_friction` | **Steps the team purposely added that LOOK like excise but are required friction** (Cooper's idiom-required friction): irreversibility guards, shoulder-surf guards, payment confirmations. Each entry has `matches` (natural-language description of what to look for) and `rationale` (why the friction is justified). The L4 Judge matches actual steps semantically against `matches` and counts unmatched excess as unintentional excise. Without this list, the Judge treats every step beyond the minimum as wasted; with it, the Judge can correctly say "this 11-step journey is fine — 3 of the steps are declared trust-building moments." Only populate when there's clear evidence in spec/code that the friction is deliberate; otherwise omit and let the Judge classify the step on observation alone. |
| `job_ids`, `next_journey`, `previous_journey` | Wiring fields — link a journey to its job(s) and to other journeys in a chain |

## Multiple jobs are normal

Many products have more than one legitimate primary job.

Examples:

- marketplace: buyer job and seller job
- SaaS team tool: maker job, reviewer job, admin job
- fintech: monitor money, move money, resolve a problem

uxaudit should not force these into one “main journey.” Instead:

- allow multiple `jobs`
- assign each `primary_journey` to one or more `job_id`s
- rank jobs by `priority`

The point is not to model every possible user. The point is to model the few jobs that define whether this product feels right.

Example:

- job: `find-recipe-fast`
- journeys: `browse-home`, `open-recipe-detail`
- both journeys carry `job_ids: ["find-recipe-fast"]`

This lets the Scout model multiple jobs without exploding the journey list into near-duplicates.

## When external research is warranted

Most projects should rely on local evidence first:

1. e2e tests
2. scenario docs
3. routes
4. README/spec
5. category baselines
6. JTBD inference

External search is useful only when domain expectations materially change the UX contract and local docs are too weak.

Typical cases:

- healthcare
- fintech / banking
- booking / scheduling
- enterprise admin tools
- regulated onboarding flows

External research should answer questions like:

- What decisions are normally deferred or defaulted in this domain?
- What progress or trust signals are expected?
- What recovery or confirmation patterns are standard because errors are costly?

It should not be used to rationalize generic UX quality.

If external research is used, store it explicitly in `evidence_basis` with `kind: "external-research"`.

Keep it narrow. The point is to fill in domain expectations the local project does not express, not to turn the Scout into a general research agent by default.

## How many scenarios is enough

Practical floor:

| Product type | Too few | Better floor |
|---|---|---|
| Marketing / landing | 1 | 3 |
| CRUD / simple utility | 2 | 5 |
| Team SaaS | 3 | 7 |
| Marketplace / platform | 4 | 8+ |

A useful rule:

- aim for at least 5 journeys
- for team / platform products, aim for 7–10
- chains count, but only if each link is meaningful

If the local evidence does not support hitting the floor, the Scout writes the shortfall into `discovery_notes` and `experience_model.open_questions` as an explicit **coverage gap** with the reason. The Scout does not pad the journey list with low-confidence speculation just to hit a number — a small honest model is more useful than a large model that can't tell the human which entries to trust. The downstream pipeline weights fails by the journey's `confidence`, so a coverage gap is information, not a defect.

## How the pipeline should use this

The Judge still must not read the whole spec or raw project files.

Instead:

1. Scout writes `experience_model`
2. Orchestrator derives a tiny per-check `evaluation_brief`
3. Judge receives only that brief plus the artifact

Example `evaluation_brief` for `understand`:

```json
{
  "job_id": "find-recipe-fast",
  "journey_id": "browse-home",
  "must_understand": [
    "This app is for browsing and saving cooking recipes",
    "I can search by dish name or browse by category"
  ],
  "first_value": "A recipe detail page is open with ingredients and steps visible"
}
```

Example `evaluation_brief` for `decide`:

```json
{
  "job_id": "find-recipe-fast",
  "journey_id": "browse-home",
  "key_decisions": [
    "Which recipe should I open?",
    "Do I search or browse by category?"
  ],
  "decisions_to_default": [
    "Do not force cuisine selection before the user has seen any recipes"
  ],
  "simplicity_rules": [
    "Opening a recipe should take 1 click from the landing page"
  ]
}
```

This is where agent reasoning should matter most.

## Product claim

If uxaudit can only run fixed checks, it is a useful lint layer.

If uxaudit can **synthesize** a project-shaped `experience_model`, **let a human ratify it as the scenario contract**, and **regress against that contract** every iteration, it becomes a real UX audit system. The catalog catches the universal floor; the experience model carries the project-specific contract; locking turns the contract into a stable measuring stick. Those three layers together are what separates this from a generic accessibility / craft linter.
