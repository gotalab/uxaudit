# Library mode — central registry, cross-project view, hide rules

Every `/uxaudit` run produces a workspace at `${PWD}/.agents/uxaudit/<target>/`. Across many projects this scatters fast. uxaudit tracks them centrally without changing where the data lives.

## Central registry

After every run, the orchestrator auto-registers the workspace in `~/.agents/uxaudit/registry.json`:

- Light metadata only — `target`, `url`, latest pass-rate, sparkline of the last N iterations, dashboard path, latest viewport, latest target kind (web vs electron), `archived` flag
- A per-workspace static `dashboard.html` is also written so it can be opened directly with `file://` (no Python server required)
- The Library tab in any audit dashboard reads the registry, so you can switch from any audit dashboard to the cross-project library view without re-running anything
- Pass `--no-register` to skip registration for one-off runs

The registry is auto-managed — there is no manual command to add or remove entries. Every `generate_dashboard.py` call updates the corresponding workspace's record in place.

### Where the registry lives

`generate_dashboard.py` resolves the registry directory with this precedence (first match wins):

| Order | Path | When it applies |
|---|---|---|
| 1 | `$UXAUDIT_HOME` | Explicit override. Any path, expanded. For CI, tests, or power users. |
| 2 | `$CLAUDE_PLUGIN_DATA/uxaudit/` | **Only** when uxaudit itself is the invoking plugin. Guarded by checking that `SKILL_DIR` lives inside `~/.claude/plugins/cache/`. |
| 3 | `$XDG_DATA_HOME/uxaudit/` | XDG-aware users (mainly Linux). The registry is data, not config, so this lives under `XDG_DATA_HOME`, not `XDG_CONFIG_HOME`. |
| 4 | `~/.agents/uxaudit/` | Default. Mirrors the per-project layout `<project>/.agents/uxaudit/<target>/` so the directory naming is identical at both scopes. `.agents/` is an agent-neutral umbrella — no vendor lock-in to `.claude/` or `.cursor/` — which matters because uxaudit is meant to run from any agent harness or standalone. |

The same directory contains `registry.json`, `registry.lock` (flock sentinel for concurrent writes), and `library.html`. It's intentionally small (only metadata + the library page — all actual iteration data stays in each project's local workspace).

## Library view (cross-project)

```bash
python $UXAUDIT_DIR/scripts/generate_dashboard.py --library
```

Renders `~/.agents/uxaudit/library.html` and opens it. Shows every registered workspace as a card with:

- Latest pass-rate (large number)
- Sparkline trend across the last N iterations (SVG line + fill + dots)
- Run count
- Latest viewport badge (mobile / tablet / desktop / electron)
- "Open dashboard" link to the per-workspace static dashboard
- Archive button

The Library view supports search/filter by name and Active / All / Archived toggle pills.

## Hide a workspace

When a project is dead or you don't want it in the library list:

```bash
python $UXAUDIT_DIR/scripts/generate_dashboard.py --archive /path/to/.agents/uxaudit/<target>
python $UXAUDIT_DIR/scripts/generate_dashboard.py --unarchive /path/to/.agents/uxaudit/<target>
```

Archived workspaces stay in the registry but are filtered out of the default Library view (toggle with the Active / All / Archived pills in the header). The on-disk data is untouched — `--archive` is reversible at any time.

## Hide a noisy check (`.uxauditignore`)

If a particular check is consistently a false positive in your project, drop a `.uxauditignore` file at the workspace root (the `.agents/uxaudit/<target>/` directory, alongside `iteration-*`):

```
# .uxauditignore — gitignore-style, one check_id per line
ai-slop/purple-gradient        # we ARE an indigo-branded crypto tool
ai-slop/coming-soon-text       # marketing wants the "Coming soon" badge
desirability/visual-craft      # known unfinished, tracking elsewhere
desirability/*                 # fnmatch globs work
```

Each line is a check_id (or fnmatch glob like `desirability/*`). Ignored checks still appear in the dashboard but are excluded from the pass-rate denominator and the failures list, so they don't dominate the verdict. This is project-local — different workspaces can ignore different checks.

The Reconciler subagent is a complementary mechanism: it can flip catalog fails to passes when the project's design system explicitly justifies them (e.g., "purple-gradient fails, but the brand IS indigo per `tailwind.config.ts`"). Use `.uxauditignore` for static, decided exceptions; let the Reconciler handle dynamic, evidence-based ones.

## Why central but not centralized

The data stays in each project's local `.agents/uxaudit/<target>/` directory. The registry only points at it. This means:

- Projects can be moved, renamed, or deleted without breaking the registry (orphan entries surface with a warning, never cause a crash)
- Multiple developers on the same machine can share the registry but each project's workspace lives in their own checkout
- You can `git clone` a project that someone else audited and continue iterating; the registry will pick up the new workspace on the next run
- The `~/.agents/uxaudit/` directory is small (just `registry.json` + `library.html`), not a duplicate of every workspace

## Schema (registry.json)

```json
{
  "workspaces": [
    {
      "path": "/Users/you/projects/mise-en-place/.agents/uxaudit/mise-en-place",
      "target": "mise-en-place",
      "url": "http://localhost:5173",
      "latest_pass_rate": 0.78,
      "latest_iteration": 4,
      "latest_viewport": { "preset": "mobile", "width": 390, "height": 844 },
      "latest_target_kind": "web",
      "sparkline": [0.45, 0.61, 0.72, 0.78],
      "dashboard_path": "/Users/you/projects/mise-en-place/.agents/uxaudit/mise-en-place/dashboard.html",
      "registered_at": "2026-04-07T19:00:00Z",
      "last_run_at": "2026-04-07T19:00:00Z",
      "archived": false
    }
  ],
  "registry_version": 1
}
```

The schema is intentionally narrow — adding fields requires bumping `registry_version` and a small migration in `generate_dashboard.py`. The library renderer is forgiving of missing fields so older registries continue to work.
