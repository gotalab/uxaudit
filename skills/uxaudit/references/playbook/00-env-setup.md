# Phase 00 — Environment setup

> Part of the orchestrator playbook. See [`index.md`](./index.md) for the full phase map.
> **Next phase:** [`01-discovery.md`](./01-discovery.md)

## Step 0 — Environment setup (plugin / standalone / dev)

Before running any script, resolve **where the skill bundle lives**, point Node at the lazy-installed `node_modules` (when needed), and pin the narrative output language for the run.

The Python scripts under `scripts/` already self-locate via `Path(__file__).resolve().parents[1]`, so once `$UXAUDIT_DIR` is set the orchestrator's bash invocations are the only place that needs the env var. The fallback chain below makes that resolution work in **plugin / `--plugin-dir` / standalone-symlink / development-bundle** mode without requiring the user to set anything by hand.

```bash
# 1. Skill bundle location — fallback chain (highest priority first)
#
#    1) $UXAUDIT_DIR explicit override — power user / CI
#    2) $CLAUDE_SKILL_DIR — set by the Skill tool when invoking from a plugin
#    3) $CLAUDE_PLUGIN_ROOT/skills/uxaudit — plugin mode AND `--plugin-dir` mode
#    4) $HOME/.claude/skills/uxaudit — standalone symlink/dir install
#    5) Common dev-checkout paths — uxaudit cloned alongside the audit target
#
#    Each candidate is sanity-checked by looking for SKILL.md before being
#    accepted. If nothing resolves, the script fails fast with a clear
#    message instead of pretending to work and crashing later.
if [ -z "${UXAUDIT_DIR:-}" ]; then
  for candidate in \
    "${CLAUDE_SKILL_DIR:-}" \
    "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/uxaudit}" \
    "$HOME/.claude/skills/uxaudit" \
    "$HOME/Documents/projects/uxaudit/skills/uxaudit" \
    "$HOME/projects/uxaudit/skills/uxaudit" \
    "$HOME/code/uxaudit/skills/uxaudit" \
    "$PWD/skills/uxaudit"; do
    if [ -n "$candidate" ] && [ -f "$candidate/SKILL.md" ]; then
      UXAUDIT_DIR="$candidate"
      break
    fi
  done
fi

if [ -z "${UXAUDIT_DIR:-}" ] || [ ! -f "$UXAUDIT_DIR/SKILL.md" ]; then
  echo "[uxaudit] ERROR: cannot resolve UXAUDIT_DIR — SKILL.md not found." >&2
  echo "[uxaudit]   Tried: \$CLAUDE_SKILL_DIR, \$CLAUDE_PLUGIN_ROOT/skills/uxaudit," >&2
  echo "[uxaudit]   ~/.claude/skills/uxaudit, common dev paths." >&2
  echo "[uxaudit]   Set UXAUDIT_DIR explicitly to your skill bundle path:" >&2
  echo "[uxaudit]     export UXAUDIT_DIR=/abs/path/to/skills/uxaudit" >&2
  exit 1
fi
export UXAUDIT_DIR

# 2. In plugin mode, dependencies live in $CLAUDE_PLUGIN_DATA (installed once
#    by hooks/ensure-deps.sh on SessionStart). Tell Node where to find them
#    via NODE_PATH. In standalone mode, skip — `node_modules` sits next to
#    the scripts and Node's normal walk-up resolution handles it without
#    extra env vars.
#
#    We deliberately do NOT set PLAYWRIGHT_BROWSERS_PATH — Chromium lives in
#    Playwright's default per-user cache, shared with any other Playwright
#    project on the machine. See _target.mjs for the rationale.
if [ -n "${CLAUDE_PLUGIN_DATA:-}" ] && [ -d "$CLAUDE_PLUGIN_DATA/node_modules" ]; then
  export NODE_PATH="$CLAUDE_PLUGIN_DATA/node_modules"
fi

# 3. Pin the narrative output language for this invocation.
#    Default is explicit English. `--lang ja` opts in to Japanese narrative.
#    IMPORTANT: use $UXAUDIT_LANG — the shell's standard $LANG variable is
#    typically "ja_JP.UTF-8" / "en_US.UTF-8" (a POSIX locale string), which
#    is NOT a uxaudit language code and would leak the Japanese preamble
#    into every English run if we keyed off of it.
export UXAUDIT_LANG="${USER_LANG:-en}"   # set USER_LANG from the --lang CLI flag above

# 4. Optional: $UXAUDIT_HOME overrides the global registry + library.html
#    directory. Unset by default — resolved at runtime by generate_dashboard.py
#    with this precedence:
#      1. $UXAUDIT_HOME               (explicit override, CI/tests)
#      2. $CLAUDE_PLUGIN_DATA/uxaudit (plugin mode, guarded by SKILL_DIR check)
#      3. $XDG_DATA_HOME/uxaudit      (XDG-aware users)
#      4. ~/.agents/uxaudit           (default — mirrors per-project .agents/uxaudit/<target>/)
#    See references/modes/library.md#where-the-registry-lives for the rationale.
```

**All subsequent `node` / `python3` invocations in this playbook assume these
env vars are set.** If you skip Step 0 in plugin mode, scripts will fail to
find Playwright (the cache at `$CLAUDE_PLUGIN_ROOT` is read-only and has no
`node_modules/` in it by design).

### Why the fallback chain matters

The previous version of this step only checked `$CLAUDE_PLUGIN_ROOT` and `$HOME/.claude/skills/uxaudit`. That covers **plugin mode** and **standalone install**, but breaks in two real-world cases:

| Mode | What's installed | Old behavior | New behavior |
|---|---|---|---|
| `claude --plugin-dir /path/to/uxaudit-plugin` | `$CLAUDE_PLUGIN_ROOT` set by Claude Code | ✓ worked | ✓ still works |
| Plugin marketplace install | `$CLAUDE_PLUGIN_ROOT` set by Claude Code | ✓ worked | ✓ still works |
| Standalone symlink at `~/.claude/skills/uxaudit` | `$HOME/.claude/skills/uxaudit/SKILL.md` exists | ✓ worked | ✓ still works |
| Skill loaded by the Skill tool from a custom path | `$CLAUDE_SKILL_DIR` set by the Skill tool | ✗ failed | ✓ now works |
| Dev checkout at `~/Documents/projects/uxaudit/...` | Neither env var set, no symlink | ✗ failed | ✓ now resolved by dev-path lookup |
| Anything else | — | ✗ failed silently | ✗ fails with a clear error message |

For development, the cleanest setup is still to symlink your dev checkout into `~/.claude/skills/uxaudit`, but the new chain means an unconfigured developer can run `/uxaudit` and have it work the first time.
