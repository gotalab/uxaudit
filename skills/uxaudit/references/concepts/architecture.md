# uxaudit · architecture

The full layered evaluation model, how subagents are dispatched, what the journey
schema looks like, and where each piece of the pipeline lives.

## Pipeline at a glance

```
                        ┌──────────────────┐
   /uxaudit <target>  │  ORCHESTRATOR    │   the Claude agent running this skill
   ─────────────────►   │  (Claude agent)  │
                        └────────┬─────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                ▼                ▼                ▼
        ┌────────────┐    ┌────────────┐   ┌────────────┐
        │  SCOUT     │    │  CAPTURE   │   │  CATALOG   │
        │  (subagent)│    │  Playwright│   │  (Python)  │
        │            │    │            │   │            │
        │ reads cwd  │    │ screenshot │   │ L1 detect.py
        │ writes:    │    │ rendered.  │   │ L2 run.mjs
        │ project-   │    │ html       │   │            │
        │ context    │    │ CSS, etc.  │   │ writes:    │
        │ .json      │    │            │   │ checks/*/  │
        └─────┬──────┘    └─────┬──────┘   │ result.json│
              │                 │          └──────┬─────┘
              │                 │                 │
              │                 ▼                 │
              │         ┌──────────────┐          │
              │         │ JOURNEY      │          │
              │         │ CAPTURE      │          │
              │         │ (Playwright) │          │
              │         │              │          │
              │         │ walks steps, │          │
              │         │ saves        │          │
              │         │ waypoint-N   │          │
              │         │ .png         │          │
              │         └──────┬───────┘          │
              │                │                  │
              │                ▼                  │
              │         ┌──────────────┐          │
              │         │  JUDGE(s)    │          │
              │         │  (subagents) │          │
              │         │              │          │
              │         │ L3 vision    │          │
              │         │ L4 pixel-    │          │
              │         │ only journey │          │
              │         │              │          │
              │         │ never sees   │          │
              │         │ project ctx  │          │
              │         │              │          │
              │         │ writes:      │          │
              │         │ result.json  │          │
              │         └──────┬───────┘          │
              │                │                  │
              ▼                ▼                  ▼
              └──────►┌─────────────────┐◄────────┘
                      │  RECONCILER     │
                      │  (subagent)     │
                      │                 │
                      │ sees Scout ctx  │
                      │ + all verdicts  │
                      │                 │
                      │ may flip failed │
                      │ catalog checks  │
                      │ → passes if     │
                      │ design system   │
                      │ justifies them  │
                      └────────┬────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │  AGGREGATE       │
                      │  benchmark.json  │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │  DASHBOARD       │
                      │  (editorial,     │
                      │  unified mode)   │
                      └──────────────────┘
```

## Why three subagent roles, not one

The single biggest failure mode of LLM-as-judge is **rationalization**. If you give the
judging LLM both the spec and the artifacts, it will find a way to read the artifacts as
satisfying the spec — because matching is easier than judging. The result is a tool that
always passes its own criteria.

NN/g's heuristic evaluation methodology calls for **3–5 independent evaluators** for
exactly this reason. You can't get independence from one evaluator no matter how you
prompt it.

uxaudit approximates independence with role-separated subagents:

- The **Scout** documents intent. It reads the spec, the design system, the journey
  definitions. It writes them down as facts. It does not judge.
- The **Judge** evaluates artifacts. It is given a task and the artifacts, but **never the
  spec**. It judges as a first-time user would, with only what's in front of it.
- The **Reconciler** is the only role allowed to see both. Its job is to re-evaluate
  catalog failures in light of declared intent: "Judge said this fails purple-gradient,
  but the brand IS indigo per the design system, so this is correct — flip to pass."

This pattern is borrowed from accounting / audit practice: the auditor never sees the
client's narrative until after the books are reviewed. Then management's commentary is
considered separately.

## L1 / L2 / L3 / L4 — what each layer can answer

| Layer | Method | Example check | Why this layer |
|---|---|---|---|
| **L1** | Python regex/AST on captured artifacts | `ai-slop/purple-gradient` (substring scan of CSS) | Cheapest, deterministic, runs in milliseconds. Catches the obvious slop. |
| **L2** | Node/Playwright on the live page | `accessibility/axe-core` (90+ WCAG rules), `accessibility/target-size` | Needs a real browser to compute styles, run accessibility engines, measure bounding boxes. Still deterministic. |
| **L3** | Vision-LLM judging a screenshot | `usability/visual-hierarchy` ("is the primary CTA visually dominant?") | Some questions can't be answered by parsing. Vision is required. |
| **L4** | Pixel-only journey Judge operating the app step by step | `core-experience/primary-journey` ("complete the booking journey, judge the friction") | Some questions can't be answered without operating the app. Requires multi-step interaction and visible state-by-state judgment. |

**Cost ordering, fastest to slowest:** L1 ≪ L2 ≪ L3 ≪ L4.
**Coverage ordering, narrowest to broadest:** L1 ≪ L2 ≪ L3 ≪ L4.

The principle is: prefer the cheapest layer that can answer the question. Only escalate
when you have to. A check that L1 can answer should never be promoted to L3.

## Catalog checks vs scenario checks

These are orthogonal to L1–L4.

| Dimension | Catalog | Scenario |
|---|---|---|
| Project-aware? | No (mostly) | Yes |
| Source | Published UX literature | Discovered from project files |
| Stability | Updates rarely | Different per project |
| Examples | All current `checks/ai-slop/*`, `checks/accessibility/*` | `core-experience/primary-journey` (with the project's actual journey) |
| Run order | First (filters out the obvious) | Second (uses what catalog learned) |

A check can be in either or both buckets. `usability/visual-hierarchy` is catalog (the heuristic doesn't change per project) but its baseline can be tightened by the design system.

## Project context schema

Produced by the Scout subagent, stored at `<workspace>/iteration-N/project-context.json`.

```json
{
  "purpose": "A reservation tool for an independent ceramics gallery in Kanazawa.",
  "target_audience": "Tourists and collectors, mostly first-time visitors. Half Japanese, half international.",
  "design_system": {
    "colors": [
      { "name": "ink",       "value": "#1c1612", "role": "primary text" },
      { "name": "parchment", "value": "#f4ede2", "role": "background"  },
      { "name": "vermillion","value": "#b7410e", "role": "accent"      }
    ],
    "fonts": [
      { "name": "Fraunces", "role": "display + body, variable" },
      { "name": "DM Mono",  "role": "metadata + code"          }
    ],
    "spacing_unit": 8,
    "border_radius": 0
  },
  "primary_journeys": [
    {
      "id": "reserve-viewing",
      "name": "Reserve a viewing",
      "goal": "A visitor with no prior account can confirm a reservation for an upcoming Saturday viewing in under 90 seconds.",
      "starting_url": "/",
      "steps_hint": [
        "Open the booking entry point from the landing page",
        "Choose an upcoming Saturday slot",
        "Enter visitor contact details",
        "Confirm the reservation"
      ],
      "success_criteria": "A confirmation message appears with the booking date echoed back.",
      "context": "cold-start",
      "derived_from": "e2e:tests/e2e/reserve-viewing.spec.ts",
      "job_ids": ["reserve-viewing"]
    }
  ],
  "experience_model": {
    "jobs": [
      {
        "id": "reserve-viewing",
        "name": "Book a gallery viewing quickly",
        "priority": "high",
        "actor": "first-time tourist visitor",
        "outcome": "A booking is confirmed without needing prior account setup",
        "contexts": ["cold-start", "returning"],
        "first_value": "A visitor sees a confirmed reservation state",
        "must_understand": [
          "This is a booking tool for gallery viewings",
          "I can reserve a slot without creating an account first"
        ],
        "key_decisions": [
          "Which date/time slot to reserve"
        ],
        "decisions_to_default": [
          "Do not ask for optional preferences before a slot is chosen"
        ],
        "progress_signals": [
          "Current step in booking flow",
          "Selected slot remains visible during checkout"
        ],
        "recovery_points": [
          "Go back to slot selection without losing entered contact info"
        ],
        "simplicity_rules": [
          "A first-time visitor should be able to confirm in under 90 seconds"
        ]
      }
    ],
    "open_questions": []
  },
  "discovery_sources": [
    { "kind": "readme",          "path": "README.md" },
    { "kind": "design-tokens",   "path": "src/styles/tokens.json" },
    { "kind": "tailwind-config", "path": "tailwind.config.ts" },
    { "kind": "e2e-tests",       "path": "tests/e2e/reserve-viewing.spec.ts" }
  ]
}
```

The `experience_model` is not raw spec text. It is the Scout's compressed, evidence-based UX contract for this project. This is the layer that should eventually feed project-shaped L3/L4 briefs without letting Judges read the full spec directly.

Each journey can point back to one or more `job_ids`. That mapping matters when a product has multiple legitimate primary jobs but a shared route graph.

## Journey schema

Used by `capture_journey.mjs` and consumed by L4 checks.

```json
{
  "id": "reserve-viewing",
  "name": "Reserve a viewing",
  "goal": "A visitor confirms a reservation.",
  "starting_url": "http://localhost:5173/",
  "job_ids": ["reserve-viewing"],
  "viewport": { "width": 1440, "height": 900 },
  "steps": [
    { "action": "navigate", "url": "/" },
    { "action": "wait", "ms": 500 },
    { "action": "screenshot", "name": "01-landing" },
    { "action": "click", "selector": "text=Reserve a viewing" },
    { "action": "screenshot", "name": "02-after-reserve-click" },
    { "action": "type", "selector": "input[name=name]", "text": "Visitor" },
    { "action": "type", "selector": "input[name=email]", "text": "visitor@example.com" },
    { "action": "screenshot", "name": "03-form-filled" },
    { "action": "click", "selector": "text=Confirm" },
    { "action": "wait", "ms": 1000 },
    { "action": "screenshot", "name": "04-confirmation" }
  ],
  "success_criteria": "A confirmation message appears with the booking date echoed back."
}
```

Step actions supported:
- `navigate` — `url` (relative to starting_url) or `back`
- `click` — `selector` (text= prefix supported, otherwise CSS)
- `type` — `selector` + `text`
- `wait` — `ms` (or `selector` to wait for an element)
- `screenshot` — `name` (saved as `name.png` in the journey dir)
- `scroll` — `delta` (px) or `to` ("top"/"bottom")

The Playwright capture script writes:

```
<workspace>/iteration-N/journey/<journey-name>/
├── steps.json          ← the journey definition + per-step status
├── 01-landing.png
├── 02-after-reserve-click.png
├── 03-form-filled.png
├── 04-confirmation.png
└── trace.zip           ← optional Playwright trace
```

For L4 checks, the same directory layout applies whether the Judge stayed in
Playwright-owned runtime space or had to escalate to `computer-use`. The
screenshots always represent the visible step-by-step evidence the Judge used
for the verdict.

## Subagent dispatch — concrete protocol

The orchestrator agent (running this skill) uses the Claude Code `Agent` tool to spawn **dedicated `uxaudit-*` subagent roles**. Each role is a real subagent definition at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-<role>.md` with its own frontmatter (pinned `tools`, `model`, full system prompt). Claude Code loads the agent's body automatically when the orchestrator passes `subagent_type="uxaudit-<role>"` — the orchestrator does NOT re-inject the brief.

The 7 roles are:

| `subagent_type` | Agent file | Model | Tools | Role |
|---|---|---|---|---|
| `uxaudit-locator` | `agents/uxaudit-locator.md` | sonnet | Read, Glob, Grep, Bash, Write | Monorepo / dev-server enumeration |
| `uxaudit-scout` | `agents/uxaudit-scout.md` | opus | Read, Glob, Grep, Write, WebSearch, WebFetch | Project-context discovery |
| `uxaudit-journey-compiler` | `agents/uxaudit-journey-compiler.md` | sonnet | Read, Write, Bash, WebFetch | NL journey → executable JSON |
| `uxaudit-l3-judge` | `agents/uxaudit-l3-judge.md` | opus | Read, Write | L3-vision verdict |
| `uxaudit-l4-judge` | `agents/uxaudit-l4-judge.md` | opus | Read, Write, Glob | L4-journey verdict (evidence-only) |
| `uxaudit-reconciler` | `agents/uxaudit-reconciler.md` | sonnet | Read, Edit, Write, Glob | Catalog-vs-intent override |
| `uxaudit-proposer` | `agents/uxaudit-proposer.md` | sonnet | Read, Write, Glob | Root-cause synthesis + ranked fix plan |

**The tool allowlist in each agent's frontmatter is the physical isolation layer.** The L3 Judge cannot call Bash because it has no Bash tool — not because a prompt told it not to. The Scout cannot curl the running app because it has no Bash or WebFetch. This turns the "Judge must not read the spec" rationalization risk into a tool-capability fact.

Each agent's system prompt body contains:

- The role's procedure and decision rules
- Inline heal-mode handling (replaces the old `heal-preamble.md` injection pattern)
- Inline language-directive handling (replaces the old `language-preamble.md` injection pattern — dispatch prompt body carries `Language: ja|en`)
- Pre-write self-checks that mirror what the post-flight validators will enforce

The per-dispatch prompt body only carries the **per-run variables** — paths, `check_id`, `Language: <code>`. Previous versions of this skill injected the entire brief into every dispatch at runtime; that pattern is obsolete.

See `${CLAUDE_PLUGIN_ROOT}/skills/uxaudit/references/playbook/` for the exact per-phase dispatch pseudocode (which paths flow into which `prompt` body per phase).

## Failure modes and how this design avoids them

| Failure mode | Why it happens | How uxaudit avoids it |
|---|---|---|
| Judge rationalizes | One LLM sees both spec and artifacts | Scout/Judge separation; Judge never sees spec |
| Catalog over-fires on intentional design | All checks are project-agnostic | Reconciler can flip catalog fails when design system justifies them |
| Single-page checking misses real UX | Most checks only look at the landing page | Journey capture + L4 walks the actual user flow |
| Hardcoded paths break for other projects | "spec.md" lives in different places | Discovery enumerates conventions in priority order, falls back to "no context" |
| Slop dashboard ironically looks like slop | The dashboard is itself a UI | Dashboard rebuilt in editorial aesthetic, uses Fraunces + DM Mono, intentional palette |
| Test reports get ignored | Generic "X% passing" with no story | Each failure is an editorial entry with source, criterion, evidence, and a what-to-do paragraph |
| Tool replaces real users | No tool actually can | Explicitly out of scope; SKILL.md says so up front; Retention layer is honest about not being measurable |

## Honest scope

uxaudit is a **discount heuristic evaluation** tool in the sense Jakob Nielsen used the
term in 1989 — methodologically less rigorous than lab user testing, but small enough to
run in seconds and broad enough to catch the obvious. It is not a substitute for user
research. It is the floor of UX evaluation, not the ceiling.

The catalog covers the *floor of craft*: things that are wrong regardless of audience.
The scenario layer covers *journey continuity*: did the actual user flow complete
without surprise? Neither layer can tell you whether the product is the right product to
build. That remains a human question.
