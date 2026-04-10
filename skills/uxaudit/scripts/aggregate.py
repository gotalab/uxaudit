#!/usr/bin/env python3
"""
Aggregate uxaudit results into benchmark.json.

Reads <iter-dir>/checks/*/result.json and produces:
- summary (total, passed, failed, skipped, by_category, by_band, by_severity)
- details list (one entry per check with its result + evidence)

Usage:
    python aggregate.py <iter-dir> [--target NAME] [--url URL]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CATALOG_DIR = SKILL_DIR / "checks"


CATALOG_JOIN_FIELDS = (
    "name",
    "band",
    "subtype",
    "method",
    "severity",
    "source",
    "rationale",
    "pass_criteria",
)


def _derive_category(check_id: str) -> str:
    """The category is the first segment of the `<category>/<name>` id.
    It is not stored in check.json — the directory layout is the single
    source of truth, and the id pattern enforces it.
    """
    if not check_id or "/" not in check_id:
        return ""
    return check_id.split("/", 1)[0]


def _load_catalog_manifest(check_id: str) -> dict | None:
    """Load the canonical check.json for a check id. Returns None if the
    catalog entry can't be found or read.
    """
    if not check_id:
        return None
    manifest_path = CATALOG_DIR / check_id / "check.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _join_catalog(result: dict) -> dict:
    """Join catalog metadata from check.json into a result.json record.

    The result writes only verdict-shaped fields (check_id, result,
    evidence, suggestion, optional check-specific extensions). Everything
    else — name, band, subtype, method, severity, source, rationale,
    pass_criteria — comes from the catalog manifest. `category` is
    derived from check_id (the directory layout is the source of truth).

    The result wins on collision so that:
      - Reconciler additions (`result_after_reconciliation`, etc.) are preserved
      - Check-specific top-level fields (e.g. `journey_name` on L4) survive
    """
    check_id = result.get("check_id", "")
    if "category" not in result:
        derived = _derive_category(check_id)
        if derived:
            result["category"] = derived
    manifest = _load_catalog_manifest(check_id)
    if not manifest:
        return result
    for field in CATALOG_JOIN_FIELDS:
        value = manifest.get(field)
        if value is not None and field not in result:
            result[field] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("iter_dir", type=Path)
    parser.add_argument("--target", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--language",
        choices=["en", "ja"],
        default=None,
        help=(
            "Audit language for narrative fields. Pinned at /uxaudit "
            "invocation; aggregator only records it in benchmark.json metadata "
            "so the dashboard can pick the right initial UI language. "
            "Subagent dispatch prompts must already have used the same value. "
            "Strict choices ('en' | 'ja') intentionally reject POSIX locale "
            "strings like 'ja_JP.UTF-8' — those would slip through if the "
            "orchestrator accidentally read the shell's standard $LANG env "
            "var instead of its own $UXAUDIT_LANG."
        ),
    )
    args = parser.parse_args()

    iter_dir: Path = args.iter_dir
    if not iter_dir.is_dir():
        print(f"Not a directory: {iter_dir}", file=sys.stderr)
        return 1

    checks_dir = iter_dir / "checks"
    if not checks_dir.is_dir():
        print(f"No checks/ directory in {iter_dir}", file=sys.stderr)
        return 1

    # Load .uxauditignore from the workspace root (parent of iter_dir).
    # Lines beginning with # are comments; blank lines are skipped.
    # Each line is a check_id (or glob pattern) to exclude from pass-rate
    # calculation. Excluded checks still appear in the dashboard but are
    # marked 'ignored' rather than 'pass'/'fail'.
    workspace_root = iter_dir.parent
    ignored_patterns: list[str] = []
    ignore_file = workspace_root / ".uxauditignore"
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text().splitlines():
                stripped = line.split("#", 1)[0].strip()
                if stripped:
                    ignored_patterns.append(stripped)
        except OSError as e:
            print(f"⚠️  Could not read {ignore_file}: {e}", file=sys.stderr)

    def is_ignored(check_id: str) -> bool:
        if not check_id:
            return False
        import fnmatch
        return any(fnmatch.fnmatch(check_id, p) for p in ignored_patterns)

    results = []
    for result_path in sorted(checks_dir.glob("*/result.json")):
        try:
            data = json.loads(result_path.read_text())
            # result.json is verdict-shaped (check_id + result + evidence
            # + suggestion + optional check-specific extensions). Catalog
            # metadata (name, category, band, subtype, method, severity,
            # source, rationale, pass_criteria) lives in check.json and is
            # joined here so the dashboard receives a single denormalized
            # record. See references/subagents/judge-output-format.md for
            # the rationalization-gate rationale.
            data = _join_catalog(data)
            # Discover evidence files (screenshots) in the same directory
            evidence_dir = result_path.parent / "evidence"
            if evidence_dir.is_dir():
                evidence_files = sorted(
                    str(p.relative_to(iter_dir))
                    for p in evidence_dir.iterdir()
                    if p.is_file()
                )
                data.setdefault("evidence", {})
                data["evidence"]["files"] = evidence_files
            # Apply .uxauditignore — preserve original verdict but flag as
            # ignored so the dashboard can render it differently and the
            # summary excludes it from pass-rate.
            if is_ignored(data.get("check_id", "")):
                data["ignored"] = True
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Skipping {result_path}: {e}", file=sys.stderr)

    summary = build_summary(results)
    if ignored_patterns:
        summary["ignored_patterns"] = ignored_patterns

    # Embed the Step 15 Proposer output (improvement-proposal.json) when
    # present, so generate_dashboard.py can render the "Top fixes" section
    # from a single source — the benchmark.json file. The proposer schema
    # is enforced separately by validate_results.py before we get here, so
    # the aggregator does not re-validate; it only embeds.
    proposal_path = iter_dir / "improvement-proposal.json"
    improvement_proposal = None
    if proposal_path.exists():
        try:
            improvement_proposal = json.loads(proposal_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Skipping {proposal_path}: {e}", file=sys.stderr)

    metadata = {
        "target": args.target,
        "url": args.url,
        "iteration_dir": str(iter_dir.name),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    iteration_meta_path = iter_dir / "meta.json"
    if iteration_meta_path.exists():
        try:
            iteration_meta = json.loads(iteration_meta_path.read_text())
            for key in (
                "scenario_mode",
                "scenario_source_iteration",
                "comparable_to_previous",
            ):
                if key in iteration_meta:
                    metadata[key] = iteration_meta[key]
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Skipping {iteration_meta_path}: {e}", file=sys.stderr)
    if args.language:
        # Pinned at /uxaudit invocation; recorded so the dashboard can pick
        # the matching initial UI language for this iteration. See
        # references/subagents/language-preamble.md for the full contract.
        metadata["language"] = args.language

    # Forward Scout validation warnings (too many jobs, too few journeys,
    # etc.) into benchmark.json as coverage caveats. Playbook 01-discovery.md
    # Step 4 promises these surface as "coverage caveats in the final summary";
    # validate_project_context.py writes the sidecar beside project-context.json
    # and we pick it up here. Absence of the sidecar means either no warnings
    # or an older Scout run — both are fine, we just emit no caveats.
    caveats_path = iter_dir / "project-context.json.warnings.json"
    if caveats_path.exists():
        try:
            caveats_data = json.loads(caveats_path.read_text())
            caveats = caveats_data.get("warnings") or []
            if caveats:
                metadata["coverage_caveats"] = caveats
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Skipping {caveats_path}: {e}", file=sys.stderr)

    benchmark = {
        "metadata": metadata,
        "summary": summary,
        "checks": results,
    }
    if improvement_proposal is not None:
        benchmark["improvement_proposal"] = improvement_proposal

    output_path = args.output or (iter_dir / "benchmark.json")
    output_path.write_text(json.dumps(benchmark, indent=2, ensure_ascii=False))
    print(f"📄 Wrote {output_path}")

    # Pretty-print summary to stdout
    print()
    print(f"  Total:    {summary['total']}")
    print(f"  ✅ Pass:         {summary['passed']}")
    print(f"  ❌ Fail:         {summary['failed']}")
    print(f"  ⏭  Skip:         {summary['skipped']}")
    if summary.get("unverifiable", 0):
        print(f"  ⚠  Unverifiable: {summary['unverifiable']}  (capture incomplete; not counted as fail)")
    if summary.get("error"):
        print(f"  💥 Error:  {summary['error']}")
    print()
    print("  By band:")
    for band, stats in summary.get("by_band", {}).items():
        print(f"    {band}: {stats['passed']}/{stats['total']} pass")
    print()
    print("  By category:")
    for cat, stats in summary.get("by_category", {}).items():
        print(f"    {cat}: {stats['passed']}/{stats['total']} pass")

    return 0


def build_summary(results: list[dict]) -> dict:
    # Ignored checks are included in `total` but excluded from
    # passed/failed/skipped buckets and from pass-rate denominator.
    # They're surfaced as a separate `ignored` count.
    #
    # `unverifiable` is a separate bucket from `fail`. It means the audit
    # pipeline could not gather enough evidence to commit to a verdict
    # (typically: L4 capture broke at a Compiler-selector mismatch). The
    # dashboard surfaces it under "audit integrity" and excludes it from
    # the pass-rate denominator so flaky captures don't punish the app's
    # quality score. Schema enum: pass | fail | skipped | error | unverifiable.
    active = [r for r in results if not r.get("ignored")]
    ignored = [r for r in results if r.get("ignored")]
    total = len(active)
    passed = sum(1 for r in active if r.get("result") == "pass")
    failed = sum(1 for r in active if r.get("result") == "fail")
    skipped = sum(1 for r in active if r.get("result") == "skipped")
    error = sum(1 for r in active if r.get("result") == "error")
    unverifiable = sum(1 for r in active if r.get("result") == "unverifiable")
    ignored_count = len(ignored)

    by_category: dict[str, dict] = {}
    by_band: dict[str, dict] = {}
    by_severity: dict[str, dict] = {}

    for r in active:
        cat = r.get("category", "uncategorized")
        band = logical_band(r)
        sev = r.get("severity", "minor")
        result = r.get("result", "?")
        for bucket, key in [(by_category, cat), (by_band, band), (by_severity, sev)]:
            stats = bucket.setdefault(key, {
                "total": 0, "passed": 0, "failed": 0,
                "skipped": 0, "error": 0, "unverifiable": 0,
            })
            stats["total"] += 1
            if result in ("pass", "failed", "fail", "skipped", "error", "unverifiable"):
                # Normalize 'failed' to 'fail'
                norm = "failed" if result == "fail" else result
                if norm == "pass":
                    stats["passed"] += 1
                elif norm == "failed":
                    stats["failed"] += 1
                elif norm == "skipped":
                    stats["skipped"] += 1
                elif norm == "error":
                    stats["error"] += 1
                elif norm == "unverifiable":
                    stats["unverifiable"] += 1

    # Compute pass_rate where total > 0. Exclude both `skipped` and
    # `unverifiable` from the denominator — neither tells us anything
    # about the app's quality.
    for bucket in (by_category, by_band, by_severity):
        for stats in bucket.values():
            stats.setdefault("unverifiable", 0)
            denom = stats["total"] - stats["skipped"] - stats["unverifiable"]
            stats["pass_rate"] = round(stats["passed"] / denom, 3) if denom > 0 else None

    pass_rate = None
    denom = total - skipped - unverifiable
    if denom > 0:
        pass_rate = round(passed / denom, 3)

    # Audit integrity: how many of the active checks actually produced a
    # committed verdict (pass + fail). If this drops below ~80% the audit
    # is sketchy regardless of whether the committed verdicts look good.
    integrity_denom = total
    integrity_committed = passed + failed
    audit_integrity_rate = (
        round(integrity_committed / integrity_denom, 3)
        if integrity_denom > 0 else None
    )

    # Top failures by severity (major fails first) — only from active set
    severity_order = {"critical": 0, "major": 1, "minor": 2}
    fails = [r for r in active if r.get("result") == "fail"]
    fails.sort(key=lambda r: severity_order.get(r.get("severity", "minor"), 3))
    top_failures = [
        {
            "check_id": r.get("check_id"),
            "name": r.get("name"),
            "severity": r.get("severity"),
            "category": r.get("category"),
            "band": logical_band(r),
            "details": r.get("evidence", {}).get("details", ""),
        }
        for r in fails[:10]
    ]

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "error": error,
        "unverifiable": unverifiable,
        "ignored": ignored_count,
        "pass_rate": pass_rate,
        "audit_integrity_rate": audit_integrity_rate,
        "by_category": by_category,
        "by_band": by_band,
        "by_severity": by_severity,
        "top_failures": top_failures,
    }


def logical_band(result: dict) -> str:
    raw = result.get("band")
    if raw in ("ux", "ui-risk"):
        return raw
    return "ux"


if __name__ == "__main__":
    sys.exit(main())
