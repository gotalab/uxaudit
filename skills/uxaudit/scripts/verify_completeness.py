#!/usr/bin/env python3
"""
Hard gate: verify that an iteration directory has no L3/L4 checks left in
'skipped: requires agent dispatch' state. Run this AFTER the orchestrator
has dispatched all subagent Judges, BEFORE aggregating and rendering the
dashboard. Exits non-zero with a precise list of what's still pending so
the orchestrator can dispatch them.

Usage:
    python verify_completeness.py <iter-dir>

Exit codes:
    0  — all L3/L4 checks have real verdicts (pass / fail / non-default skip)
    1  — at least one L3/L4 check is still 'awaiting agent dispatch'
    2  — input directory invalid

This script is what makes /uxaudit actually autonomous: the orchestrator
cannot proceed to aggregation until every Judge has run.
"""
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CATALOG_DIR = SKILL_DIR / "checks"

DISPATCH_METHODS = {"L3-vision", "L4-journey"}
PENDING_MARKERS = (
    "awaiting agent dispatch",
    "requires agent dispatch",
    # Set by run_all_checks.run_l4_journey_captures after the Step 10 capture
    # phase completes but before the Step 11 evidence-only Judge writes a real
    # verdict. The completeness gate must still flag this as pending so the
    # orchestrator cannot skip Step 11.
    "awaiting evidence-only judge dispatch",
)


def _load_manifest(check_id: str) -> dict:
    """Load the catalog check.json for a check id, or empty dict if missing."""
    if not check_id:
        return {}
    manifest_path = CATALOG_DIR / check_id / "check.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_completeness.py <iter-dir>", file=sys.stderr)
        return 2

    iter_dir = Path(sys.argv[1]).resolve()
    if not iter_dir.is_dir():
        print(f"Not a directory: {iter_dir}", file=sys.stderr)
        return 2

    checks_dir = iter_dir / "checks"
    if not checks_dir.is_dir():
        print(f"No checks/ directory in {iter_dir}", file=sys.stderr)
        return 2

    pending: list[dict] = []
    total_dispatch = 0

    for result_path in sorted(checks_dir.glob("*/result.json")):
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  unreadable {result_path}: {e}", file=sys.stderr)
            continue

        # result.json is verdict-only — `method` and `severity` live in the
        # catalog (check.json) and are joined by aggregate.py later. We
        # need them here to know whether the check is L3/L4 (and to label
        # the pending list), so we look them up directly.
        check_id = data.get("check_id", "")
        manifest = _load_manifest(check_id)
        method = manifest.get("method", "")
        if method not in DISPATCH_METHODS:
            continue

        total_dispatch += 1
        result = data.get("result", "")
        details = (data.get("evidence") or {}).get("details", "") or ""

        if result == "skipped" and any(m in details.lower() for m in PENDING_MARKERS):
            pending.append({
                "check_id": check_id or result_path.parent.name,
                "method": method,
                "severity": manifest.get("severity", ""),
                "result_path": str(result_path.relative_to(iter_dir)),
                "prompt_path": _find_prompt(check_id),
            })

    if not pending:
        print(f"✅ All {total_dispatch} L3/L4 checks have verdicts in {iter_dir.name}")
        return 0

    print(f"❌ {len(pending)} of {total_dispatch} L3/L4 checks still need agent dispatch:")
    print()
    for p in pending:
        print(f"  • {p['check_id']}  [{p['method']}, {p['severity']}]")
        print(f"      result: {p['result_path']}")
        if p['prompt_path']:
            print(f"      prompt: {p['prompt_path']}")
        print()
    print("The orchestrator MUST dispatch these via Agent(subagent_type=…)")
    print("before proceeding past Step 12 (this completeness gate). See")
    print("references/playbook/04-judge-dispatch.md (L3/L4 Judge dispatch).")
    print("Skipping is not optional — incomplete runs are not real audits.")
    return 1


def _find_prompt(check_id: str) -> str | None:
    """Best-effort lookup of the prompt.md path for a given check_id."""
    if not check_id:
        return None
    skill_dir = Path(__file__).resolve().parents[1]
    prompt = skill_dir / "checks" / check_id / "prompt.md"
    if prompt.exists():
        return str(prompt)
    return None


if __name__ == "__main__":
    sys.exit(main())
