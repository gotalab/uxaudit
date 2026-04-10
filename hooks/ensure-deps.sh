#!/usr/bin/env bash
#
# uxaudit SessionStart hook — lazy-install Playwright + Chromium.
#
# Design contract (read before editing):
#
#   1. **Playwright is pinned to an exact version in
#      `skills/uxaudit/package.json`** (and locked in `package-lock.json`).
#      Bumping is a deliberate maintainer action — see the "Bumping
#      Playwright" section of README.md. The pin is what gives the
#      plugin reproducibility across installations.
#
#   2. **node_modules** for uxaudit lives under $CLAUDE_PLUGIN_DATA
#      (per-plugin writable, persists across plugin updates). Nothing
#      installs globally; nothing leaks into other projects'
#      node_modules.
#
#   3. **Fast path** (must hold for the hook to no-op):
#      a. $CLAUDE_PLUGIN_DATA/node_modules/playwright/ exists
#      b. The package.json checked into the plugin matches the one
#         we previously copied to $CLAUDE_PLUGIN_DATA/package.json
#      If either is false, we re-run `npm ci` against the locked
#      package-lock.json to install the pinned version.
#
#   4. **The Chromium binary is intentionally NOT isolated.** We let
#      Playwright use its default per-user cache
#      (`~/Library/Caches/ms-playwright/` on macOS,
#       `~/.cache/ms-playwright/` on Linux) so:
#        - If the user already has Chromium from any other Playwright
#          project, we reuse it (saves ~300 MB).
#        - `npx playwright install chromium` itself is idempotent —
#          it checks the cache and no-ops when the version is already
#          present.
#      Trade-off: uninstalling the uxaudit plugin leaves Chromium in
#      the user's shared cache. That's the user's resource, not ours;
#      cleanup is `npx playwright uninstall` at their discretion.
#
#   5. **Prereq checks** (node, python3, npm) never abort the session
#      — they warn and exit 0. A missing prereq only bites when the
#      user actually invokes /uxaudit, at which point the orchestrator
#      surfaces a clean error.
#
#   6. **Force a clean re-install** (e.g. after editing package.json):
#         rm -rf "$CLAUDE_PLUGIN_DATA/uxaudit/node_modules"
#         rm -f  "$CLAUDE_PLUGIN_DATA/uxaudit/package.json"
#      Then run `/reload-plugins` in Claude Code.

set -u

SKILL_DIR="${CLAUDE_PLUGIN_ROOT:-}/skills/uxaudit"
SKILL_PKG="${SKILL_DIR}/package.json"
SKILL_LOCK="${SKILL_DIR}/package-lock.json"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-}"
DATA_PKG="${DATA_DIR}/package.json"
DATA_LOCK="${DATA_DIR}/package-lock.json"
PLAYWRIGHT_DIR="${DATA_DIR}/node_modules/playwright"
AXE_CORE_DIR="${DATA_DIR}/node_modules/axe-core"

# --- 1. Sanity: plugin runtime env --------------------------------------------
if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ] || [ -z "${CLAUDE_PLUGIN_DATA:-}" ]; then
  # Not running as a plugin — standalone dev mode handles its own bootstrap
  # (`cd skills/uxaudit && npm install`).
  exit 0
fi

# --- 2. Fast path: deps already installed and manifest unchanged --------------
if [ -d "$PLAYWRIGHT_DIR" ] && [ -d "$AXE_CORE_DIR" ] && diff -q "$SKILL_PKG" "$DATA_PKG" >/dev/null 2>&1; then
  exit 0
fi

# --- 3. Prereq checks — warn but do not block session start -------------------
if ! command -v node >/dev/null 2>&1; then
  echo "[uxaudit] WARN: Node 20+ not found in PATH — /uxaudit will not work until it is installed (e.g. via nvm or brew)." >&2
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "[uxaudit] WARN: python3 not found in PATH — /uxaudit will not work until it is installed (macOS/Linux ship with it by default)." >&2
  exit 0
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "[uxaudit] WARN: npm not found in PATH — install Node.js (which ships with npm) to enable /uxaudit." >&2
  exit 0
fi

# --- 4. Install pinned version into $CLAUDE_PLUGIN_DATA -----------------------
echo "[uxaudit] installing pinned Node dependencies ..." >&2

set -e
mkdir -p "$DATA_DIR"
cp "$SKILL_PKG" "$DATA_PKG"
cp "$SKILL_LOCK" "$DATA_LOCK"

(
  cd "$DATA_DIR"

  # `npm ci` is the strict reproducible install:
  #   - reads package-lock.json verbatim (fails if package.json disagrees)
  #   - wipes any existing node_modules first (clean install)
  #   - faster than `npm install` because no dep-tree resolution
  #
  # PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 suppresses Playwright's postinstall
  # browser download — we call `playwright install` explicitly below with
  # the user's shared cache so the call is a no-op when Chromium is
  # already present.
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    npm ci --silent --no-audit --no-fund >/dev/null

  # Idempotent: Playwright's own install command checks the shared cache
  # and skips any download whose hash/version is already present.
  # NOTE: no --with-deps — that requires sudo for apt/dnf packages
  #       and we never want a plugin hook running sudo.
  npx playwright install chromium >/dev/null
)

echo "[uxaudit] OK: Playwright dependencies ready" >&2
