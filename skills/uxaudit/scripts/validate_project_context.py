#!/usr/bin/env python3
"""Validate Scout-produced project-context.json files.

This is the missing twin of validate_checks.py / validate_results.py.

It validates:
  - shape against schemas/project-context.schema.json
  - structural invariants the schema can't express:
      * unique journey ids / job ids
      * journey links point at real journeys
      * journey job_ids point at real jobs
      * journey chains only reference known journeys
  - soft quality signals:
      * suspiciously low journey count for the inferred category
      * high-priority jobs not covered by any journey
      * overgrown job lists
      * empty evidence_basis on a job

Usage:
  python validate_project_context.py path/to/project-context.json
  python validate_project_context.py path/to/project-context.json --json
  python validate_project_context.py path/to/project-context.json --strict
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
SCHEMA_PATH_DEFAULT = SKILL_DIR / "schemas" / "project-context.schema.json"


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    file: str
    field: str | None
    message: str
    healing_hint: str | None = None   # agent-actionable one-liner
    subagent: str | None = None       # who should heal this ("scout", "judge:<id>", "proposer", ...)
    found: Any = None                 # the rejected value (if applicable)
    expected: str | None = None       # short description of what was expected

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
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


def _validate_value(value: Any, schema: dict[str, Any], field_name: str, file: str) -> list[Issue]:
    issues: list[Issue] = []

    allowed_types: list[str]
    expected = schema.get("type")
    if isinstance(expected, list):
        allowed_types = expected
    elif isinstance(expected, str):
        allowed_types = [expected]
    else:
        allowed_types = []

    if allowed_types and not any(_check_type(value, t) for t in allowed_types):
        issues.append(Issue(
            "error",
            file,
            field_name,
            f"Field '{field_name}' must be one of {allowed_types}, got {type(value).__name__}",
        ))
        return issues

    expected_type = next((t for t in allowed_types if _check_type(value, t)), None)

    if expected_type == "string":
        text = value
        if "minLength" in schema and len(text) < schema["minLength"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' is too short ({len(text)} chars, min {schema['minLength']})"))
        if "maxLength" in schema and len(text) > schema["maxLength"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' is too long ({len(text)} chars, max {schema['maxLength']})"))
        if "enum" in schema and text not in schema["enum"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' value '{text}' is not in enum {schema['enum']}"))
        if "pattern" in schema and not re.search(schema["pattern"], text):
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' value '{text}' does not match pattern {schema['pattern']!r}"))

    if expected_type in {"number", "integer"}:
        n = value
        if "minimum" in schema and n < schema["minimum"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' is below minimum ({n} < {schema['minimum']})"))
        if "maximum" in schema and n > schema["maximum"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' is above maximum ({n} > {schema['maximum']})"))

    if expected_type == "object":
        if not isinstance(value, dict):
            return issues
        for req in schema.get("required", []):
            if req not in value:
                issues.append(Issue("error", file, f"{field_name}.{req}",
                                    f"Required nested field '{field_name}.{req}' is missing"))
        if schema.get("additionalProperties") is False:
            allowed = set((schema.get("properties") or {}).keys())
            for key in value.keys():
                if key not in allowed:
                    issues.append(Issue("error", file, f"{field_name}.{key}",
                                        f"Unknown field '{field_name}.{key}' (additionalProperties: false)"))
        for key, subschema in (schema.get("properties") or {}).items():
            if key in value:
                issues.extend(_validate_value(value[key], subschema, f"{field_name}.{key}", file))

    if expected_type == "array":
        if not isinstance(value, list):
            return issues
        if "minItems" in schema and len(value) < schema["minItems"]:
            issues.append(Issue("error", file, field_name,
                                f"Field '{field_name}' has too few items ({len(value)}, min {schema['minItems']})"))
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(value):
                issues.extend(_validate_value(item, items_schema, f"{field_name}[{idx}]", file))

    return issues


def validate_against_schema(data: dict[str, Any], schema: dict[str, Any], *, file: str) -> list[Issue]:
    issues: list[Issue] = []

    if not isinstance(data, dict):
        issues.append(Issue("error", file, None, f"Expected an object, got {type(data).__name__}"))
        return issues

    for req in schema.get("required", []):
        if req not in data:
            issues.append(Issue("error", file, req, f"Required field '{req}' is missing"))

    if schema.get("additionalProperties") is False:
        allowed = set((schema.get("properties") or {}).keys())
        for key in data.keys():
            if key not in allowed:
                issues.append(Issue("error", file, key, f"Unknown field '{key}' (additionalProperties: false)"))

    for key, subschema in (schema.get("properties") or {}).items():
        if key in data:
            issues.extend(_validate_value(data[key], subschema, key, file))

    return issues


def _category_floor(category: str, purpose: str, audience: str) -> tuple[int, str]:
    hay = " ".join([category, purpose, audience]).lower()
    if any(word in hay for word in ("marketplace", "platform", "seller", "buyer", "two-sided")):
        return 8, "marketplace/platform"
    if any(word in hay for word in ("saas", "productivity", "team", "admin", "workspace", "collaboration")):
        return 7, "team-saas"
    if any(word in hay for word in ("landing", "marketing", "brand site", "showcase")):
        return 3, "marketing"
    if any(word in hay for word in ("crud", "utility", "todo", "notes", "expense", "tracker")):
        return 5, "crud"
    return 5, "default"


def validate_structural(data: dict[str, Any], *, file: str) -> list[Issue]:
    issues: list[Issue] = []

    journeys = data.get("primary_journeys") or []
    jobs = (data.get("experience_model") or {}).get("jobs") or []
    chains = data.get("journey_chains") or []

    journey_ids: list[str] = [j.get("id", "") for j in journeys if isinstance(j, dict)]
    job_ids: list[str] = [j.get("id", "") for j in jobs if isinstance(j, dict)]
    journey_set = {j for j in journey_ids if j}
    job_set = {j for j in job_ids if j}

    seen: set[str] = set()
    for jid in journey_ids:
        if not jid:
            continue
        if jid in seen:
            issues.append(Issue("error", file, "primary_journeys.id",
                                f"Duplicate journey id '{jid}'"))
        seen.add(jid)

    seen.clear()
    for job_id in job_ids:
        if not job_id:
            continue
        if job_id in seen:
            issues.append(Issue("error", file, "experience_model.jobs.id",
                                f"Duplicate job id '{job_id}'"))
        seen.add(job_id)

    for idx, journey in enumerate(journeys):
        if not isinstance(journey, dict):
            continue
        for edge in ("next_journey", "previous_journey"):
            ref = journey.get(edge)
            if ref and ref not in journey_set:
                issues.append(Issue("error", file, f"primary_journeys[{idx}].{edge}",
                                    f"Journey '{journey.get('id', '<unknown>')}' references unknown journey id '{ref}'"))
        for job_id in journey.get("job_ids") or []:
            if job_id not in job_set:
                issues.append(Issue("error", file, f"primary_journeys[{idx}].job_ids",
                                    f"Journey '{journey.get('id', '<unknown>')}' references unknown job id '{job_id}'"))

    for idx, chain in enumerate(chains):
        if not isinstance(chain, list):
            continue
        for journey_id in chain:
            if journey_id not in journey_set:
                issues.append(Issue("error", file, f"journey_chains[{idx}]",
                                    f"Journey chain references unknown journey id '{journey_id}'"))

    if not journeys:
        issues.append(Issue("warning", file, "primary_journeys",
                            "No primary_journeys found. This weakens every downstream journey-based evaluation."))
    if not jobs:
        issues.append(Issue("warning", file, "experience_model.jobs",
                            "No experience_model.jobs found. Project-shaped UX evaluation will stay generic."))

    purpose = data.get("purpose", "")
    audience = data.get("target_audience", "")
    category = data.get("category", "unknown")
    floor, floor_label = _category_floor(category, purpose, audience)
    if len(journeys) < floor:
        issues.append(Issue(
            "warning",
            file,
            "primary_journeys",
            f"Only {len(journeys)} journey(s) synthesized; category floor for {floor_label} is about {floor}. "
            "This is fine if discovery_notes / experience_model.open_questions explain the missing evidence — "
            "an honest small hypothesis is more useful than a padded one. Re-dispatch the Scout only if the "
            "gap is undocumented."
        ))

    if len(jobs) > 4:
        issues.append(Issue(
            "warning",
            file,
            "experience_model.jobs",
            f"{len(jobs)} jobs found. This is probably too many for a stable audit frame; prefer 1–3, rarely 4."
        ))

    journey_job_refs: dict[str, int] = {}
    for journey in journeys:
        if not isinstance(journey, dict):
            continue
        for job_id in journey.get("job_ids") or []:
            journey_job_refs[job_id] = journey_job_refs.get(job_id, 0) + 1

    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        if job.get("priority") == "high" and journey_job_refs.get(job.get("id", ""), 0) == 0:
            issues.append(Issue(
                "warning",
                file,
                f"experience_model.jobs[{idx}]",
                f"High-priority job '{job.get('id', '<unknown>')}' is not referenced by any journey.job_ids."
            ))
        if not (job.get("evidence_basis") or []):
            issues.append(Issue(
                "warning",
                file,
                f"experience_model.jobs[{idx}].evidence_basis",
                f"Job '{job.get('id', '<unknown>')}' has empty evidence_basis. The source of this contract is unclear."
            ))

    return issues


# --------------------------------------------------------------------------
# Healing hints — every issue gets annotated with an agent-actionable
# one-liner + the subagent who should patch it. Project-context errors
# always route to the Scout.
# --------------------------------------------------------------------------

_ENUM_FIELDS_MACHINE = {
    # suffixes / exact segments that are machine enums and must NEVER be
    # translated under --lang ja — the Scout occasionally rewrites these
    # into narrative Japanese which breaks the schema.
    "context": ("cold-start | returning | power-user",
                "Journey context is a machine enum. Do not translate; pick one of cold-start, returning, power-user based on the journey semantics."),
    "contexts": ("cold-start | returning | power-user",
                 "experience_model.jobs[*].contexts is a machine enum array. Do not translate; each item must be cold-start, returning, or power-user."),
    "priority": ("high | medium | low",
                 "Job priority is a machine enum. Do not translate; pick high, medium, or low."),
    "confidence": ("high | medium | low",
                   "Confidence is a machine enum. Do not translate; pick high, medium, or low."),
    "kind": ("e2e | scenario-doc | route | readme | category-baseline | jtbd | external-research",
             "evidence_basis[*].kind is a machine enum. Do not translate; pick one of the declared source kinds."),
    "primary_viewport": ("mobile-sm | mobile | tablet | tablet-pro | desktop | desktop-lg",
                         "primary_viewport is a machine enum of viewport preset names. Do not translate; pick one of the declared presets."),
}


def _annotate(issue: Issue) -> None:
    """Attach healing_hint + subagent in-place. Idempotent."""
    # Everything in project-context.json is the Scout's responsibility.
    issue.subagent = issue.subagent or "scout"

    field = issue.field or ""
    msg = issue.message or ""

    # Pattern 1 — enum violation on a known machine field
    if "is not in enum" in msg:
        # Walk the field path backwards to find the last segment (strip array indices).
        tail = field.rsplit(".", 1)[-1]
        # Strip trailing [N] if present
        import re as _re
        tail = _re.sub(r"\[\d+\]$", "", tail)
        expected, hint = _ENUM_FIELDS_MACHINE.get(
            tail,
            (None,
             f"This field is a machine enum. Replace the rejected value with one of the allowed values listed in the message. Do not translate enum values under --lang ja."),
        )
        issue.expected = expected or issue.expected
        issue.healing_hint = hint
        # Try to pull `found` out of the message between the first pair of quotes
        import re as _re2
        m = _re2.search(r"value '([^']*)'", msg)
        if m:
            issue.found = m.group(1)
        return

    # Pattern 2 — required field missing
    if "is missing" in msg:
        issue.expected = "field present"
        issue.healing_hint = (
            f"Your previous output was missing the required field '{field}'. "
            "Add it using the schema definition at schemas/project-context.schema.json. "
            "Do not rewrite the whole file — patch only this field and re-Write."
        )
        return

    # Pattern 3 — unknown field
    if "Unknown field" in msg:
        issue.expected = "field removed or moved"
        issue.healing_hint = (
            f"You added a field '{field}' that is not in the schema. "
            "Remove it — the schema blocks additionalProperties at the top level. "
            "If the information is important, see if it fits in discovery_notes or an existing field."
        )
        return

    # Pattern 4 — duplicate id
    if msg.startswith("Duplicate"):
        issue.expected = "unique ids"
        issue.healing_hint = (
            "Two entries share the same id. Ids are slugs used for cross-references "
            "(journey_chains, job_ids, next_journey). Rename one of the duplicates "
            "and update any reference to the renamed id."
        )
        return

    # Pattern 5 — reference to unknown id
    if "references unknown" in msg:
        issue.expected = "resolvable cross-reference"
        issue.healing_hint = (
            "A cross-reference points at an id that does not exist in this file. "
            "Either add the missing entry or remove the reference. Do not silently "
            "drop the linked data — document the removal in discovery_notes if you "
            "intended to drop it."
        )
        return

    # Pattern 6 — too many jobs (warning)
    if "too many" in msg or ("jobs found" in msg and "probably too many" in msg):
        issue.expected = "1–3 jobs, rarely 4"
        issue.healing_hint = (
            "Job list is padded. Merge jobs whose actors/outcomes overlap, and drop any "
            "whose evidence_basis is empty or low-confidence. A 5th job is acceptable only "
            "if it has at least one evidence_basis entry at confidence >= medium AND a "
            "distinct first_value from every other job."
        )
        return

    # Pattern 7 — too few journeys (warning)
    if "Only" in msg and "journey(s) synthesized" in msg:
        issue.expected = "category floor reached or documented gap"
        issue.healing_hint = (
            "Journey count is below the category floor. Either (a) re-run discovery "
            "sources D3 (route enumeration) and D4 (README/spec user stories) to find "
            "more honest journeys, or (b) document in discovery_notes and "
            "experience_model.open_questions WHY the gap exists. Never pad with "
            "low-confidence speculation to pass this check."
        )
        return

    # Pattern 8 — high-priority job with no journey (warning)
    if "High-priority job" in msg and "not referenced" in msg:
        issue.expected = "job linked to >=1 journey via job_ids"
        issue.healing_hint = (
            "A high-priority job has no primary_journey that serves it. Either add a "
            "journey whose job_ids includes this job, or downgrade the job's priority "
            "if it's not actually the spine of the product."
        )
        return

    # Pattern 9 — empty evidence_basis
    if "empty evidence_basis" in msg:
        issue.expected = "at least one evidence_basis entry"
        issue.healing_hint = (
            "Every job must declare where its contract came from. Add at least one "
            "evidence_basis entry with source + kind + confidence. If you synthesized "
            "the job from JTBD reasoning alone, use kind='jtbd' and confidence='low' "
            "honestly."
        )
        return

    # Pattern 10 — type mismatch
    if "must be one of" in msg:
        issue.expected = "correct JSON type"
        issue.healing_hint = (
            "The value has the wrong JSON type. Check the schema — strings must be "
            "quoted, arrays need brackets, objects need braces. Do not wrap scalars "
            "in arrays."
        )
        return

    # Default fallback
    issue.healing_hint = (
        "The validator rejected this field. Re-read the schema at "
        "schemas/project-context.schema.json for the correct shape, "
        "patch only this field, and re-Write."
    )


def annotate_report(report: Report) -> None:
    for issue in report.issues:
        _annotate(issue)


def validate_project_context(project_context_path: Path,
                             schema_path: Path = SCHEMA_PATH_DEFAULT) -> Report:
    report = Report()
    report.checked = 1

    if not schema_path.exists():
        report.issues.append(Issue("error", str(schema_path), None,
                                   f"Schema file not found: {schema_path}"))
        return report

    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as e:
        report.issues.append(Issue("error", str(schema_path), None,
                                   f"Could not parse schema: {e}"))
        return report

    if not project_context_path.exists():
        report.issues.append(Issue("error", str(project_context_path), None,
                                   f"project-context.json not found: {project_context_path}"))
        return report

    try:
        data = json.loads(project_context_path.read_text())
    except json.JSONDecodeError as e:
        report.issues.append(Issue("error", str(project_context_path), None,
                                   f"Invalid JSON: {e}"))
        return report

    report.issues.extend(validate_against_schema(data, schema, file=str(project_context_path)))
    report.issues.extend(validate_structural(data, file=str(project_context_path)))
    annotate_report(report)
    _write_warnings_sidecar(project_context_path, report)
    return report


def _write_warnings_sidecar(project_context_path: Path, report: Report) -> None:
    """Persist non-blocking warnings next to project-context.json so the
    aggregator can forward them into benchmark.json.metadata.coverage_caveats.

    Playbook 01-discovery.md Step 4 promises: "Warnings do not block; they
    should be surfaced to the user and carried into the final summary as
    coverage caveats." Without this sidecar, aggregate.py has no way to reach
    them — they die on stdout at Phase 01 time. Writing only warnings (not
    errors) keeps the sidecar focused on "things the human should know about
    the coverage of this audit," not error replay.
    """
    sidecar_path = project_context_path.with_suffix(project_context_path.suffix + ".warnings.json")
    warnings = report.warnings
    if not warnings:
        # Remove a stale sidecar from a previous run so the aggregator doesn't
        # report ghost caveats after the Scout was re-dispatched cleanly.
        if sidecar_path.exists():
            try:
                sidecar_path.unlink()
            except OSError:
                pass
        return
    payload = {
        "source": str(project_context_path),
        "warnings": [w.to_dict() for w in warnings],
    }
    try:
        sidecar_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    except OSError:
        # Sidecar is best-effort; a write failure should not block validation.
        pass


def format_report(report: Report) -> str:
    lines = []
    err = report.errors
    warn = report.warnings
    lines.append(f"Checked {report.checked} project-context file(s)")
    lines.append(f"  errors:   {len(err)}")
    lines.append(f"  warnings: {len(warn)}")
    lines.append("")

    if err:
        lines.append("ERRORS")
        for i in err:
            lines.append(f"  ✗ {i.field or '-'}")
            lines.append(f"    {i.message}")
            if i.healing_hint:
                lines.append(f"    → {i.healing_hint}")
            lines.append(f"    in {i.file}")
        lines.append("")

    if warn:
        lines.append("WARNINGS")
        for i in warn:
            lines.append(f"  ! {i.field or '-'}")
            lines.append(f"    {i.message}")
            if i.healing_hint:
                lines.append(f"    → {i.healing_hint}")
        lines.append("")

    if not err and not warn:
        lines.append("project-context.json conforms to the schema and structural rules.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Scout project-context.json output.")
    parser.add_argument("project_context", type=Path, help="Path to project-context.json")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH_DEFAULT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    report = validate_project_context(args.project_context, args.schema)

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
