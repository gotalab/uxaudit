#!/usr/bin/env python3
"""Post-flight validator for uxaudit result.json files.

Walks `<iteration-dir>/checks/<check-id>/result.json` and validates each one
against `schemas/check-result.schema.json` plus a small set of cross-file
invariants (check_id ↔ directory match, suggestion required when result == fail).

This is the post-flight twin of validate_checks.py:

  validate_checks.py  — pre-flight, validates check.json (the manifest)
  validate_results.py — post-flight, validates result.json (the verdict)

The post-flight gate exists primarily for L3/L4 Judge dispatches: a vision
or computer-use subagent could write a malformed result.json and the rest
of the pipeline (aggregate, dashboard, library) would silently render
broken data. The validator surfaces the field name and the violation so
the orchestrator can re-dispatch the affected check.

L1/L2 results are produced by check_lib.write_result(), which is
hard-coded against the schema, so they should always validate. Running
the validator on them is still useful as a smoke test for `check_lib`
itself.

Stdlib only — same hand-rolled JSON Schema walker as validate_checks.py.
We deliberately don't pull in `jsonschema`; the schema is small.

Usage
-----
  python scripts/validate_results.py <iteration-dir>
  python scripts/validate_results.py <iteration-dir> --strict   # warnings = errors
  python scripts/validate_results.py <iteration-dir> --json
  python scripts/validate_results.py <iteration-dir> --quiet

Exit codes
----------
  0 — every result.json matched the schema
  1 — at least one result.json violated the schema
  2 — usage / config error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH_DEFAULT = SKILL_DIR / "schemas" / "check-result.schema.json"
PROPOSAL_SCHEMA_PATH_DEFAULT = SKILL_DIR / "schemas" / "improvement-proposal.schema.json"


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    check_id: str
    file: str
    field: str | None
    message: str
    healing_hint: str | None = None   # agent-actionable one-liner
    subagent: str | None = None       # who should heal this
    found: Any = None
    expected: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "check_id": self.check_id,
            "file": self.file,
            "field": self.field,
            "message": self.message,
            "healing_hint": self.healing_hint,
            "subagent": self.subagent,
            "found": self.found,
            "expected": self.expected,
        }


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    checked: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
        }


def _check_type(value: Any, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "null": value is None,
    }.get(expected, False)


def _validate_value(
    value: Any,
    schema: dict[str, Any],
    field_name: str,
    check_id: str,
    file: str,
) -> list[Issue]:
    issues: list[Issue] = []
    expected_type = schema.get("type")
    if expected_type and not _check_type(value, expected_type):
        issues.append(Issue(
            "error", check_id, file, field_name,
            f"Field '{field_name}' must be {expected_type}, "
            f"got {type(value).__name__}",
        ))
        return issues

    if expected_type == "string":
        text: str = value
        if "minLength" in schema and len(text) < schema["minLength"]:
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' is too short ({len(text)} chars, "
                f"min {schema['minLength']})",
            ))
        if "maxLength" in schema and len(text) > schema["maxLength"]:
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' is too long ({len(text)} chars, "
                f"max {schema['maxLength']})",
            ))
        if "enum" in schema and text not in schema["enum"]:
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' value '{text}' is not in enum "
                f"{schema['enum']}",
            ))
        if "pattern" in schema and not re.search(schema["pattern"], text):
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' value '{text}' does not match pattern "
                f"{schema['pattern']!r}",
            ))

    if expected_type == "number" or expected_type == "integer":
        n = value
        if "minimum" in schema and n < schema["minimum"]:
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' is below minimum "
                f"({n} < {schema['minimum']})",
            ))
        if "maximum" in schema and n > schema["maximum"]:
            issues.append(Issue(
                "error", check_id, file, field_name,
                f"Field '{field_name}' is above maximum "
                f"({n} > {schema['maximum']})",
            ))

    if expected_type == "object":
        if not isinstance(value, dict):
            return issues
        for req in schema.get("required", []):
            if req not in value:
                issues.append(Issue(
                    "error", check_id, file, f"{field_name}.{req}",
                    f"Required nested field '{field_name}.{req}' is missing",
                ))
        for key, subschema in (schema.get("properties") or {}).items():
            if key in value:
                issues.extend(_validate_value(
                    value[key], subschema, f"{field_name}.{key}", check_id, file,
                ))

    if expected_type == "array":
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(value):
                issues.extend(_validate_value(
                    item, items_schema, f"{field_name}[{idx}]", check_id, file,
                ))

    return issues


def validate_against_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    *,
    check_id: str,
    file: str,
) -> list[Issue]:
    issues: list[Issue] = []

    if not isinstance(data, dict):
        issues.append(Issue("error", check_id, file, None,
                            f"Expected an object, got {type(data).__name__}"))
        return issues

    # Required top-level
    for req in schema.get("required", []):
        if req not in data:
            issues.append(Issue("error", check_id, file, req,
                                f"Required field '{req}' is missing"))

    # Per-field
    for key, subschema in (schema.get("properties") or {}).items():
        if key not in data:
            continue
        issues.extend(_validate_value(data[key], subschema, key, check_id, file))

    # Conditional (allOf with if/then) — narrow support for our one case
    for clause in schema.get("allOf", []):
        if "if" in clause and "then" in clause:
            cond_props = (clause["if"].get("properties") or {})
            condition_met = True
            for k, v in cond_props.items():
                if "const" in v and data.get(k) != v["const"]:
                    condition_met = False
                    break
            if condition_met:
                then_clause = clause["then"]
                for req in then_clause.get("required", []):
                    if req not in data or not data[req]:
                        issues.append(Issue(
                            "error", check_id, file, req,
                            f"Field '{req}' is required when "
                            f"{cond_props} (got: missing or empty)",
                        ))
                for key, sub in (then_clause.get("properties") or {}).items():
                    if key in data:
                        issues.extend(_validate_value(
                            data[key], sub, key, check_id, file,
                        ))

    return issues


def validate_iteration(
    iteration_dir: Path,
    schema_path: Path = SCHEMA_PATH_DEFAULT,
    proposal_schema_path: Path = PROPOSAL_SCHEMA_PATH_DEFAULT,
) -> Report:
    """Walk every result.json under <iteration_dir>/checks/ and validate it.

    Also validates <iteration_dir>/improvement-proposal.json if present
    (Step 15 Proposer output).
    """
    report = Report()

    if not schema_path.exists():
        report.issues.append(Issue(
            "error", "<schema>", str(schema_path), None,
            f"Schema file not found: {schema_path}",
        ))
        return report

    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as e:
        report.issues.append(Issue(
            "error", "<schema>", str(schema_path), None,
            f"Could not parse schema: {e}",
        ))
        return report

    checks_dir = iteration_dir / "checks"
    if not checks_dir.exists():
        report.issues.append(Issue(
            "error", "<iteration>", str(iteration_dir), None,
            f"No checks/ directory under {iteration_dir}",
        ))
        return report

    for result_path in sorted(checks_dir.rglob("result.json")):
        report.checked += 1
        try:
            data = json.loads(result_path.read_text())
        except json.JSONDecodeError as e:
            report.issues.append(Issue(
                "error", "<unparseable>", str(result_path), None,
                f"Invalid JSON: {e}",
            ))
            continue

        check_id = data.get("check_id", "<unknown>")
        report.issues.extend(validate_against_schema(
            data, schema, check_id=check_id, file=str(result_path),
        ))

        # Imperative invariant: when journey_evaluation is present, the
        # top-level result MUST be the rollup of the four sub-verdicts under
        # the rules below. The JSON Schema constraint encodes rule A
        # (any-fail → top-fail) with allOf+anyOf, but the hand-rolled walker
        # only handles `if/then` with top-level const, so both rules get
        # enforced here. See `references/concepts/discovery-and-scope.md`
        # Part 0 and the L4 Judge brief in `references/subagents/judge-
        # output-format.md` for the contract.
        #
        # Rule A (existing): if any sub.verdict == "fail", top result MUST
        # be "fail". A failing axis is a real product issue and must be
        # surfaced as such — the dashboard renders these as critical fails.
        #
        # Rule B (new): if no sub.verdict == "fail" AND any sub.verdict ==
        # "unverifiable", top result MUST be "unverifiable" (NOT "pass").
        # The audit pipeline didn't gather enough evidence to commit. Top-
        # level "pass" would lie about what we actually verified. Top-level
        # "fail" would punish the app for our capture problem. "unverifiable"
        # is the honest answer — the dashboard counts these in a separate
        # bucket and excludes them from pass-rate denominators.
        je = data.get("journey_evaluation")
        if isinstance(je, dict):
            sub_axes = ("value_delivery", "task_completion", "operating_cost", "feedback_quality")
            failing_axes = []
            unverifiable_axes = []
            for axis in sub_axes:
                axis_obj = je.get(axis)
                if not isinstance(axis_obj, dict):
                    continue
                v = axis_obj.get("verdict")
                if v == "fail":
                    failing_axes.append(axis)
                elif v == "unverifiable":
                    unverifiable_axes.append(axis)
            top_result = data.get("result")
            if failing_axes and top_result != "fail":
                report.issues.append(Issue(
                    "error", check_id, str(result_path), "result",
                    f"journey_evaluation rollup violation (Rule A): "
                    f"sub-verdict(s) {', '.join(failing_axes)} are 'fail' "
                    f"but top-level result is '{top_result}'. Any failing "
                    f"axis must force the top-level verdict to 'fail'.",
                ))
            elif unverifiable_axes and top_result == "pass":
                # No failing axis, but at least one is unverifiable. Cannot
                # claim a passing journey because we didn't actually verify
                # the unverifiable axes. Top must be "unverifiable" (or
                # "fail" if there's a separate reason).
                report.issues.append(Issue(
                    "error", check_id, str(result_path), "result",
                    f"journey_evaluation rollup violation (Rule B): "
                    f"sub-verdict(s) {', '.join(unverifiable_axes)} are "
                    f"'unverifiable' and no axis is 'fail', but top-level "
                    f"result is 'pass'. The audit pipeline did not gather "
                    f"enough evidence to commit to pass — set top-level "
                    f"result to 'unverifiable' instead.",
                ))

        # Cross-file invariant: check_id should match the directory name.
        # The directory uses '-' as separator instead of '/' for filesystem
        # safety. Compare in the id→dir direction (slash → dash) because the
        # other direction is ambiguous when category or name contain hyphens.
        #
        # Per-journey instances of core-experience/primary-journey may use a
        # `-<N>-<slug>` suffix on the directory name (documented in
        # references/playbook/03-journey-capture.md) so the dashboard can
        # show one strip per discovered journey while reusing the same
        # check_id. Accept any directory whose name STARTS with the expected
        # base, separated by a hyphen + integer.
        rel = result_path.relative_to(checks_dir)
        if len(rel.parts) >= 2 and check_id != "<unknown>":
            expected_dir = check_id.replace("/", "-")
            actual_dir = rel.parts[0]
            if expected_dir != actual_dir:
                # Allow per-instance suffix: <expected>-<N>-<slug>
                suffix_ok = False
                if actual_dir.startswith(expected_dir + "-"):
                    rest = actual_dir[len(expected_dir) + 1:]
                    head = rest.split("-", 1)[0]
                    if head.isdigit():
                        suffix_ok = True
                if not suffix_ok:
                    report.issues.append(Issue(
                        "warning", check_id, str(result_path), "check_id",
                        f"check_id '{check_id}' does not match its directory "
                        f"name '{actual_dir}' (expected '{expected_dir}')",
                    ))

    # Step 15 — Proposer output (improvement-proposal.json) is optional but
    # validated when present. The schema lives at the iteration root, not
    # under checks/, so we walk it separately.
    proposal_path = iteration_dir / "improvement-proposal.json"
    if proposal_path.exists():
        report.checked += 1
        if not proposal_schema_path.exists():
            report.issues.append(Issue(
                "warning", "<proposer>", str(proposal_path), None,
                f"improvement-proposal.json found but proposal schema is "
                f"missing at {proposal_schema_path}; skipping validation.",
            ))
        else:
            try:
                proposal_schema = json.loads(proposal_schema_path.read_text())
            except json.JSONDecodeError as e:
                report.issues.append(Issue(
                    "error", "<proposer>", str(proposal_schema_path), None,
                    f"Could not parse proposal schema: {e}",
                ))
                return report
            try:
                proposal_data = json.loads(proposal_path.read_text())
            except json.JSONDecodeError as e:
                report.issues.append(Issue(
                    "error", "<proposer>", str(proposal_path), None,
                    f"Invalid JSON in improvement-proposal.json: {e}",
                ))
                return report
            report.issues.extend(validate_against_schema(
                proposal_data, proposal_schema,
                check_id="<proposer>", file=str(proposal_path),
            ))

            # Cross-file invariant: every check_id referenced in the proposal
            # must actually exist in the iteration's checks/ directory.
            # The Proposer can reference fails-as-(partial) so we strip the
            # suffix before comparing.
            existing_ids: set[str] = set()
            for r in checks_dir.rglob("result.json"):
                try:
                    rd = json.loads(r.read_text())
                    if "check_id" in rd:
                        existing_ids.add(rd["check_id"])
                except json.JSONDecodeError:
                    continue

            referenced: list[tuple[str, str]] = []  # (where, id)
            for rc in proposal_data.get("root_causes") or []:
                for cid in rc.get("explains") or []:
                    referenced.append(("root_causes.explains", cid))
            for prop in proposal_data.get("proposals") or []:
                for cid in prop.get("addresses_fails") or []:
                    bare = cid.replace(" (partial)", "").strip()
                    referenced.append(("proposals.addresses_fails", bare))
            for d in proposal_data.get("deferred") or []:
                if isinstance(d, dict) and "check_id" in d:
                    referenced.append(("deferred.check_id", d["check_id"]))

            for source, cid in referenced:
                if cid not in existing_ids:
                    report.issues.append(Issue(
                        "warning", "<proposer>", str(proposal_path), source,
                        f"Proposer references check_id '{cid}' which does "
                        f"not exist in this iteration's checks/. Either the "
                        f"check was deleted or the Proposer hallucinated it.",
                    ))

    annotate_report(report)
    return report


# --------------------------------------------------------------------------
# Healing hints — the post-dispatch companion to validate_project_context's
# annotator. Every issue gets an agent-actionable one-liner plus a
# `subagent` routing label so the orchestrator's re-dispatch step knows
# which role to wake up.
# --------------------------------------------------------------------------


def _subagent_for(check_id: str, file_path: str) -> str:
    """Route an issue to the subagent that should heal it."""
    if check_id == "<proposer>":
        return "proposer"
    if check_id in {"<schema>", "<iteration>", "<unparseable>"}:
        # These are fatal environmental issues — only the orchestrator can fix.
        return "orchestrator"
    # Everything else came from a per-check result.json — route by check_id.
    return f"judge:{check_id}"


def _annotate(issue: Issue) -> None:
    """Attach healing_hint + subagent in-place. Idempotent."""
    issue.subagent = issue.subagent or _subagent_for(issue.check_id, issue.file)

    field = issue.field or ""
    msg = issue.message or ""

    # Rule A rollup violation (L4 journey)
    if "Rule A" in msg:
        issue.expected = "top-level result == 'fail'"
        issue.healing_hint = (
            "Your journey_evaluation has at least one sub-verdict set to 'fail' "
            "but the top-level result is not 'fail'. Change the top-level `result` "
            "to 'fail' (rollup rule A). Keep the sub-verdicts as-is unless you "
            "actually disagree with one — in which case fix THAT axis's verdict "
            "and explain in its `evidence` string. Either direction is fine, but "
            "the rollup must be consistent."
        )
        return

    # Rule B rollup violation
    if "Rule B" in msg:
        issue.expected = "top-level result == 'unverifiable'"
        issue.healing_hint = (
            "Your journey_evaluation has unverifiable sub-verdicts and no failing "
            "axis, but the top-level result is 'pass'. A pass requires complete "
            "evidence on every axis. Change the top-level `result` to 'unverifiable'. "
            "If you actually DO have evidence for the unverifiable axes, fix those "
            "sub-verdicts instead."
        )
        return

    # check_id does not match directory name
    if "does not match its directory name" in msg:
        issue.expected = "check_id matches directory"
        issue.healing_hint = (
            "The `check_id` field in your result.json must be the exact string the "
            "orchestrator gave you in the prompt (category/name form), NOT the "
            "directory name (category-name form). Per-journey L4 checks all share "
            "the same check_id 'core-experience/primary-journey' — the directory "
            "suffix like '-1-browse-and-discover' is a dashboard-only affordance, "
            "not part of the check_id."
        )
        return

    # Proposer referenced a check_id that doesn't exist
    if "Proposer references check_id" in msg:
        issue.expected = "canonical check_id from result.json"
        issue.healing_hint = (
            "You referenced a check_id that doesn't exist. Read the `check_id` "
            "FIELD INSIDE each result.json (not the directory basename). L4 "
            "journey checks all use 'core-experience/primary-journey' — to "
            "distinguish journeys, reference them in narrative fields "
            "(concrete_steps, why_first) or attach the journey_name. Never "
            "synthesize a slug like 'core-experience/primary-journey-1-foo'."
        )
        return

    # Required field missing
    if "is required when" in msg:
        issue.expected = "required field present"
        issue.healing_hint = (
            "A conditional required field is missing. This is most often "
            "`suggestion` being empty when `result == 'fail'`. Add a concrete, "
            "actionable suggestion (name the specific change, not 'improve X')."
        )
        return

    if msg.startswith("Required field") and "is missing" in msg:
        issue.expected = "field present"
        issue.healing_hint = (
            "Your output is missing a required top-level field. Read the schema "
            "at schemas/check-result.schema.json (for per-check result.json) or "
            "schemas/improvement-proposal.schema.json (for improvement-proposal.json), "
            "add the missing field, and re-Write. Do not rewrite the whole file."
        )
        return

    if "Required nested field" in msg:
        issue.expected = "nested field present"
        issue.healing_hint = (
            "A required nested field is missing. This is most often inside "
            "`evidence` (which needs `details`) or inside a `journey_evaluation` "
            "axis (which needs `verdict` and `evidence`). Patch only the missing "
            "nested field; leave the rest alone."
        )
        return

    # Enum violation
    if "is not in enum" in msg:
        issue.expected = "enum-valid value"
        # Try to extract the allowed set from the message
        import re as _re
        m = _re.search(r"enum \[(.+?)\]", msg)
        allowed = m.group(1) if m else "the allowed values listed in the message"
        issue.healing_hint = (
            f"This field must be one of: {allowed}. Machine enums are never "
            f"translated under --lang ja; keep the canonical English token."
        )
        m2 = _re.search(r"value '([^']*)'", msg)
        if m2:
            issue.found = m2.group(1)
        return

    # Pattern mismatch (e.g., check_id pattern)
    if "does not match pattern" in msg:
        issue.expected = "value matching schema pattern"
        issue.healing_hint = (
            "The value does not match the schema regex. For `check_id`, it must be "
            "lowercase-kebab-case segments joined by '/' (e.g. 'ai-slop/purple-gradient')."
        )
        return

    # Invalid JSON
    if msg.startswith("Invalid JSON"):
        issue.expected = "valid JSON document"
        issue.healing_hint = (
            "Your result.json is not valid JSON (likely unterminated string, "
            "trailing comma, or raw newline inside a string). Re-Write the file "
            "from scratch following the contract in references/subagents/"
            "judge-output-format.md. Pay attention to escaping in "
            "evidence.details — use \\n for line breaks inside strings."
        )
        return

    # Type mismatch
    if "must be " in msg and ", got " in msg:
        issue.expected = "correct JSON type"
        issue.healing_hint = (
            "The value has the wrong JSON type. Common mistakes: writing a step "
            "number as a string ('5' instead of 5), wrapping a scalar in an array, "
            "or confusing array vs object syntax."
        )
        return

    # String length
    if "is too short" in msg or "is too long" in msg:
        issue.expected = "string within the declared length bounds"
        issue.healing_hint = (
            "The string length is outside the allowed bounds. For narrative "
            "fields, either expand (at least 1 concrete observation) or trim "
            "(remove filler and restate the core point)."
        )
        return

    # Number bounds
    if "is below minimum" in msg or "is above maximum" in msg:
        issue.expected = "number within bounds"
        issue.healing_hint = (
            "A numeric field is out of range. Counts like `actual_steps` must be "
            "non-negative integers; ranks must be positive. Do not wrap numbers in "
            "strings — the schema rejects string-wrapped integers."
        )
        return

    # Proposal schema missing
    if "proposal schema is" in msg and "missing" in msg:
        issue.expected = "proposal schema file present"
        issue.healing_hint = (
            "The improvement-proposal schema file is missing from the skill bundle. "
            "This is an environmental error — the orchestrator needs to restore "
            "schemas/improvement-proposal.schema.json. Cannot be healed by a subagent."
        )
        return

    # Default fallback
    issue.healing_hint = (
        "The validator rejected this field. Re-read the schema at "
        "schemas/check-result.schema.json (result.json) or "
        "schemas/improvement-proposal.schema.json (improvement-proposal.json), "
        "patch only this field, and re-Write."
    )


def annotate_report(report: Report) -> None:
    for issue in report.issues:
        _annotate(issue)


def format_report(report: Report) -> str:
    lines = []
    err = report.errors
    warn = report.warnings
    lines.append(f"Checked {report.checked} result(s)")
    lines.append(f"  errors:   {len(err)}")
    lines.append(f"  warnings: {len(warn)}")
    lines.append("")

    if err:
        lines.append("ERRORS")
        for i in err:
            lines.append(f"  ✗ [{i.check_id}] {i.field or '-'}")
            lines.append(f"    {i.message}")
            if i.healing_hint:
                lines.append(f"    → {i.healing_hint}")
            lines.append(f"    in {i.file}")
        lines.append("")

    if warn:
        lines.append("WARNINGS")
        for i in warn:
            lines.append(f"  ! [{i.check_id}] {i.field or '-'}")
            lines.append(f"    {i.message}")
            if i.healing_hint:
                lines.append(f"    → {i.healing_hint}")
        lines.append("")

    if not err and not warn:
        lines.append("All result.json files conform to the schema.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate uxaudit result.json files against the schema.",
    )
    parser.add_argument("iteration_dir", type=Path,
                        help="Path to the iteration directory "
                             "(workspace/iteration-N)")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH_DEFAULT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors")
    args = parser.parse_args()

    if not args.iteration_dir.exists():
        print(f"❌ Iteration directory not found: {args.iteration_dir}",
              file=sys.stderr)
        return 2

    report = validate_iteration(args.iteration_dir, args.schema)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif not args.quiet or not report.ok:
        print(format_report(report))

    if not report.ok:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
