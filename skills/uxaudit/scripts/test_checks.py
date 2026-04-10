#!/usr/bin/env python3
"""Regression test runner for uxaudit.

Each check directory MAY contain a `fixtures/` subdirectory holding synthetic
target captures. The runner walks them, runs the check against each, and
asserts the verdict matches the expected one encoded in the fixture name.

Convention
----------
checks/<category>/<name>/fixtures/<expected>[-<label>]/
  rendered.html
  stylesheets.css
  visible-text.txt
  computed-styles.json
  ...

Where <expected> is one of `pass`, `fail`, `skipped`. Optional `-<label>`
suffix lets a check have multiple fixtures of the same expected verdict
(e.g., `fail-purple-gradient`, `fail-stripe-bootstrap`).

The fixture directory is the captured target directory the check would
otherwise see at runtime. You only need to provide the files the check
actually reads (purple-gradient needs stylesheets.css; coming-soon-text
needs visible-text.txt; etc.). Missing files default to empty string.

Why this exists
---------------
The check.json schema validator (validate_checks.py) catches manifest
typos and structural drift, but it CANNOT see ROC drift in the
implementation logic. If you change the threshold in shadcn-signature
from 2 to 5, the validator stays green but the detector silently catches
half what it used to. Per-check fixtures are the only way to surface that
class of regression.

L2 (Playwright), L3 (vision), and L4 (computer-use) checks are skipped
by this runner — they require a live browser / vision LLM / computer-use
session that doesn't fit a stdlib regression test. L2 fixtures could be
served via http.server in a future iteration; L3/L4 need their own
golden-output testing pattern.

Usage
-----
  python scripts/test_checks.py                       # all L1 checks
  python scripts/test_checks.py --check ai-slop/purple-gradient
  python scripts/test_checks.py --category ai-slop
  python scripts/test_checks.py --json
  python scripts/test_checks.py --strict              # missing fixtures = fail

Exit codes
----------
  0 — every fixture matched its expected verdict
  1 — at least one fixture mismatched
  2 — usage / config error
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CHECKS_DIR = SKILL_DIR / "checks"

VALID_EXPECTED = {"pass", "fail", "skipped"}


@dataclass
class FixtureCase:
    check_id: str
    check_dir: Path
    fixture_dir: Path
    expected: str  # "pass" | "fail" | "skipped"
    label: str  # the suffix after "fail-", "" if no suffix


@dataclass
class CaseResult:
    case: FixtureCase
    actual: str
    ok: bool
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.case.check_id,
            "fixture": self.case.fixture_dir.name,
            "expected": self.case.expected,
            "actual": self.actual,
            "ok": self.ok,
            "details": self.details,
        }


@dataclass
class TestReport:
    cases: list[CaseResult] = field(default_factory=list)
    skipped_checks: list[tuple[str, str]] = field(default_factory=list)  # (check_id, reason)

    @property
    def passed(self) -> list[CaseResult]:
        return [c for c in self.cases if c.ok]

    @property
    def failed(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.ok]

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict:
        return {
            "total": len(self.cases),
            "passed": len(self.passed),
            "failed": len(self.failed),
            "skipped_checks": [
                {"check_id": cid, "reason": reason}
                for cid, reason in self.skipped_checks
            ],
            "cases": [c.to_dict() for c in self.cases],
        }


def discover_fixtures(
    *,
    checks_dir: Path = CHECKS_DIR,
    only_check: str | None = None,
    only_category: str | None = None,
) -> list[FixtureCase]:
    """Walk every check directory looking for fixtures/ subdirs.

    Returns a list of FixtureCase. The runner will dispatch them per check.method.
    """
    cases: list[FixtureCase] = []
    for manifest_path in sorted(checks_dir.rglob("check.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            continue

        check_id = manifest.get("id", "")
        # Category is the first segment of `<category>/<name>` — derived
        # from the id, not stored in check.json. The directory layout is
        # the single source of truth.
        category = check_id.split("/", 1)[0] if "/" in check_id else ""
        if only_check and check_id != only_check:
            continue
        if only_category and category != only_category:
            continue

        check_dir = manifest_path.parent
        fixtures_root = check_dir / "fixtures"
        if not fixtures_root.exists():
            continue

        for fixture_dir in sorted(fixtures_root.iterdir()):
            if not fixture_dir.is_dir():
                continue
            name = fixture_dir.name
            # Parse expected verdict from prefix
            expected = None
            label = ""
            for prefix in VALID_EXPECTED:
                if name == prefix:
                    expected = prefix
                    break
                if name.startswith(prefix + "-"):
                    expected = prefix
                    label = name[len(prefix) + 1 :]
                    break
            if expected is None:
                # Skip dirs that don't follow the convention (e.g., __pycache__)
                continue
            cases.append(FixtureCase(
                check_id=check_id,
                check_dir=check_dir,
                fixture_dir=fixture_dir,
                expected=expected,
                label=label,
            ))
    return cases


def run_l1_case(case: FixtureCase) -> CaseResult:
    """Invoke the L1 detect.py against a fixture, parse the result.json,
    and compare to the expected verdict."""
    detect_py = case.check_dir / "detect.py"
    if not detect_py.exists():
        return CaseResult(case, actual="error", ok=False,
                          details=f"detect.py not found at {detect_py}")
    manifest = case.check_dir / "check.json"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        result_path = tmp_path / "result.json"

        proc = subprocess.run(
            [
                sys.executable, str(detect_py),
                "--target-dir", str(case.fixture_dir),
                "--evidence-dir", str(evidence_dir),
                "--output", str(result_path),
                "--manifest", str(manifest),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 and not result_path.exists():
            return CaseResult(
                case, actual="error", ok=False,
                details=f"detect.py exited {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()[:200]}",
            )
        if not result_path.exists():
            return CaseResult(case, actual="error", ok=False,
                              details="detect.py did not write result.json")
        try:
            data = json.loads(result_path.read_text())
        except json.JSONDecodeError as e:
            return CaseResult(case, actual="error", ok=False,
                              details=f"result.json malformed: {e}")
        actual = data.get("result", "<missing>")
        ok = (actual == case.expected)
        details = ""
        if not ok:
            details = (data.get("evidence", {}) or {}).get("details", "")[:200]
        return CaseResult(case, actual=actual, ok=ok, details=details)


def run_all(
    *,
    checks_dir: Path = CHECKS_DIR,
    only_check: str | None = None,
    only_category: str | None = None,
    strict: bool = False,
) -> TestReport:
    report = TestReport()
    cases = discover_fixtures(
        checks_dir=checks_dir,
        only_check=only_check,
        only_category=only_category,
    )

    # Per-check completeness check (only when --strict): every L1 check
    # should have at least one fixture.
    if strict:
        seen_checks = {c.check_id for c in cases}
        for manifest_path in sorted(checks_dir.rglob("check.json")):
            try:
                m = json.loads(manifest_path.read_text())
            except json.JSONDecodeError:
                continue
            if m.get("method") != "L1-script":
                continue
            cid = m.get("id", "")
            if only_check and cid != only_check:
                continue
            cat = cid.split("/", 1)[0] if "/" in cid else ""
            if only_category and cat != only_category:
                continue
            if cid not in seen_checks:
                report.skipped_checks.append(
                    (cid, "no fixtures/ directory (strict mode requires one)")
                )

    for case in cases:
        try:
            manifest = json.loads((case.check_dir / "check.json").read_text())
        except json.JSONDecodeError:
            continue
        method = manifest.get("method")
        if method != "L1-script":
            # L2/L3/L4 fixtures aren't supported by this runner yet
            report.skipped_checks.append(
                (case.check_id, f"method {method} not yet runnable from test_checks.py")
            )
            continue
        report.cases.append(run_l1_case(case))

    return report


def format_report(report: TestReport) -> str:
    lines = []
    total = len(report.cases)
    lines.append(f"Ran {total} fixture(s) — "
                 f"{len(report.passed)} ok, {len(report.failed)} failed")
    if report.skipped_checks:
        lines.append(f"  ({len(report.skipped_checks)} check(s) skipped)")
    lines.append("")

    if report.failed:
        lines.append("FAILED")
        for c in report.failed:
            lines.append(
                f"  ✗ [{c.case.check_id}] fixture={c.case.fixture_dir.name} "
                f"expected={c.case.expected} actual={c.actual}"
            )
            if c.details:
                lines.append(f"      {c.details}")
        lines.append("")

    by_check: dict[str, list[CaseResult]] = {}
    for c in report.passed:
        by_check.setdefault(c.case.check_id, []).append(c)
    if by_check:
        lines.append("PASSED")
        for cid, items in sorted(by_check.items()):
            labels = ", ".join(i.case.fixture_dir.name for i in items)
            lines.append(f"  ✓ [{cid}] {labels}")
        lines.append("")

    if report.skipped_checks:
        lines.append("SKIPPED CHECKS")
        for cid, reason in sorted(set(report.skipped_checks)):
            lines.append(f"  ⏭  [{cid}] {reason}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run check fixtures and verify each detect.py still "
                    "produces the expected verdict.",
    )
    parser.add_argument("--checks-dir", type=Path, default=CHECKS_DIR)
    parser.add_argument("--check", type=str, default=None,
                        help="Run only this check id (e.g., ai-slop/purple-gradient)")
    parser.add_argument("--category", type=str, default=None,
                        help="Run only checks in this category")
    parser.add_argument("--strict", action="store_true",
                        help="Fail if any L1 check is missing a fixtures/ directory")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON report instead of human-readable text")
    args = parser.parse_args()

    report = run_all(
        checks_dir=args.checks_dir,
        only_check=args.check,
        only_category=args.category,
        strict=args.strict,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    if not report.ok:
        return 1
    if args.strict and report.skipped_checks:
        # In strict mode, missing fixtures count as failures
        skipped_l1 = [
            (cid, r) for cid, r in report.skipped_checks
            if "L1" not in r and "method" not in r
        ]
        if skipped_l1:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
