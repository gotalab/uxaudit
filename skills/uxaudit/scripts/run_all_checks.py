#!/usr/bin/env python3
"""
uxaudit orchestrator.

Captures a target URL once, then runs every discovered check (L1 scripts and L2 node scripts)
against the captured artifacts, writes results into iteration-N/checks/, runs aggregate.py,
and optionally launches the dashboard.

If `<iter-dir>/journey-scripts/*.json` exist (produced by the Step 9 Journey Compiler
subagent), this orchestrator also fans out `capture_journey.mjs` in parallel for each
compiled journey, populating per-journey evidence directories under
`<iter-dir>/checks/core-experience-primary-journey-<N>-<slug>/`. The downstream
L4 Judge subagents (Step 11 of the playbook) then read those evidence directories
without needing a live browser.

Usage:
    python run_all_checks.py <target> --url <url> [--workspace <dir>] [--only cat1,cat2] [--skip cat3] [--no-dashboard] [--no-capture]
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]  # uxaudit/
CHECKS_DIR = SKILL_DIR / "checks"
SCRIPTS_DIR = SKILL_DIR / "scripts"


def _resolve_workspace(explicit: str | None, target: str) -> Path:
    """Resolve where this run's workspace lives.

    Resolution:

    1. **Explicit `--workspace`** — power-user override, no questions asked.
    2. **`./.agents/uxaudit/<target>/`** — default. The `.agents/` convention
       is multi-tool (Cline, Cursor, Claude Code, future agents) and the
       `uxaudit/<target>/` namespace keeps multiple targets in one repo
       cleanly scoped under a single directory rather than scattering
       sibling workspace folders at the project root.

    The function only RESOLVES the path; it does not create directories.
    The caller is responsible for `mkdir(parents=True, exist_ok=True)`.
    """
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".agents" / "uxaudit" / target


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the uxaudit checks against a target")
    parser.add_argument("target", help="Target name (used for workspace dir)")
    parser.add_argument("--url", default=None, help="URL of the running app (web targets)")
    parser.add_argument("--electron-app", default=None,
                        help="Path to an Electron app entry point or package dir (Electron targets)")
    parser.add_argument("--viewport", default=None,
                        help="Viewport preset (mobile|tablet|desktop) or WIDTHxHEIGHT for web targets")
    parser.add_argument("--viewports", default=None,
                        help="Comma-separated list of viewports — runs one iteration per viewport. "
                             "Mutually exclusive with --viewport. Example: --viewports mobile,desktop")
    parser.add_argument("--scenario-mode", choices=["locked", "refresh", "hybrid"],
                        default="hybrid",
                        help="How the project's scenario contract (the Scout's project-context.json, "
                             "treated as a ratified evidence-based hypothesis) is reused across iterations: "
                             "locked=pure regression run, reuse the previous contract verbatim; "
                             "refresh=throw the contract away and re-synthesize; "
                             "hybrid=keep the existing contract stable but let the Scout add new candidates on top.")
    parser.add_argument("--scenario-source-iteration", default=None,
                        help="Optional source iteration id/path for locked or hybrid scenario reuse "
                             "(for example: iteration-3 or /abs/path/to/iteration-3)")
    parser.add_argument("--workspace", default=None,
                        help="Workspace directory (default: ./.agents/uxaudit/<target>/)")
    parser.add_argument("--only", default=None,
                        help="Comma-separated category filter (accessibility,ai-slop,core-experience,desirability,usability)")
    parser.add_argument("--skip", default=None,
                        help="Comma-separated category to skip")
    parser.add_argument("--no-capture", action="store_true",
                        help="Skip the capture step (reuse existing target/ directory)")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Don't launch the HTML dashboard at the end")
    parser.add_argument("--reuse-iteration", type=int, default=None,
                        help="Reuse a specific iteration number instead of creating a new one")
    parser.add_argument("--skip-validate", action="store_true",
                        help="Skip the pre-flight check-manifest validator (default: validate first)")
    args = parser.parse_args()

    # Pre-flight: validate every check.json against schemas/check-manifest.schema.json.
    # This catches typos, missing fields, enum violations, missing implementation
    # files, and ID-vs-path mismatches BEFORE we burn time on capture and dispatch.
    # Warnings are non-blocking; errors abort the run loud.
    if not args.skip_validate:
        from validate_checks import validate_all, format_report
        print("🧪 Validating check manifests...")
        report = validate_all()
        if not report.ok:
            print(format_report(report), file=sys.stderr)
            print("\n❌ Manifest validation failed. Fix the errors above or "
                  "run with --skip-validate to bypass (not recommended).",
                  file=sys.stderr)
            return 1
        if report.warnings:
            # Surface warnings but don't block
            print(f"   ⚠️  {len(report.warnings)} manifest warning(s) — see "
                  f"`python {SCRIPTS_DIR / 'validate_checks.py'}` for details")
        else:
            print(f"   ✅ {report.checked} manifest(s) valid")

    if not args.url and not args.electron_app:
        parser.error(
            "either --url or --electron-app is required.\n"
            "  Tip: invoke the /uxaudit skill directly instead of calling this "
            "script — the orchestrator auto-detects the dev server via the "
            "Project Locator (reads package.json scripts, vite/next/astro/nuxt "
            "configs, .env PORT, Procfile) and will offer to start it if it's "
            "not already running."
        )
    if args.url and args.electron_app:
        parser.error("--url and --electron-app are mutually exclusive")
    if args.viewport and args.viewports:
        parser.error("--viewport and --viewports are mutually exclusive")

    # Resolve viewport list. The plural --viewports loops over each, producing
    # one iteration per viewport. The singular --viewport (or default None)
    # produces a single iteration.
    if args.viewports:
        viewport_list = [v.strip() for v in args.viewports.split(",") if v.strip()]
    elif args.viewport:
        viewport_list = [args.viewport]
    else:
        viewport_list = [None]  # let downstream default kick in

    if len(viewport_list) > 1 and args.electron_app:
        parser.error("--viewports cannot be combined with --electron-app (Electron windows have a fixed size)")

    workspace = _resolve_workspace(args.workspace, args.target).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    print(f"📁 Workspace: {workspace}")
    if args.electron_app:
        print(f"⚡ Target: Electron app at {args.electron_app}")
    else:
        print(f"🌐 Target URL: {args.url}")
    if len(viewport_list) > 1:
        print(f"📱 Viewports: {', '.join(viewport_list)} → {len(viewport_list)} iterations")
    elif viewport_list[0]:
        print(f"📱 Viewport: {viewport_list[0]}")

    # Run one iteration per viewport. The reuse_iteration flag only makes
    # sense for a single viewport — when multiple are specified, each gets
    # its own fresh iteration directory.
    iter_dirs: list[Path] = []
    for vp in viewport_list:
        if args.reuse_iteration and len(viewport_list) == 1:
            iteration_num = args.reuse_iteration
        else:
            iteration_num = next_iteration(workspace)
        # Suffix with viewport name when multi-viewport so the iterations
        # are visually distinguishable in the workspace listing
        suffix = f"-{vp}" if len(viewport_list) > 1 and vp else ""
        iter_dir = workspace / f"iteration-{iteration_num}{suffix}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        iter_dirs.append(iter_dir)

        ok = run_one_iteration(args, iter_dir, viewport=vp)
        if not ok:
            return 1

    # Launch dashboard once for the entire run, pointing at all iterations
    if not args.no_dashboard:
        print(f"\n🌐 Launching dashboard...")
        subprocess.Popen([
            sys.executable,
            str(SCRIPTS_DIR / "generate_dashboard.py"),
            *[str(d) for d in iter_dirs],
            "--target", args.target,
        ])
    else:
        print(f"\n💡 Dashboard not launched. Run manually:")
        print(f"   python {SCRIPTS_DIR / 'generate_dashboard.py'} {' '.join(str(d) for d in iter_dirs)} --target {args.target}")

    return 0


def run_one_iteration(args, iter_dir: Path, *, viewport: str | None) -> bool:
    """Run capture + checks + aggregate for a single (iteration_dir, viewport)
    pair. Returns True on success, False if a hard error occurred."""
    print(f"\n🔢 Iteration: {iter_dir.name}")
    if viewport:
        print(f"   viewport: {viewport}")

    # Step 1: Capture target
    target_dir = iter_dir / "target"
    if not args.no_capture or not target_dir.exists():
        print(f"📸 Capturing target → {target_dir}")
        capture_ok = capture_target(args.url, target_dir, viewport=viewport, electron_app=args.electron_app)
        if not capture_ok:
            print("❌ Capture failed. Aborting.", file=sys.stderr)
            return False
    else:
        print(f"♻️  Reusing existing capture at {target_dir}")

    # Per-iteration metadata. This is distinct from target/meta.json
    # (which records capture viewport/kind) and exists so timeline/compare
    # runs can distinguish "same contract, new fix attempt" from
    # "contract regenerated".
    iteration_meta = {
        "target": args.target,
        "url": args.url,
        "electron_app": args.electron_app,
        "viewport": viewport,
        "scenario_mode": args.scenario_mode,
        "scenario_source_iteration": args.scenario_source_iteration,
        "comparable_to_previous": True if args.scenario_mode == "locked" else False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (iter_dir / "meta.json").write_text(json.dumps(iteration_meta, indent=2, ensure_ascii=False))

    # Step 2: Discover checks
    checks = discover_checks(only=args.only, skip=args.skip)
    if not checks:
        print("❌ No checks discovered.", file=sys.stderr)
        return False
    print(f"🔍 Discovered {len(checks)} check(s)")

    # Step 2b: L4 journey capture (when compiled journey scripts exist).
    # The Step 9 Journey Compiler subagent (run by the orchestrator BEFORE
    # this script) writes one JSON per journey into `iter_dir/journey-scripts/`.
    # We fan capture_journey.mjs out in parallel here so the per-journey
    # evidence directories are populated before the L3/L4 Judge subagents
    # are dispatched in Step 11. When journey-scripts/ is missing or empty,
    # this is a no-op and L4 falls back to the legacy "awaiting agent
    # dispatch" placeholder behavior in run_check().
    journey_scripts_dir = iter_dir / "journey-scripts"
    journey_scripts: list[Path] = []
    if journey_scripts_dir.is_dir():
        # Filter out validator sibling files like <id>.validation.json that
        # validate_journey_scripts.mjs writes next to the source journey.
        # Without this filter the L4 capture step fans out twice per journey
        # and creates bogus per-journey check directories ending in
        # ".validation", which then look like legitimate Judge targets
        # downstream. Also skip the underscore-prefixed FTUE script if it
        # is already routed by name to the FTUE check directory (handled
        # separately below).
        journey_scripts = sorted(
            p for p in journey_scripts_dir.glob("*.json")
            if p.is_file() and not p.name.endswith(".validation.json")
        )
    if journey_scripts:
        print(f"🎬 L4 journey capture: {len(journey_scripts)} compiled script(s) → fanning out in parallel")
        run_l4_journey_captures(
            iter_dir=iter_dir,
            journey_scripts=journey_scripts,
            viewport=viewport,
            electron_app=args.electron_app,
        )

    # Step 3: Run each check
    # Names of the per-journey directories that journey capture produced;
    # used to skip the legacy single-placeholder branch in run_check.
    captured_journey_check_ids = {
        d.name for d in (iter_dir / "checks").iterdir()
        if d.is_dir() and d.name.startswith("core-experience-primary-journey-")
    } if (iter_dir / "checks").is_dir() else set()

    # Did the Journey Compiler emit an FTUE script this iteration? If so,
    # run_l4_journey_captures already routed it to the FTUE check dir with
    # a captured result.json — the legacy FTUE placeholder branch below
    # would clobber that, so we detect and skip it here.
    ftue_captured = (iter_dir / "checks" / "usability-first-time-user-experience" / "evidence" / "steps.json").exists()

    print("🏃 Running checks:")
    for check in checks:
        check_id = check["_id_safe"]
        # When the new L4 journey capture pipeline produced per-journey
        # subdirectories for `core-experience/primary-journey`, skip the
        # legacy single placeholder so the completeness gate doesn't see
        # both the per-journey real results AND a stale "awaiting agent
        # dispatch" entry under the un-suffixed dir.
        if check["id"] == "core-experience/primary-journey" and captured_journey_check_ids:
            print(f"  🎬 [L4-journey] core-experience/primary-journey      → {len(captured_journey_check_ids)} per-journey dir(s) (compiled+captured)")
            # Make sure the legacy un-suffixed dir does not exist (it
            # would otherwise be picked up by verify_completeness.py as
            # an awaiting-dispatch L4 entry).
            legacy_dir = iter_dir / "checks" / check_id
            if legacy_dir.exists():
                shutil.rmtree(legacy_dir)
            continue

        # Same thing for FTUE: if the Compiler emitted _ftue.json and the
        # capture phase produced real evidence, don't let the legacy
        # single-placeholder branch clobber it.
        if check["id"] == "usability/first-time-user-experience" and ftue_captured:
            print(f"  🎬 [L4-journey] usability/first-time-user-experience  → cold-start evidence captured")
            continue

        result_dir = iter_dir / "checks" / check_id
        result_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = result_dir / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        result_path = result_dir / "result.json"

        start = time.monotonic()
        method = check["method"]
        run_check(check, target_dir, evidence_dir, result_path, args.url,
                  viewport=viewport, electron_app=args.electron_app)
        duration_ms = int((time.monotonic() - start) * 1000)

        if result_path.exists():
            try:
                status = json.loads(result_path.read_text()).get("result", "?")
            except json.JSONDecodeError:
                status = "?"
        else:
            status = "missing"

        icon = {"pass": "✅", "fail": "❌", "skipped": "⏭", "error": "💥"}.get(status, "❓")
        print(f"  {icon} [{method:>9}] {check['id']:<40} ({duration_ms}ms)")

    # Step 4: Aggregate
    print("📊 Aggregating...")
    agg_cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "aggregate.py"),
        str(iter_dir),
        "--target", args.target,
        "--url", args.url or args.electron_app or "",
    ]
    try:
        agg_proc = subprocess.run(agg_cmd, capture_output=True, text=True, timeout=120)
        agg_rc = agg_proc.returncode
    except subprocess.TimeoutExpired:
        agg_rc = 124
        agg_proc = None
    if agg_rc != 0:
        # Hard failure — promote to ❌ and spill the full stderr so the
        # operator (or orchestrator agent) can act. Silent "aggregate
        # failed" was the worst of both worlds: noisy enough to notice,
        # empty enough to be useless.
        print(f"❌ aggregate.py returned {agg_rc}", file=sys.stderr)
        if agg_proc and (agg_proc.stderr or "").strip():
            for line in agg_proc.stderr.splitlines():
                print(f"    {line}", file=sys.stderr)
        if agg_proc and (agg_proc.stdout or "").strip():
            print("    --- stdout ---", file=sys.stderr)
            for line in agg_proc.stdout.splitlines():
                print(f"    {line}", file=sys.stderr)
    else:
        # Echo aggregate's summary lines on success — they're useful
        # confirmation and already formatted for the terminal.
        if agg_proc and agg_proc.stdout:
            sys.stdout.write(agg_proc.stdout)

    # Per-iteration summary
    benchmark_path = iter_dir / "benchmark.json"
    if benchmark_path.exists():
        try:
            bench = json.loads(benchmark_path.read_text())
            summary = bench.get("summary", {})
            total = summary.get("total", 0)
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            print(f"📈 {passed}/{total} passed, {failed} failed")
        except json.JSONDecodeError:
            pass
    return True


def next_iteration(workspace: Path) -> int:
    nums = []
    for p in workspace.glob("iteration-*"):
        try:
            nums.append(int(p.name.split("-", 1)[1]))
        except ValueError:
            continue
    return (max(nums) if nums else 0) + 1


def discover_checks(only: str | None = None, skip: str | None = None) -> list[dict]:
    """Find all check.json files. Return list of dicts with metadata + _dir + _id_safe."""
    only_set = set(only.split(",")) if only else None
    skip_set = set(skip.split(",")) if skip else set()

    checks = []
    for manifest_path in sorted(CHECKS_DIR.rglob("check.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            print(f"⚠️  Skipping invalid manifest: {manifest_path}", file=sys.stderr)
            continue

        # Category is the first segment of `<category>/<name>` — derived
        # from id, not stored in check.json. Directory layout is the
        # single source of truth.
        check_id = manifest.get("id", "")
        category = check_id.split("/", 1)[0] if "/" in check_id else ""
        if only_set and category not in only_set:
            continue
        if category in skip_set:
            continue

        manifest["_dir"] = manifest_path.parent
        manifest["_id_safe"] = manifest["id"].replace("/", "-")
        checks.append(manifest)

    return checks


def run_check(check: dict, target_dir: Path, evidence_dir: Path, result_path: Path,
              url: str | None, *, viewport: str | None = None,
              electron_app: str | None = None) -> bool:
    """Dispatch a single check by method. Returns True if execution succeeded."""
    check_dir = check["_dir"]
    method = check["method"]

    if method == "L1-script":
        detect_py = check_dir / "detect.py"
        if not detect_py.exists():
            write_skipped(result_path, check, "L1-script: detect.py not found")
            return False
        rc = subprocess.call([
            sys.executable, str(detect_py),
            "--target-dir", str(target_dir),
            "--evidence-dir", str(evidence_dir),
            "--output", str(result_path),
            "--manifest", str(check_dir / "check.json"),
        ])
        return rc == 0

    if method == "L2-script":
        run_mjs = check_dir / "run.mjs"
        if not run_mjs.exists():
            write_skipped(result_path, check, "L2-script: run.mjs not found")
            return False
        node = shutil.which("node")
        if not node:
            write_skipped(result_path, check, "L2-script: node not installed")
            return False
        cmd = [
            node, str(run_mjs),
            "--output", str(result_path),
            "--manifest", str(check_dir / "check.json"),
        ]
        if electron_app:
            cmd += ["--electron-app", electron_app]
        else:
            cmd += ["--url", url or ""]
        if viewport:
            cmd += ["--viewport", viewport]
        rc = subprocess.call(cmd)
        return rc == 0

    if method in ("L3-vision", "L4-journey"):
        # These need agent dispatch — done by the orchestrating Claude agent at
        # /uxaudit invocation time, not by this Python subprocess. Mark as
        # awaiting-agent so the orchestrator can find them.
        write_skipped(
            result_path, check,
            f"{method}: awaiting agent dispatch — see prompt.md, run from /uxaudit orchestrator agent"
        )
        return True

    write_skipped(result_path, check, f"Unknown method: {method}")
    return False


def write_skipped(result_path: Path, check: dict, reason: str) -> None:
    """Write a verdict-shaped skipped result.json. Catalog fields are joined
    in by aggregate.py; we only write the verdict-side data here."""
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "check_id": check.get("id"),
        "result": "skipped",
        "evidence": {"details": reason, "matches": [], "files": []},
    }
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def run_l4_journey_captures(*, iter_dir: Path, journey_scripts: list[Path],
                            viewport: str | None,
                            electron_app: str | None) -> None:
    """Fan capture_journey.mjs out in parallel, one process per compiled journey.

    For each compiled journey script in `journey_scripts`, this:

    1. Computes a stable per-journey check directory under
       `iter_dir/checks/core-experience-primary-journey-<N>-<slug>/` where
       N is the 1-based index in alphabetical order and <slug> is the
       journey script's filename without `.json`.
    2. Pre-writes a placeholder `result.json` (so the L4 Judge dispatch
       in Step 11 can `Read` it before overwriting per the
       `judge-output-format.md` "read-then-write" tool rule), with
       `details` set to a sentinel string the completeness gate ignores
       (`"L4-judge: awaiting evidence-only judge dispatch"`). This is
       distinct from the legacy `"awaiting agent dispatch"` string the
       gate hard-codes against — the new sentinel signals "capture done,
       judge pending", which is the new intermediate state.
    3. Spawns `node capture_journey.mjs <script> <evidence_dir>` for each
       journey, in parallel via concurrent.futures.ThreadPoolExecutor.
       Each subprocess writes screenshots + steps.json + trace.zip into
       `evidence/`.
    4. Waits for all to finish (with a generous per-journey timeout).
    5. Logs per-journey status.

    Failures are non-fatal — a journey that errors mid-capture still
    produces an `evidence/` directory with whatever screenshots got
    captured before the failure, plus the failure state itself, which
    is exactly the evidence the L4 Judge needs to evaluate.
    """
    capture_script = SCRIPTS_DIR / "capture_journey.mjs"
    if not capture_script.exists():
        print(f"❌ capture_journey.mjs missing at {capture_script}", file=sys.stderr)
        return
    node = shutil.which("node")
    if not node:
        print("❌ node not found in PATH; cannot run journey capture", file=sys.stderr)
        return

    checks_root = iter_dir / "checks"
    checks_root.mkdir(parents=True, exist_ok=True)

    # Split the incoming scripts into two buckets:
    #   - `_ftue.json` (if present) routes to the FTUE check directory
    #     with check_id `usability/first-time-user-experience`.
    #   - Everything else is a primary-journey script, numbered 1..N.
    # The underscore prefix is the Compiler's convention for "special"
    # journey scripts that don't participate in the primary-journey
    # numbering. See agents/uxaudit-journey-compiler.md § Mandatory
    # FTUE journey.
    ftue_script = next((p for p in journey_scripts if p.stem == "_ftue"), None)
    regular_scripts = [p for p in journey_scripts if p.stem != "_ftue"]

    # Compute per-journey directories. Index is 1-based and stable
    # (alphabetical sort of the script filenames matches the L4 dispatch
    # convention `core-experience-primary-journey-<N>-<slug>` from the
    # original playbook).
    plans: list[tuple[Path, Path, str]] = []  # (script_path, evidence_dir, dir_name)
    for i, script_path in enumerate(regular_scripts, start=1):
        slug = script_path.stem  # e.g. "create-first-recipe"
        dir_name = f"core-experience-primary-journey-{i}-{slug}"
        check_dir = checks_root / dir_name
        evidence_dir = check_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # Pre-write the placeholder result.json. The L4 Judge in Step 11
        # will Read this and overwrite it with a real verdict.
        placeholder = {
            "check_id": "core-experience/primary-journey",
            "result": "skipped",
            "evidence": {
                "details": "L4-judge: awaiting evidence-only judge dispatch (capture complete)",
                "matches": [],
                "files": [],
            },
        }
        (check_dir / "result.json").write_text(
            json.dumps(placeholder, indent=2, ensure_ascii=False)
        )

        plans.append((script_path, evidence_dir, dir_name))

    # Route the FTUE script, if the Compiler emitted one.
    if ftue_script is not None:
        ftue_check_dir = checks_root / "usability-first-time-user-experience"
        ftue_evidence_dir = ftue_check_dir / "evidence"
        ftue_evidence_dir.mkdir(parents=True, exist_ok=True)
        ftue_placeholder = {
            "check_id": "usability/first-time-user-experience",
            "result": "skipped",
            "evidence": {
                "details": "L4-judge: awaiting evidence-only judge dispatch (FTUE capture complete)",
                "matches": [],
                "files": [],
            },
        }
        (ftue_check_dir / "result.json").write_text(
            json.dumps(ftue_placeholder, indent=2, ensure_ascii=False)
        )
        plans.append((ftue_script, ftue_evidence_dir, "usability-first-time-user-experience"))

    def _run_one(plan: tuple[Path, Path, str]) -> tuple[str, int, str, str, list[str]]:
        """Run a single journey capture subprocess.

        Returns (dir_name, returncode, stderr, stdout, cmd).
        On failure, ALSO writes `<evidence_dir>/capture-error.json` with the
        full diagnostic so the orchestrator / L4 Judge can Read it as an
        actionable artifact instead of scraping it out of terminal log lines.
        """
        script_path, evidence_dir, dir_name = plan
        cmd = [node, str(capture_script), str(script_path), str(evidence_dir)]
        if electron_app:
            cmd += ["--electron-app", electron_app]
        if viewport:
            cmd += ["--viewport", viewport]
        try:
            # Per-journey timeout: 5 minutes is generous for a 10-15 step
            # journey on a local dev server, and bounds total wall time
            # at 5 minutes regardless of how many journeys run.
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            rc = proc.returncode
        except subprocess.TimeoutExpired as e:
            stderr = f"TimeoutExpired after 300s\n{(e.stderr or '')[:2000] if isinstance(e.stderr, (str, bytes)) else ''}"
            stdout = ""
            rc = 124
        except Exception as e:
            stderr = f"python subprocess exception: {type(e).__name__}: {e}"
            stdout = ""
            rc = 1

        if rc != 0:
            error_record = {
                "dir_name": dir_name,
                "script": str(script_path),
                "returncode": rc,
                "cmd": cmd,
                # Keep full stderr — truncation happens at display time, not
                # at capture time. The L4 Judge and any heal-loop consumer
                # needs the middle of the stack, not just the tail.
                "stderr": stderr,
                "stdout": stdout,
                "timeout_s": 300,
                "captured_at_unix": int(time.time()),
            }
            try:
                (evidence_dir / "capture-error.json").write_text(
                    json.dumps(error_record, indent=2, ensure_ascii=False)
                )
            except Exception:
                pass  # best-effort; never hide the primary failure
        return (dir_name, rc, stderr, stdout, cmd)

    start = time.monotonic()
    # Cap parallelism: 4 simultaneous browsers is plenty for typical 5-10
    # journey runs and stays gentle on the dev server. Bigger numbers risk
    # the dev server's HMR or db locking out under contention.
    max_workers = min(4, len(plans)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_run_one, plans))
    elapsed = time.monotonic() - start

    ok_count = 0
    for dir_name, rc, stderr, stdout, cmd in results:
        if rc == 0:
            ok_count += 1
            # On success, show the last useful line from stdout — this is
            # where capture_journey.mjs prints `[journey] cold_start=true`
            # and `[journey] done → <dir> (N step records)`. Cheap signal
            # that tells the operator the run actually did what it claimed.
            tail = stderr.splitlines()[-1] if stderr else ""
            if tail and "[journey]" in tail:
                print(f"  ✅ {dir_name}  {tail}")
            else:
                print(f"  ✅ {dir_name}")
        else:
            # Hard failure — use ❌, not ⚠️. The L4 Judge downstream cannot
            # distinguish a missing capture from a degraded one without
            # this signal, and a warning icon actively misleads operators
            # scanning for real errors.
            print(f"  ❌ {dir_name}  (rc={rc})")
            # Print ALL of stderr on failure, not a 200-char tail. Node
            # stack traces with the selector + DOM context routinely exceed
            # 200 chars, and truncation makes the failure unactionable.
            # Indent each line for visual grouping under the failure header.
            if stderr:
                for line in stderr.splitlines():
                    print(f"      {line}")
            else:
                print(f"      (no stderr — see capture-error.json in the evidence dir)")
            # Point at the persisted error record in case the terminal
            # buffer scrolls past the inline output.
            print(f"      → details: checks/{dir_name}/evidence/capture-error.json")
    print(f"   journey capture complete in {elapsed:.1f}s ({ok_count}/{len(results)} succeeded)")


def capture_target(url: str | None, target_dir: Path, *,
                   viewport: str | None = None,
                   electron_app: str | None = None) -> bool:
    """Run capture.mjs to snapshot the target. Supports web URL OR Electron app.

    Failures are surfaced with the full stderr/stdout AND persisted to
    `<target_dir>/capture-error.json` so the orchestrator has an
    actionable artifact on a busted first-capture run. Warnings (capture
    technically exited 0 but produced no rendered HTML) get the same
    treatment.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    capture_script = SCRIPTS_DIR / "capture.mjs"
    node = shutil.which("node")
    if not node:
        print("❌ node not found in PATH. Install Node.js to use uxaudit.", file=sys.stderr)
        return False

    env = os.environ.copy()

    cmd: list[str] = [node, str(capture_script)]
    if electron_app:
        cmd += ["--electron-app", electron_app, str(target_dir)]
    else:
        cmd += [url or "", str(target_dir)]
    if viewport:
        cmd += ["--viewport", viewport]

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        rc = proc.returncode
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        rc = 124
        stderr = "TimeoutExpired after 120s while running capture.mjs"
        stdout = ""
    except Exception as e:
        rc = 1
        stderr = f"python subprocess exception: {type(e).__name__}: {e}"
        stdout = ""

    def _persist_error(kind: str, extra: str = "") -> None:
        record = {
            "kind": kind,
            "returncode": rc,
            "cmd": cmd,
            "stderr": stderr,
            "stdout": stdout,
            "extra": extra,
            "captured_at_unix": int(time.time()),
        }
        try:
            (target_dir / "capture-error.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

    if rc != 0:
        print(f"❌ capture.mjs returned {rc}", file=sys.stderr)
        # Full stderr on failure, no truncation.
        if stderr:
            for line in stderr.splitlines():
                print(f"    {line}", file=sys.stderr)
        if stdout:
            print("    --- stdout ---", file=sys.stderr)
            for line in stdout.splitlines():
                print(f"    {line}", file=sys.stderr)
        print(f"    → details: {target_dir}/capture-error.json", file=sys.stderr)
        _persist_error("nonzero-exit")
        return False

    rendered = target_dir / "rendered.html"
    if not rendered.exists() or rendered.stat().st_size == 0:
        # capture.mjs exited 0 but produced no rendered.html. This means
        # Playwright launched but the target never responded — most often
        # a dead dev server or a wrong --url. Persist the stderr anyway
        # so the operator can see whatever Playwright complained about.
        print("❌ capture produced no rendered.html", file=sys.stderr)
        if stderr:
            for line in stderr.splitlines():
                print(f"    {line}", file=sys.stderr)
        print(f"    → details: {target_dir}/capture-error.json", file=sys.stderr)
        _persist_error("empty-rendered-html",
                       extra="capture.mjs exited 0 but rendered.html is missing or empty")
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
