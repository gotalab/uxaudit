#!/usr/bin/env python3
"""
Generate the unified uxaudit editorial dashboard.

ONE template (templates/dashboard.html) handles three main modes:
- single   — one app, one iteration
- timeline — one app, multiple iterations (user-facing label: History)
- compare  — multiple apps

The mode is auto-detected from the inputs.

Usage:
    # single iteration
    python generate_dashboard.py <iter-dir> [--target NAME] [--port PORT] [--static OUTPUT]

    # history (implemented by --timeline; multiple iterations of same app)
    python generate_dashboard.py <workspace-dir> --timeline [--target NAME]

    # comparison (multiple apps)
    python generate_dashboard.py <iter-dir-1> <iter-dir-2> ... --compare [--output PATH]
"""
import argparse
import base64
import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from functools import partial
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = SKILL_DIR / "templates" / "dashboard.html"


def _registry_dir() -> Path:
    """Where the cross-project registry + library.html live.

    Resolution order (first match wins):

    1. **`$UXAUDIT_HOME`** — explicit override. For CI, tests, or power
       users who want everything under a single pinned path. No
       existence check: if set, we trust it.

    2. **`$CLAUDE_PLUGIN_DATA` — but ONLY when uxaudit itself is running
       as a plugin.** Claude Code sets `CLAUDE_PLUGIN_DATA` to the data
       directory of the *currently invoking* plugin, not a global constant.
       A non-plugin skill invoked while some *other* plugin is active would
       pick up that foreign plugin's data dir and corrupt it. We guard by
       checking that SKILL_DIR is actually inside `~/.claude/plugins/cache/`
       — which is true iff Claude Code loaded us from the plugin marketplace.
       See: https://code.claude.com/docs/en/plugins-reference.md#persistent-data-directory

    3. **`$XDG_DATA_HOME/uxaudit/`** — XDG-aware users. The registry is
       data, not config, so this lives under `XDG_DATA_HOME`, not
       `XDG_CONFIG_HOME`. Per the XDG Base Directory spec.

    4. **`~/.agents/uxaudit/`** — default. Deliberately mirrors the
       per-project layout at `<project>/.agents/uxaudit/<target>/` so the
       directory naming is identical at both scopes. `.agents/` is an
       agent-neutral umbrella (no vendor lock-in to `.claude/` or
       `.cursor/` or similar), which matters because uxaudit is meant to
       be usable from any agent harness — or standalone, without any
       agent at all.

    The fallback is intentionally NOT `~/.claude/skills/uxaudit/` — the
    skill install dir should be treated as read-only because once we ship
    as a plugin the same path becomes `~/.claude/plugins/cache/<id>/` which
    IS read-only by design.
    """
    explicit = os.environ.get("UXAUDIT_HOME")
    if explicit:
        return Path(explicit).expanduser()

    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        try:
            plugins_cache = (Path.home() / ".claude" / "plugins" / "cache").resolve()
            if SKILL_DIR.resolve().is_relative_to(plugins_cache):
                return Path(plugin_data) / "uxaudit"
        except (OSError, ValueError):
            pass  # Path resolution failed — fall through

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data).expanduser() / "uxaudit"

    return Path.home() / ".agents" / "uxaudit"


REGISTRY_DIR = _registry_dir()
REGISTRY_PATH = REGISTRY_DIR / "registry.json"
REGISTRY_LOCK_PATH = REGISTRY_DIR / "registry.lock"
LIBRARY_PATH = REGISTRY_DIR / "library.html"


@contextlib.contextmanager
def _registry_lock():
    """Exclusive flock around any read-modify-write of registry.json.

    Two `/uxaudit` runs can finish in parallel (different projects, same
    machine). Without a lock the read-modify-write window inside
    `_register_workspace` is racy: A reads, B reads, A writes, B writes —
    A's update is silently lost.

    The lock file is a sentinel kept open only for the duration of the
    critical section. We `os.replace()` registry.json on commit, so the
    lock file is intentionally a *separate* path — replacing the lock'd
    file out from under flock would orphan the lock holder.

    Cooperative only: every writer must enter this context. Readers that
    only need a snapshot (e.g. _attach_library) can skip the lock and
    accept eventual consistency.
    """
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(REGISTRY_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*", type=Path,
                        help="Iteration dirs (containing benchmark.json) OR a workspace dir for --timeline")
    parser.add_argument("--target", default="")
    parser.add_argument("--port", "-p", type=int, default=3118)
    parser.add_argument("--static", "-s", type=Path, default=None,
                        help="Write standalone HTML file instead of serving")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't open browser automatically")
    parser.add_argument("--timeline", action="store_true",
                        help="Treat the single input as a workspace dir; show all iterations as project history")
    parser.add_argument("--compare", action="store_true",
                        help="Treat multiple inputs as separate apps; show side-by-side comparison")
    parser.add_argument("--design-system", type=Path, default=None,
                        help="Optional design-system.json with brand colors/fonts (project context)")
    parser.add_argument("--library", action="store_true",
                        help="Open the cross-project library view from ~/.agents/uxaudit/registry.json")
    parser.add_argument("--archive", type=Path, default=None,
                        help="Mark the given workspace path as archived in the registry, then exit")
    parser.add_argument("--unarchive", type=Path, default=None,
                        help="Unmark the given workspace path as archived in the registry, then exit")
    parser.add_argument("--remove", type=Path, action="append", default=None,
                        metavar="WORKSPACE",
                        help="Delete the given workspace from the registry (repeatable), then exit. "
                             "Files on disk are NOT touched — only the registry entry is removed.")
    parser.add_argument("--no-register", action="store_true",
                        help="Skip writing this workspace to the central registry")
    parser.add_argument("--no-embed-files", action="store_true",
                        help="Don't inline per-check evidence files (screenshots/videos) "
                             "as data URIs. Uses absolute file:// references instead — "
                             "the resulting dashboard.html is much smaller (often 100x+) "
                             "but only works on this machine. Default behavior: server "
                             "and per-workspace auto-write paths are slim (file://); "
                             "--static defaults to embed for portability. Pass this "
                             "flag to force no-embed even for --static exports.")
    args = parser.parse_args()

    # Standalone registry mutations — short-circuit
    if args.archive is not None:
        return _set_archived(args.archive, True)
    if args.unarchive is not None:
        return _set_archived(args.unarchive, False)
    if args.remove:
        return _remove_workspaces(args.remove)

    # Library mode — load the registry, render a cross-project grid
    if args.library:
        return _run_library(args)

    if not args.inputs:
        print("❌ no inputs given. Use --library to view the cross-project index, or pass an iteration/workspace path.", file=sys.stderr)
        return 1

    # Embed-files policy:
    # - --no-embed-files explicit: always wins (forced no-embed)
    # - --static (portable export): default embed=True so the html is shareable
    # - server / no --static (local view): default embed=False so it's slim
    if args.no_embed_files:
        embed_files = False
    elif args.static:
        embed_files = True   # explicit export defaults to portable
    else:
        embed_files = False  # local view defaults to slim

    # Resolve inputs into the unified envelope
    payload = build_payload(args.inputs, args.target, timeline=args.timeline,
                            compare=args.compare, embed_files=embed_files)
    if payload is None:
        return 1

    # Optional design system overlay
    if args.design_system and args.design_system.exists():
        try:
            payload["design_system"] = json.loads(args.design_system.read_text())
        except json.JSONDecodeError as e:
            print(f"⚠️  invalid --design-system JSON: {e}", file=sys.stderr)

    # Register every workspace touched in this run BEFORE rendering, so the
    # Library tab in the rendered dashboard reflects the latest state.
    #
    # Two passes are required because _attach_library() checks `dash.exists()`
    # for every registry entry to flag `_missing`. If we render a workspace
    # before its sibling workspaces (or itself) have a dashboard.html on
    # disk, those entries get baked in as _missing=True. Splitting into
    # register+touch → render fixes both the self-missing bug and the
    # sibling-missing bug in compare runs.
    if not args.no_register:
        # Pass 1: register every workspace AND ensure its dashboard.html
        # exists on disk before any rendering happens.
        pending: list[tuple[Path, dict, Path]] = []
        for ws_path in _workspaces_in_payload(payload):
            try:
                static_dest = ws_path / "dashboard.html"
                ws_payload = _build_single_workspace_payload(ws_path)
                if ws_payload is not None:
                    _register_workspace(ws_path, ws_payload, static_dest)
                    static_dest.touch(exist_ok=True)
                    pending.append((ws_path, ws_payload, static_dest))
            except OSError as e:
                print(f"⚠️  could not prepare {ws_path}/dashboard.html: {e}", file=sys.stderr)

        # Pass 2: now that every dashboard.html exists, render each one
        # with an _attach_library() that won't falsely mark anything _missing.
        for ws_path, ws_payload, static_dest in pending:
            try:
                _attach_library(ws_payload)
                static_dest.write_text(render(ws_payload), encoding="utf-8")
            except OSError as e:
                print(f"⚠️  could not write {ws_path}/dashboard.html: {e}", file=sys.stderr)

        # Pass 3: refresh the standalone full-Library page so the
        # "Open full Library →" link in every per-workspace lite banner
        # always opens an up-to-date page. Cheap (one file write) and
        # the only place cross-project Compare actually works.
        try:
            _emit_full_library_html()
        except OSError as e:
            print(f"⚠️  could not write standalone library.html: {e}", file=sys.stderr)

    # Attach the registry to the main payload so the Library tab works from
    # any dashboard the user opens (server or static).
    _attach_library(payload)
    html = render(payload)

    if args.static:
        args.static.parent.mkdir(parents=True, exist_ok=True)
        args.static.write_text(html, encoding="utf-8")
        print(f"📄 Dashboard written to {args.static}")
        if not args.no_open:
            webbrowser.open(f"file://{args.static.resolve()}")
        return 0

    # Server mode
    port = args.port
    _kill_port(port)
    allowed_dirs, allowed_files = _collect_allowed_paths(payload)
    handler = partial(DashboardHandler, payload, allowed_dirs, allowed_files)
    # ThreadingHTTPServer because the dashboard fires 30+ image requests in
    # parallel as the user scrolls; a single-threaded BaseHTTPServer would
    # serialize them and stall. The handler is read-only so it's safe.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]

    url = f"http://localhost:{port}"
    print(f"\n  uxaudit dashboard")
    print(f"  ───────────────────")
    print(f"  URL:    {url}")
    print(f"  Mode:   {payload.get('_mode', 'single')}")
    print(f"\n  Ctrl+C to stop.\n")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
    return 0


# ──────────────────────────────────────────────────────────
# Payload building
# ──────────────────────────────────────────────────────────

def build_payload(inputs: list[Path], target_hint: str, *,
                  timeline: bool, compare: bool, embed_files: bool = True) -> dict | None:
    """Build the unified data envelope: {apps: [{name, url, iterations: [...]}], _mode}.

    The dashboard ALWAYS receives a rich payload — all apps with all their iterations.
    The topbar mode switcher (Audit / History / Compare) decides what to render from
    that one payload. There is never a reason to open multiple dashboard files.

    Input resolution:
    - A workspace dir (contains iteration-*) → collect all iterations as one app
    - An iteration-* dir → that single iteration of its parent workspace
    - Multiple inputs → each resolved separately, grouped by parent workspace,
      so passing two workspaces gives you two apps with all their iterations.

    `embed_files` controls how per-check evidence (screenshots/videos) is
    delivered to the dashboard:
    - True (default): inline as base64 data URIs — fully portable single
      file, but the html bloats to tens of MB on a long iteration history.
    - False: store absolute file:// references instead — much smaller html
      but only renders correctly on the same machine where the audit ran.
    """
    apps_by_workspace: dict[Path, list[Path]] = {}

    def add_workspace(ws: Path, restrict_to: Path | None = None):
        ws = ws.resolve()
        if restrict_to is not None:
            apps_by_workspace.setdefault(ws, []).append(restrict_to.resolve())
            return
        # Collect ALL iterations of this workspace
        iters = sorted(
            [p for p in ws.glob("iteration-*") if p.is_dir()],
            key=lambda p: _iter_num(p),
        )
        existing = apps_by_workspace.setdefault(ws, [])
        for it in iters:
            if it not in existing:
                existing.append(it)

    for p in inputs:
        p = p.resolve()
        if p.is_dir() and p.name.startswith("iteration-"):
            add_workspace(p.parent, restrict_to=p)
        elif p.is_dir():
            add_workspace(p)
        elif p.name == "benchmark.json":
            iter_dir = p.parent
            add_workspace(iter_dir.parent, restrict_to=iter_dir)
        else:
            print(f"❌ unrecognized input: {p}", file=sys.stderr)
            return None

    # Always expand each workspace to ALL its iterations (so timeline works
    # even if the user passed a single iteration, as long as siblings exist)
    enriched: dict[Path, list[Path]] = {}
    for ws, iters in apps_by_workspace.items():
        all_iters = sorted(
            [p for p in ws.glob("iteration-*") if p.is_dir()],
            key=lambda p: _iter_num(p),
        )
        # If user passed specific iterations, prefer those order; but augment with siblings
        seen = set()
        merged = []
        for it in iters + all_iters:
            r = it.resolve()
            if r not in seen:
                seen.add(r)
                merged.append(r)
        enriched[ws] = sorted(merged, key=lambda p: _iter_num(p))

    apps = []
    for ws, iters in enriched.items():
        hint = target_hint if len(enriched) == 1 else None
        app = build_app_from_iters(iters, hint or ws.name, embed_files=embed_files)
        if app:
            # Stash the workspace path so registration can find it later
            app["_workspace_path"] = str(ws)
            apps.append(app)

    if not apps:
        print("❌ no benchmark.json found in any input", file=sys.stderr)
        return None

    # Determine the natural starting mode (the dashboard topbar can switch to any other)
    if len(apps) > 1:
        starting_mode = "compare"
    elif len(apps[0]["iterations"]) > 1:
        starting_mode = "timeline"
    else:
        starting_mode = "single"

    return {
        "apps": apps,
        "design_system": None,
        "_mode": starting_mode,
        "_capabilities": {
            "single": True,
            "timeline": any(len(a["iterations"]) > 1 for a in apps),
            "compare": len(apps) > 1,
        },
    }


def _iter_num(p: Path) -> int:
    try:
        return int(p.name.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _looks_like_separate_apps(iters: list[tuple[Path, Path]]) -> bool:
    """Heuristic: if the parent workspaces differ, treat as separate apps."""
    if len(iters) < 2:
        return False
    parents = {p.parent.resolve() for p, _ in iters}
    return len(parents) > 1


def build_app_from_iters(iter_dirs: list[Path], hint: str | None,
                         *, embed_files: bool = True) -> dict | None:
    """Read a list of iteration dirs into a single app entry.

    `embed_files`:
    - True (default): inline screenshots/videos as base64 data URIs.
      Single-file portable html, but bloats fast.
    - False: store absolute file:// URLs in the same `data_uri` field.
      Dashboard renders identically locally; cannot be moved off the
      machine where the audit ran.
    """
    if not iter_dirs:
        return None
    iterations = []
    inferred_name = None
    inferred_url = None
    for iter_dir in iter_dirs:
        bench_path = iter_dir / "benchmark.json"
        if not bench_path.exists():
            continue
        try:
            bench = json.loads(bench_path.read_text())
        except json.JSONDecodeError as e:
            print(f"⚠️  invalid {bench_path}: {e}", file=sys.stderr)
            continue
        meta = bench.get("metadata") or {}
        if inferred_name is None:
            inferred_name = meta.get("target") or iter_dir.parent.name
        if inferred_url is None:
            inferred_url = meta.get("url", "")

        screenshot_uri = ""
        screenshot_path = iter_dir / "target" / "screenshot.png"
        if screenshot_path.exists():
            if embed_files:
                try:
                    screenshot_uri = (
                        "data:image/png;base64,"
                        + base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
                    )
                except OSError:
                    pass
            else:
                # Absolute file:// URL — same field, dashboard JS just
                # passes it to <img src=> which doesn't care about scheme.
                screenshot_uri = "file://" + str(screenshot_path.resolve())

        # Pull viewport / target kind from the capture meta. This is what the
        # dashboard uses for the per-iteration badge.
        viewport_info = None
        target_kind = None
        meta_path = iter_dir / "target" / "meta.json"
        if meta_path.exists():
            try:
                cap_meta = json.loads(meta_path.read_text())
                viewport_info = cap_meta.get("viewport") or None
                target_kind = cap_meta.get("kind") or None
            except (json.JSONDecodeError, OSError):
                pass

        # Per-check evidence (screenshots, waypoint images, journey videos).
        # Two delivery modes share the same `embedded_files[].data_uri` field
        # so the dashboard JS doesn't need to branch:
        # - embed=True : data:<mime>;base64,<bytes>  (portable, fat)
        # - embed=False: file://<absolute path>      (local-only, slim)
        IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        VIDEO_EXTS = {".webm", ".mp4", ".mov"}
        MAX_BYTES_PER_FILE = 8 * 1024 * 1024  # 8 MB cap so the dashboard stays portable
        for check in bench.get("checks", []):
            evidence = check.setdefault("evidence", {})
            files = evidence.get("files") or []
            embedded = []
            for f in files:
                try:
                    fp = (iter_dir / f).resolve()
                    fp.relative_to(iter_dir.resolve())
                except (OSError, ValueError):
                    continue
                if not fp.exists():
                    continue
                ext = fp.suffix.lower()
                if ext in IMAGE_EXTS:
                    mime = f"image/{'jpeg' if ext == '.jpg' else ext[1:]}"
                elif ext in VIDEO_EXTS:
                    mime = f"video/{ext[1:]}"
                else:
                    continue
                try:
                    if embed_files:
                        if fp.stat().st_size > MAX_BYTES_PER_FILE:
                            continue
                        data = fp.read_bytes()
                        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
                    else:
                        # No size cap when not embedding — bytes never get
                        # loaded into the html, the browser fetches lazily.
                        uri = "file://" + str(fp.resolve())
                    embedded.append({
                        "name": fp.name,
                        "data_uri": uri,
                    })
                except OSError:
                    pass
            if embedded:
                evidence["embedded_files"] = embedded

        iterations.append({
            "iteration": _iter_num(iter_dir),
            "label": iter_dir.name,
            "generated_at": meta.get("generated_at"),
            "summary": bench.get("summary") or {},
            "checks": bench.get("checks") or [],
            "screenshot_data_uri": screenshot_uri,
            "viewport": viewport_info,
            "target_kind": target_kind,
            "scenario_mode": meta.get("scenario_mode") or "",
            "scenario_source_iteration": meta.get("scenario_source_iteration") or "",
            "comparable_to_previous": meta.get("comparable_to_previous"),
            # Step 15 Proposer output. Embedded by aggregate.py if present.
            # The dashboard uses this to render the "Top fixes" section.
            "improvement_proposal": bench.get("improvement_proposal"),
            # Audit language pinned at /uxaudit invocation. Surfaces from
            # benchmark.json metadata so the dashboard's currentLang init can
            # default to it instead of always falling back to 'en'. Empty string
            # = no language was set, dashboard uses its localStorage / 'en'
            # behavior. See references/subagents/language-preamble.md.
            "language": meta.get("language") or "",
        })

    if not iterations:
        return None

    iterations.sort(key=lambda it: it["iteration"])
    return {
        "name": hint or inferred_name or "untitled",
        "url": inferred_url or "",
        "iterations": iterations,
    }


# ──────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────

def render(payload: dict) -> str:
    template = TEMPLATE_PATH.read_text()
    title_parts = []
    for app in payload.get("apps", []):
        title_parts.append(app["name"])
    title = " · ".join(title_parts) or "uxaudit"
    data_json = _json_for_html_script(payload)
    html = template.replace("__EMBEDDED_DATA__", data_json)
    html = html.replace("__TITLE__", _escape_html(title))
    html = html.replace("__TARGET__", _escape_html(title))
    return html


def _escape_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace('"', "&quot;").replace("'", "&#39;"))


def _json_for_html_script(data: dict) -> str:
    """Serialize JSON safely for embedding inside a <script> tag."""
    return (json.dumps(data, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


# ──────────────────────────────────────────────────────────
# Server
# ──────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the in-process dashboard server.

    Serves three things:
      1. `/` and `/index.html` — the rendered dashboard HTML.
         Before sending, every literal `file://...` reference (used by the
         slim no-embed payload mode) is rewritten to `/file?path=<encoded>`
         so the browser will fetch via the same http: origin instead of
         being blocked by the file:// scheme isolation.
      2. `/file?path=<urlencoded absolute path>` — serves bytes from disk.
         Path must resolve to a generated dashboard artifact we explicitly
         allow. Anything else returns 403 — this is a localhost-bound dev
         tool but we still don't want a curl loop to walk the repo.
      3. Everything else → 404.
    """

    # Computed once per server instance (set by `partial(...)` in main())
    _allowed_dirs: list[Path] = []
    _allowed_files: set[Path] = set()

    def __init__(self, payload, allowed_dirs, allowed_files, *args, **kwargs):
        self.payload = payload
        self._allowed_dirs = allowed_dirs
        self._allowed_files = allowed_files
        super().__init__(*args, **kwargs)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs, unquote, quote
        import mimetypes

        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            html = render(self.payload)
            # Rewrite every literal file:// occurrence in the rendered HTML
            # to /file?path=<encoded> so the browser fetches via http: origin.
            # We only need to touch URLs that point to files inside the
            # allowed roots — anything else is left untouched (it'll 404 or
            # 403 the same way it does today).
            def rewrite(m: re.Match) -> str:
                url = m.group(0)
                # Strip the scheme and any trailing quote/space the regex
                # accidentally captured.
                raw_path = unquote(url[len("file://"):])
                # Drop any trailing JSON / HTML delimiter that snuck in.
                raw_path = raw_path.rstrip('"\\').rstrip("'").rstrip()
                if not raw_path:
                    return url
                try:
                    abs_path = Path(raw_path).resolve()
                except OSError:
                    return url
                if not self._is_allowed(abs_path):
                    return url
                # Always re-percent-encode so spaces / non-ASCII don't break.
                return "/file?path=" + quote(str(abs_path), safe="")

            html = re.sub(r'file://[^"\'\s<>]+', rewrite, html)
            content = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if route == "/file":
            params = parse_qs(parsed.query)
            raw = params.get("path", [None])[0]
            if not raw:
                self.send_error(400, "missing ?path=")
                return
            try:
                target = Path(unquote(raw)).resolve()
            except OSError:
                self.send_error(400, "invalid path")
                return
            if not self._is_allowed(target):
                self.send_error(403, "path outside allowed roots")
                return
            if not target.is_file():
                self.send_error(404, "not a file")
                return
            ctype, _ = mimetypes.guess_type(str(target))
            if ctype is None:
                ctype = "application/octet-stream"
            try:
                data = target.read_bytes()
            except OSError as e:
                self.send_error(500, f"read failed: {e}")
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # Allow caching — these files are immutable artifacts.
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)

    def _is_allowed(self, abs_path: Path) -> bool:
        """True iff abs_path is a known dashboard/library file or generated artifact."""
        try:
            if abs_path in self._allowed_files:
                return True
            for root in self._allowed_dirs:
                try:
                    abs_path.relative_to(root)
                    return True
                except ValueError:
                    continue
        except OSError:
            return False
        return False

    def log_message(self, *args, **kwargs):
        pass  # quiet


def _collect_allowed_paths(payload: dict) -> tuple[list[Path], set[Path]]:
    """Build the allowlist of generated artifacts the dashboard server may read."""
    dirs: set[Path] = set()
    files: set[Path] = set()
    for ws in _workspaces_in_payload(payload):
        try:
            resolved = ws.resolve()
            files.add((resolved / "dashboard.html").resolve())
            dirs.add((resolved / "target").resolve())
            dirs.add((resolved / "checks").resolve())
        except OSError:
            pass
    try:
        files.add(LIBRARY_PATH.resolve())
    except OSError:
        pass
    return sorted(dirs), files


def _kill_port(port: int) -> None:
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if pid_str.strip():
                try:
                    os.kill(int(pid_str.strip()), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
        if result.stdout.strip():
            time.sleep(0.5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


# ──────────────────────────────────────────────────────────
# Registry & Library
# ──────────────────────────────────────────────────────────

def _workspaces_in_payload(payload: dict) -> list[Path]:
    """Reverse-lookup workspace dirs from a payload's iteration paths.

    The payload doesn't carry workspace paths directly, so we recover them
    from the iteration metadata embedded during build_payload(). For each
    app we look at the resolved iteration source path (we re-derive from
    the global enriched dict at build time isn't available here), so we
    instead reconstruct from the app name + a search of the cwd-relative
    paths the user passed in. Simpler: we walk the payload looking for
    iterations and find their parent directories on disk.
    """
    seen: set[Path] = set()
    out: list[Path] = []
    for app in payload.get("apps", []):
        # Iterations carry no path back-reference, so we accept that the
        # caller of build_payload tracked which workspace each app came
        # from via the apps_by_workspace dict. To stay simple, this helper
        # just returns nothing if it can't find paths — registration is
        # done by _register_workspace which is called explicitly with a
        # known path. This function is a fallback used by the auto-write
        # path; the canonical path comes from the build_payload caller.
        path = app.get("_workspace_path")
        if path:
            p = Path(path).resolve()
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _build_single_workspace_payload(workspace_path: Path) -> dict | None:
    """Render-ready payload for a single workspace's full timeline.

    Per-workspace static dashboards live next to the iteration data
    they reference (`<workspace>/dashboard.html` alongside
    `<workspace>/iteration-N/...`), so file:// references to evidence
    files are always resolvable. We force `embed_files=False` here so
    these auto-written dashboards stay slim — typically 100x smaller
    than the embed variant — without sacrificing any rendering. The
    portability tradeoff (sharing the file across machines) doesn't
    apply because the workspace itself isn't portable either.
    """
    payload = build_payload([workspace_path], "", timeline=True, compare=False,
                            embed_files=False)
    if payload is None:
        return None
    # Single-workspace dashboards default to timeline mode if multiple iters
    apps = payload.get("apps", [])
    if not apps:
        return None
    if len(apps[0].get("iterations", [])) > 1:
        payload["_mode"] = "timeline"
    else:
        payload["_mode"] = "single"
    return payload


REGISTRY_VERSION = 1


def _load_registry() -> dict:
    # Sweep an orphan registry.json.tmp left by a crashed writer. Safe to
    # delete iff it's older than the live registry.json (or if registry.json
    # doesn't exist yet) — that proves no commit ever happened. We avoid
    # deleting a tmp from an in-flight save by requiring it be >5s old.
    tmp_path = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".tmp")
    try:
        if tmp_path.exists():
            tmp_age = time.time() - tmp_path.stat().st_mtime
            if tmp_age > 5:
                tmp_path.unlink()
    except OSError:
        pass  # Best-effort cleanup; never block load on it.

    if not REGISTRY_PATH.exists():
        return {"workspaces": [], "registry_version": REGISTRY_VERSION}
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  registry corrupt ({e}); starting fresh", file=sys.stderr)
        return {"workspaces": [], "registry_version": REGISTRY_VERSION}


def _save_registry(registry: dict) -> None:
    """Persist the registry. Two safety properties:

    1. **Atomic**: write to a sibling temp file first, then `os.replace()`
       onto the target. POSIX guarantees `replace` is atomic on the same
       filesystem, so a crash mid-write can never leave a partially-written
       registry.json on disk — readers see either the old version or the
       new one, never a half-truncated mix.

    2. **Versioned**: every save stamps `registry_version` so future schema
       migrations have an anchor. New entries default to the current
       REGISTRY_VERSION even if the loaded registry was older.
    """
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    registry.setdefault("registry_version", REGISTRY_VERSION)
    payload = json.dumps(registry, indent=2, ensure_ascii=False)
    tmp_path = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".tmp")
    tmp_path.write_text(payload)
    os.replace(tmp_path, REGISTRY_PATH)


def _slim_check(check: dict) -> dict:
    """Reduce a full check result to the minimum fields needed for cross-
    workspace compare. Drops heavy stuff (matches list, embedded_files,
    rationale, evidence.details long text). Used by the library registry
    so compare can be run across workspaces from the Library tab without
    bloating the registry.
    """
    ev = check.get("evidence") or {}
    # Truncate free-form details so the registry stays roughly bounded;
    # compare uses this only for a tooltip / secondary summary.
    details = (ev.get("details") or "")
    if len(details) > 280:
        details = details[:277] + "…"
    return {
        "check_id":  check.get("check_id") or "",
        "name":      check.get("name") or check.get("check_id") or "",
        "category":  check.get("category") or "",
        "band":      check.get("band"),
        "subtype":   check.get("subtype"),
        "method":    check.get("method"),
        "severity":  check.get("severity"),
        "result":    check.get("result"),
        "source":    check.get("source"),
        "suggestion": check.get("suggestion") or "",
        "details":   details,
    }


def _register_workspace(workspace_path: Path, payload: dict, dashboard_html: Path) -> None:
    """Add or update an entry in ~/.agents/uxaudit/registry.json.

    Stores light summary metadata plus a slim per-check array from the
    latest iteration so the Library tab can drive cross-workspace
    compare without loading each workspace's full dashboard.
    """
    workspace_path = workspace_path.resolve()
    apps = payload.get("apps", [])
    if not apps:
        return
    app = apps[0]
    iterations = app.get("iterations", [])
    if not iterations:
        return

    latest = iterations[-1]
    latest_summary = latest.get("summary") or {}
    latest_checks = latest.get("checks") or []
    # Slim check data for cross-workspace compare. Keeps the registry
    # bounded (~500B × N checks × M workspaces).
    checks_slim = [_slim_check(c) for c in latest_checks]
    sparkline = []
    # Cap at the last 60 iterations. The Library card sparkline is ~120px
    # wide so >60 points become an unreadable forest of dots, and the
    # registry would otherwise grow unbounded with iteration count.
    for it in iterations[-60:]:
        s = it.get("summary") or {}
        rate = s.get("pass_rate")
        sparkline.append({
            "iter": it.get("iteration"),
            "label": it.get("label"),
            "pass_rate": rate,
            "pct": int(round((rate or 0) * 100)),
            "total": s.get("total", 0),
            "failed": s.get("failed", 0),
        })

    with _registry_lock():
        registry = _load_registry()
        workspaces = registry.setdefault("workspaces", [])
        now_iso = datetime.now(timezone.utc).isoformat()

        # Opportunistic cleanup: prune stale entries whose dashboard file no
        # longer exists. This is the only "write path" that actually rewrites
        # the registry on disk, so piggybacking the compaction here keeps the
        # file from growing unbounded without needing a dedicated --prune CLI
        # command. Archived entries are preserved regardless of disk state so
        # intentional archives aren't nuked when the file happens to be on an
        # unmounted volume.
        workspaces[:] = [
            w for w in workspaces
            if w.get("archived") or Path(w.get("dashboard", "")).exists()
        ]

        existing = next(
            (w for w in workspaces if Path(w["path"]).resolve() == workspace_path),
            None,
        )
        record = {
            "path": str(workspace_path),
            "target": app.get("name") or workspace_path.name,
            "url": app.get("url", ""),
            "dashboard": str(dashboard_html.resolve()),
            "iteration_count": len(iterations),
            "latest_pass_rate": latest_summary.get("pass_rate"),
            "latest_passed": latest_summary.get("passed", 0),
            "latest_failed": latest_summary.get("failed", 0),
            "latest_skipped": latest_summary.get("skipped", 0),
            "latest_total": latest_summary.get("total", 0),
            "latest_label": latest.get("label"),
            "latest_run_at": latest.get("generated_at") or now_iso,
            "latest_viewport": (latest.get("viewport") or {}).get("preset")
                                or _viewport_label(latest.get("viewport")),
            "latest_target_kind": latest.get("target_kind"),
            "latest_checks": checks_slim,
            "first_seen_at": (existing or {}).get("first_seen_at") or now_iso,
            "last_updated_at": now_iso,
            "sparkline": sparkline,
            "archived": (existing or {}).get("archived", False),
            "tags": (existing or {}).get("tags", []),
        }

        if existing:
            existing.update(record)
        else:
            workspaces.append(record)

        _save_registry(registry)


def _set_archived(workspace_path: Path, archived: bool) -> int:
    workspace_path = workspace_path.resolve()
    with _registry_lock():
        registry = _load_registry()
        workspaces = registry.get("workspaces", [])
        for w in workspaces:
            if Path(w["path"]).resolve() == workspace_path:
                w["archived"] = archived
                _save_registry(registry)
                verb = "archived" if archived else "unarchived"
                print(f"📦 {verb}: {workspace_path}")
                return 0
    print(f"❌ workspace not in registry: {workspace_path}", file=sys.stderr)
    print(f"   run /uxaudit on this workspace first to register it.", file=sys.stderr)
    return 1


def _remove_workspaces(paths: list[Path]) -> int:
    """Delete one or more workspace entries from the central registry.

    Files on disk (dashboards, benchmarks, screenshots) are intentionally
    left alone — this only purges the Library's view of them. Use this to
    drop stale, moved, or test-fixture entries that you don't want to see
    in the Library tab anymore.

    Returns 0 if every requested path was found and removed, else 1.
    """
    with _registry_lock():
        registry = _load_registry()
        workspaces = registry.get("workspaces", [])
        targets = {p.resolve() for p in paths}
        kept: list[dict] = []
        removed: list[Path] = []
        for w in workspaces:
            try:
                wp = Path(w["path"]).resolve()
            except (KeyError, OSError):
                kept.append(w)
                continue
            if wp in targets:
                removed.append(wp)
            else:
                kept.append(w)
        if not removed:
            print(f"❌ no matching workspaces in registry:", file=sys.stderr)
            for t in targets:
                print(f"   {t}", file=sys.stderr)
            return 1
        registry["workspaces"] = kept
        _save_registry(registry)
    for r in removed:
        print(f"🗑  removed from registry: {r}")
    not_found = targets - {r for r in removed}
    if not_found:
        for nf in not_found:
            print(f"⚠️  not in registry (skipped): {nf}", file=sys.stderr)
        return 1
    return 0


def _viewport_label(vp: dict | None) -> str | None:
    """Turn a viewport dict into a short label like 'mobile' or '1024x768'."""
    if not vp:
        return None
    if vp.get("preset"):
        return vp["preset"]
    if vp.get("width") and vp.get("height"):
        return f"{vp['width']}x{vp['height']}"
    return None


def _latest_iteration_dir(workspace_path: Path) -> Path | None:
    """Return the newest iteration-N directory under a workspace, or None."""
    try:
        iters = [p for p in workspace_path.iterdir()
                 if p.is_dir() and p.name.startswith("iteration-")]
    except OSError:
        return None
    if not iters:
        return None
    iters.sort(key=lambda p: _iter_num(p))
    return iters[-1]


def _lazy_load_slim_checks(workspace_path: str) -> list[dict]:
    """For registry entries written before `latest_checks` was stored,
    peek at the workspace's latest benchmark.json and build a slim array
    on the fly. Returns [] if anything goes wrong — compare mode just
    skips that workspace gracefully."""
    try:
        wp = Path(workspace_path)
        if not wp.exists():
            return []
        iter_dir = _latest_iteration_dir(wp)
        if not iter_dir:
            return []
        bench_path = iter_dir / "benchmark.json"
        if not bench_path.exists():
            return []
        bench = json.loads(bench_path.read_text())
        checks = bench.get("checks") or []
        return [_slim_check(c) for c in checks]
    except (OSError, json.JSONDecodeError):
        return []


def _attach_library(payload: dict, *, with_check_data: bool = False) -> None:
    """Bake the current registry into a payload so its Library tab works.

    Two flavors of "library payload":

    - **Lite (default, `with_check_data=False`)**: only summary metadata
      per workspace (target, pass_rate, sparkline, dashboard path,
      viewport). This is what every per-workspace dashboard.html gets.
      Drops `latest_checks` to keep the embedded payload small — a 50
      project / 100-check registry was previously inflating *every*
      generated dashboard by ~2.5MB. Cross-workspace Compare is not
      available in lite mode; the dashboard surfaces an "Open full
      Library →" link instead so the user can jump to library.html
      where compare actually works.

    - **Full (`with_check_data=True`)**: includes the slim per-check
      array (`latest_checks`) so cross-workspace Compare can build its
      check×app matrix. Used only by `_run_library()` when generating
      the standalone `~/.agents/uxaudit/library.html` page, which is
      the canonical home for cross-project comparison.

    Stale registry entries (dashboards whose HTML file no longer exists on
    disk — deleted iteration dirs, moved projects, /tmp test fixtures) are
    auto-pruned from the in-memory payload so they never render as noisy
    "file not found" cards. They stay in registry.json until the next
    `_register_workspace` call, which also compacts the persisted file.
    The archived filter still sees them via the CLI, but the default
    library view is kept clean.
    """
    registry = _load_registry()
    workspaces = registry.get("workspaces", [])
    alive = []
    for w in workspaces:
        dash = Path(w.get("dashboard", ""))
        if not dash.exists():
            # Skip — don't render cards for dashboards that no longer exist
            continue
        record = dict(w)
        if with_check_data:
            # Backwards-compat: older registry entries have no latest_checks.
            # Lazy-load from the workspace's benchmark.json so compare works.
            if not record.get("latest_checks"):
                slim = _lazy_load_slim_checks(record.get("path", ""))
                if slim:
                    record["latest_checks"] = slim
        else:
            # Lite payload — strip the per-check array entirely. This is
            # the primary bloat reduction: registry × N workspaces was
            # being baked into every dashboard. Sub-keys like
            # `latest_total/passed/failed` stay so cards still show counts.
            record.pop("latest_checks", None)
        alive.append(record)

    payload.setdefault("library", {})
    payload["library"]["workspaces"] = alive
    payload["library"]["registry_path"] = str(REGISTRY_PATH)
    payload["library"]["library_html_path"] = str(LIBRARY_PATH)
    payload["library"]["with_check_data"] = with_check_data
    # Embed the absolute path of this script so the dashboard can show a
    # runnable archive/unarchive command without the CLAUDE_PLUGIN_ROOT
    # placeholder. Users copy the command to clipboard from the library
    # card and paste it into a terminal — see the libCard JS.
    payload["library"]["script_path"] = str(Path(__file__).resolve())

    caps = payload.setdefault("_capabilities", {"single": True, "timeline": False, "compare": False})
    caps["library"] = len(alive) > 0


def _build_full_library_payload() -> tuple[dict, list[dict]]:
    """Build the full-data library payload used by both `_run_library`
    (the explicit `--library` CLI command) and `_emit_full_library_html`
    (the auto-refresh on every audit run). Single source of truth so
    the standalone library.html stays consistent regardless of how it
    was generated."""
    payload = {
        "_mode": "library",
        "_capabilities": {"single": False, "timeline": False, "compare": False},
        "apps": [],  # library mode renders from .library, not .apps
    }
    _attach_library(payload, with_check_data=True)
    alive = payload.get("library", {}).get("workspaces", [])
    return payload, alive


def _emit_full_library_html() -> None:
    """Refresh ~/.agents/uxaudit/library.html in place.

    Called from the audit run path so the "Open full Library →" link in
    every per-workspace lite banner always reaches an up-to-date page.
    Skips silently if there are no live workspaces yet (first-ever run
    of a brand-new install) — the lite banner won't show in that case
    either since there's nothing to point at.
    """
    payload, alive = _build_full_library_payload()
    if not alive:
        return
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    html = render(payload)
    LIBRARY_PATH.write_text(html, encoding="utf-8")


def _run_library(args) -> int:
    """Render the cross-project Library dashboard from the central registry.

    This is the canonical home for cross-workspace Compare, so we ask
    `_attach_library` for the full payload (`with_check_data=True`)
    including the per-check slim array. Per-workspace dashboards get the
    lite payload by default.
    """
    payload, alive = _build_full_library_payload()
    html = render(payload)

    if args.static:
        args.static.parent.mkdir(parents=True, exist_ok=True)
        args.static.write_text(html, encoding="utf-8")
        print(f"📄 Library dashboard written to {args.static}")
        if not args.no_open:
            webbrowser.open(f"file://{args.static.resolve()}")
        return 0

    # Default: write to ~/.agents/uxaudit/library.html and open it via file://
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(html, encoding="utf-8")
    print(f"\n  uxaudit library")
    print(f"  ─────────────────")
    print(f"  Workspaces: {len(alive)}")
    print(f"  File:       {LIBRARY_PATH}\n")
    if not args.no_open:
        webbrowser.open(f"file://{LIBRARY_PATH.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
