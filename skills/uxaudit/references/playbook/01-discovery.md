# Phase 01 — Discovery (workspace, locator, URL, Scout, viewport)

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Previous phase:** [`00-env-setup.md`](./00-env-setup.md) · **Next phase:** [`02-catalog-run.md`](./02-catalog-run.md)
> **Subagents dispatched in this phase:** `uxaudit-locator` (Step 2), `uxaudit-scout` (Step 4). Their full system prompts live in `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-locator.md` and `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-scout.md` — the orchestrator does NOT re-inject them, Claude Code loads them automatically from the role's frontmatter.

## Step 1 — Workspace setup

The workspace lives at `./.agents/uxaudit/<target>/`. `--workspace` overrides if explicitly provided. `<target>` defaults to the cwd's directory basename when the user did not supply one.

```bash
# target defaults to the cwd directory name — "/uxaudit" with no args
# picks up the current project's name automatically.
target="${target:-$(basename "$PWD")}"

WORKSPACE="${EXPLICIT_WORKSPACE:-${PWD}/.agents/uxaudit/${target}}"
mkdir -p "$WORKSPACE"

# Stale-shell cleanup: if a previous aborted run left a dev-server tracking
# file behind, kill that shell (best-effort) and remove the file BEFORE we
# start a new iteration. See Step 3 for how the file gets written.
STALE="$WORKSPACE/.dev-server-shell"
if [ -f "$STALE" ]; then
  # Pseudocode: orchestrator uses KillShell(head -1 "$STALE"); ignore failure
  rm -f "$STALE"
  echo "[uxaudit] cleaned up stale dev-server shell from previous run"
fi

ITER=$(python3 -c "import os, glob; print(max([int(p.split('-')[-1]) for p in glob.glob(f'$WORKSPACE/iteration-*')] or [0]) + 1)")
ITER_DIR="$WORKSPACE/iteration-$ITER"
mkdir -p "$ITER_DIR"
```

## Step 2 — Project locator (monorepo / scope resolution)

Modern repos are rarely a single app — they often look like `apps/web` + `apps/marketing` + `services/api` + `apps/ios` under one root. Pointing Scout at the repo root in that case finds 3 design systems, 4 frameworks, and the wrong journeys.

**Solution**: before Scout runs, dispatch a **`uxaudit-locator` subagent** that maps the repo, enumerates every dev-server candidate (URL + start command + running state + auditability), identifies shared packages, and flags out-of-scope native siblings. Output is written to `<iteration-dir>/project-locator.json`.

The subagent's full system prompt lives in `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-locator.md` (frontmatter: `tools: Read, Glob, Grep, Bash, Write`, `model: sonnet`). Claude Code loads that file automatically when you dispatch `subagent_type="uxaudit-locator"` — the orchestrator **does NOT** re-inject the brief. The dispatch prompt body only carries the per-run inputs:

```python
# Pseudocode the orchestrator follows.
# URL_HINT is the --url flag if provided, else "" (URL will be decided in Step 3).
Agent(
  subagent_type="uxaudit-locator",
  description="Project locator",
  prompt=f"""
URL_HINT: {URL_HINT!r}
Output path: {ITER_DIR}/project-locator.json
""",
)
```

The `uxaudit-locator` role has Read / Glob / Grep, Bash (for `curl` port probing) and Write (to write `project-locator.json` directly to disk).

### Output schema (required fields)

```json
{
  "is_monorepo": true,
  "monorepo_tool": "turborepo | pnpm-workspaces | nx | lerna | rush | null",
  "project_root": "apps/web",
  "project_root_abs": "/abs/path/repo/apps/web",
  "url_match_app_id": "web",
  "matched_by": "<one-line cite>",
  "confidence": "high",
  "dev_server_candidates": [
    {
      "app_id": "web", "app_dir": "apps/web", "framework": "next.js",
      "declared_url": "http://localhost:3033/", "declared_from": "<file:line>",
      "start_command": "cd apps/web && pnpm dev", "start_from": "/abs/path/repo",
      "running": true, "auditable": true, "confidence": "high"
    }
  ],
  "shared_packages": [{ "path": "packages/ui", "purpose": "design tokens + components" }],
  "siblings": [{ "path": "apps/ios", "kind": "xcode-native", "port": null }]
}
```

`auditable: false` excludes a candidate from Step 3 but it still appears in `dev_server_candidates` so Scout can see it. The full per-field semantics — including the 14-source priority order for `declared_url`, the auditability rules, and the `running` probe contract — are in the `uxaudit-locator` agent definition at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-locator.md`.

When `is_monorepo: true`, **all subsequent steps operate on `project_root_abs`** instead of cwd:
- Scout's discovery uses that as its base
- The native-platform check from Step 5 ignores siblings
- Design system discovery includes `shared_packages`

When `is_monorepo: false`, still emit `dev_server_candidates` with a single entry (or empty array) and set `project_root: "."`.

## Step 3 — URL resolution + optional auto-launch

At this point the orchestrator has:
- The user-supplied `--url` flag (may be empty)
- `project-locator.json` with a `dev_server_candidates` array
- The user-supplied `--yes` / `-y` flag (may be unset). When set, this is **unattended mode** — the orchestrator MUST NOT pause for any disambiguation or consent prompt. It picks the safe default for each ambiguous case (spelled out below) and prints what it chose before proceeding so the run log is auditable.

Decision tree (execute in order, stop at first match):

Let `auditable_candidates = [c for c in locator.dev_server_candidates if c.auditable]` and `running = [c for c in auditable_candidates if c.running]`.

The **safe-default tiebreak** used by every `--yes` branch below:

```python
# Highest confidence wins; ties broken alphabetically by app_id so the
# choice is deterministic across runs (no hidden ordering surprises).
def safe_pick(candidates):
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(candidates, key=lambda c: (rank.get(c.confidence, 9), c.app_id or ""))[0]
```

### A. User passed `--url` explicitly
Use it as-is. The locator's `url_match_app_id` tells you which sub-app it belongs to. If nothing matched, the audit still proceeds — manual `--url` overrides detection. (`--yes` is irrelevant here.)

### B. Exactly one auditable candidate is running (`len(running) == 1`)
`URL = running[0].declared_url`. Print `[uxaudit] using running <framework> server at <URL>` and proceed. (`--yes` is irrelevant — no ambiguity.)

### C. Multiple auditable candidates are running (`len(running) > 1`)

**Without `--yes`** — print the numbered list and ask the user to pick one (or to re-run with `--url`). Empty answer → abort with "disambiguation required".

```
[uxaudit] Multiple dev servers detected. Which one do you want to audit?
  1) http://localhost:3033/   (web, Next.js)
  2) http://localhost:5174/   (admin, Vite)
Enter 1 or 2 (or re-run with --url explicitly):
```

**With `--yes`** — apply `safe_pick(running)` and announce the choice. Do not pause:

```
[uxaudit] --yes: auto-picked 'web' (http://localhost:3033/, Next.js, confidence=high)
          out of 2 running candidates. Re-run without --yes to disambiguate manually.
```

`URL = picked.declared_url`, proceed.

### D. Zero running, exactly one auditable candidate declared

**Without `--yes`** — ask for consent before launching, then run the **launch procedure** below:

```
[uxaudit] Dev server for 'web' (Next.js) is not running at http://localhost:3033/.
Start it now? (will run in the background and be stopped when the audit ends)
  $ cd apps/web && pnpm dev
[y/N]:
```

If the user says no, error out with the manual start command and stop.

**With `--yes`** — `--yes` IS the consent. Skip the prompt entirely, announce the launch, and run the launch procedure:

```
[uxaudit] --yes: auto-launching dev server for 'web' (Next.js)
          $ cd apps/web && pnpm dev
```

#### Launch procedure (cases D and E share this)
1. Start via `Bash(command=c.start_command, run_in_background=true, description=f"Dev server: {c.app_id}")` and record the returned `shell_id`.
2. Write `$WORKSPACE/.dev-server-shell` with two lines: `shell_id`, `declared_url`. This is what Step 18 uses to clean up — and what the next run's stale-shell cleanup (top of Step 1) uses if this run crashes.
3. Probe `declared_url` once per second (any HTTP status counts as "ready"). Timeout after 60 s.
4. On timeout → `KillShell(shell_id)`, remove the tracking file, and bail with the last 30 lines of `BashOutput(shell_id)` so the user can see the build failure. (Even with `--yes`: a build failure is not safe to silently retry on a different candidate; abort cleanly.)
5. On success → `URL = declared_url`, proceed to Step 4.

### E. Zero running, multiple declared candidates

**Without `--yes`** — show the same numbered list as case C but include each candidate's `start_command`. After the user picks one, apply the launch procedure above.

**With `--yes`** — apply `safe_pick(auditable_candidates)`, announce the choice, then run the launch procedure for the picked candidate. Do not pause:

```
[uxaudit] --yes: auto-picked 'web' (http://localhost:3033/, Next.js, confidence=high)
          out of 3 declared candidates. Auto-launching:
          $ cd apps/web && pnpm dev
```

### F. Zero running, zero declared
Abort with a help message regardless of `--yes` — there is nothing safe to assume:
```
[uxaudit] Could not detect any auditable dev server in this project.
Options:
  1. Start your dev server first (e.g. `npm run dev`, `bundle exec rails s`) and re-run /uxaudit.
  2. Pass --url explicitly: /uxaudit --url http://localhost:PORT/
  3. Audit an Electron app: /uxaudit --electron-app ./main.js

The Project Locator did not find any package.json scripts.dev, vite.config,
Rails Gemfile, Phoenix mix.exs, or Django manage.py in the expected places.
```

### Cleanup boundaries
Step 1 cleans up any stale `.dev-server-shell` from a crashed prior run; Step 18 stops whatever Step 3 started during *this* run. Servers the user had running before invocation are **never** touched — the orchestrator only kills what it started itself, tracked exclusively via the `.dev-server-shell` file.

## Step 4 — Scout (synthesize the project's scenario hypothesis)

If a project root exists in the cwd (any of: README.md, package.json, harness/state, docs/), spawn a **`uxaudit-scout` subagent**. The Scout writes `project-context.json` to `$ITER_DIR/project-context.json`.

The Scout's output is **an evidence-based hypothesis about the project's intent and primary journeys**, not ground truth. Each entry in `primary_journeys` and `experience_model.jobs` carries an `evidence_basis` that records what it was derived from and at what `confidence`. The downstream pipeline uses those markers to weight fails — a fail on a high-confidence (e.g. `e2e`-derived) journey is not the same as a fail on a low-confidence (`jtbd`-derived) one. See [`../concepts/discovery-and-scope.md`](../concepts/discovery-and-scope.md) Part 0 for the framing.

If `--no-scenarios` is set OR no project root is detected, skip Scout. The catalog still runs.

The subagent's full system prompt (tool allowlist: Read / Glob / Grep / Write plus WebSearch / WebFetch for rare regulated-domain external research; model: opus; discovery procedure D1–D6; audit_policy contract; pre-write self-check) lives in `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-scout.md`. Claude Code loads it automatically — the dispatch prompt body only carries per-run inputs:

```python
# Pseudocode the orchestrator follows
Agent(
  subagent_type="uxaudit-scout",
  description="Project context Scout",
  prompt=f"""
Project root: {PROJECT_ROOT_ABS}
Write your output to: {ITER_DIR}/project-context.json
Language: {UXAUDIT_LANG}
""",
)
```

The Scout's `model: opus` is pinned in the agent frontmatter. It is not a cheap categorizer; it is responsible for assembling the strongest evidence-based hypothesis available, separating what was found from what was inferred, and surfacing the gaps it cannot close. If the Scout collapses distinct jobs together or silently upgrades JTBD speculation to high-confidence, every downstream judgment gets weaker.

The Scout's file should conform to `schemas/project-context.schema.json`. Treat these as the important quality bars for Step 4:

- `primary_journeys` should usually reach the category floor documented in [`../concepts/experience-model.md`](../concepts/experience-model.md), but **only when honest evidence supports it** — padding the list with `jtbd`-derived speculation is worse than a smaller honest list
- multiple legitimate jobs should stay separate in `experience_model.jobs`
- each journey should carry `job_ids` when the mapping is clear
- each `evidence_basis` entry should have an accurate `confidence` — `high` only when the source is something the team actively maintains (e2e in CI, recent scenario doc), `medium` for routes / README inference, `low` for category-baseline adaptation and JTBD reasoning
- any external domain research should be rare and explicit in `evidence_basis` (`kind: "external-research"`)

If the Scout returns a sparse journey list, do not silently accept it AND do not silently reject it. Read `discovery_notes` and `experience_model.open_questions`: if the Scout explained the gap with evidence ("no e2e tests exist; README only describes the buyer flow"), the audit proceeds with a documented coverage gap that the Reconciler / Proposer / dashboard can surface. If the gap is undocumented, the Scout should be re-dispatched.

Immediately validate the Scout output before continuing:

```bash
python3 $UXAUDIT_DIR/scripts/validate_project_context.py "$ITER_DIR/project-context.json"
```

Errors block the run. Warnings do not block; they should be surfaced to the user and carried into the final summary as coverage caveats.

Critical isolation rule for iteration history:

- Scout must NOT read prior uxaudit verdicts (`.agents/uxaudit/**`, older `benchmark.json`, older `result.json`, prior dashboards)
- Judge must NOT read prior uxaudit verdicts
- Reconciler and Proposer may read only the CURRENT iteration's verdicts

If `--scenario-mode locked|hybrid` reuses a previous **scenario contract** (a ratified `project-context.json` from an earlier iteration), the orchestrator should pass the reused `project-context.json` or derived `evaluation-briefs` explicitly as inputs. Do not let Scout "discover" them by walking older iteration directories. `locked` means this iteration is a **regression run against the contract**: the Scout's job is reduced to no-op (the contract is the truth); `hybrid` means the Scout may add new candidates but the existing contract entries remain stable so iteration-to-iteration comparison stays meaningful; `refresh` discards the previous contract entirely (use after major IA / product changes).

## Step 5 — Resolve viewport (and check for native-platform projects)

After Scout finishes, first check whether it flagged the project as a native (iOS/Android/desktop GUI) app that uxaudit can't audit:

```bash
# Native project + no --url → nothing to capture, abort. If --url WAS given
# alongside a native project, the warning is informational only — proceed.
# This abort is unconditional — `--yes` does NOT bypass it because there is
# no "safe default" web URL to invent for a native-only project.
if [ -f "$ITER_DIR/project-context.json" ]; then
  WARNING=$(python3 -c "import json; print(json.load(open('$ITER_DIR/project-context.json')).get('native_platform_warning') or '')")
  if [ -n "$WARNING" ] && [ -z "$URL" ]; then
    echo "⚠️  $WARNING"
    echo "    Provide --url for a web companion (admin panel, marketing site) if one exists."
    exit 1
  fi
fi
```

Then decide which viewport(s) the rest of the pipeline will use:

```bash
# Precedence:
#   1. user --viewports (plural) → run multiple iterations, one per viewport
#   2. user --viewport (singular) → use that
#   3. Scout's project-context.json primary_viewport
#   4. Fallback: desktop
if [ -n "$USER_VIEWPORTS" ]; then
  VIEWPORTS="$USER_VIEWPORTS"   # comma-separated
elif [ -n "$USER_VIEWPORT" ]; then
  VIEWPORTS="$USER_VIEWPORT"
elif [ -f "$ITER_DIR/project-context.json" ]; then
  VIEWPORTS=$(python3 -c "import json; print(json.load(open('$ITER_DIR/project-context.json')).get('primary_viewport', 'desktop'))")
else
  VIEWPORTS="desktop"
fi
```

Steps 5–15 then loop over each viewport in `$VIEWPORTS`. When there's only one (the common case), it's a single iteration with the chosen viewport baked into `meta.json`. When `--viewports mobile,desktop` is passed, the orchestrator runs Step 6 → Step 16 once per viewport into separate iteration directories (e.g., `iteration-3-mobile`, `iteration-3-desktop`) so the dashboard can show them as siblings.
