#!/usr/bin/env python3
"""Pre-flight validator for uxaudit check manifests.

Walks `checks/<category>/<name>/check.json` and validates each one against
`schemas/check-manifest.schema.json` plus a set of structural rules that the
JSON Schema can't express:

  - The check id must match the on-disk path (`checks/foo/bar/check.json` → id `foo/bar`)
  - The category in id must match the directory name
  - The implementation file must exist for the declared method:
      L1-script   → detect.py
      L2-script   → run.mjs
      L3-vision   → prompt.md
      L4-journey  → prompt.md
  - Soft warnings: vague rationale, single-source citation, adjective-heavy pass_criteria

Exit code:
  0 — no errors (warnings allowed)
  1 — at least one error
  2 — usage error / can't read schema

Designed to be:
  - Stdlib only (no jsonschema dependency, so it runs in any environment)
  - Idempotent (safe to run any number of times)
  - Callable as a library: validate_all(checks_dir, schema_path) -> Report
  - Callable as a CLI from `python validate_checks.py [--checks-dir DIR] [--json]`
  - Wired into run_all_checks.py as a pre-flight gate

Why hand-rolled instead of `jsonschema`:
  This skill ships with a vendored Python toolchain and we want zero pip
  install steps. The check manifest schema is small enough that walking it
  manually is straightforward and gives us better error messages than
  jsonschema's default output.
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
CHECKS_DIR_DEFAULT = SKILL_DIR / "checks"
SCHEMA_PATH_DEFAULT = SKILL_DIR / "schemas" / "check-manifest.schema.json"

# Method → required implementation file (relative to the check directory)
METHOD_IMPLS: dict[str, str] = {
    "L1-script": "detect.py",
    "L2-script": "run.mjs",
    "L3-vision": "prompt.md",
    "L4-journey": "prompt.md",
}

# Soft signals — flagged as warnings, not errors. Adjusting these is part of
# the authoring contract; see references/authoring/check-authoring.md for the rationale.
VAGUE_RATIONALE_WORDS = {
    "important",
    "matters",
    "good",
    "bad",
    "better",
    "improves",
    "improve usability",
    "improve ux",
    "best practice",
    "should be",
    "would be",
}

ADJECTIVE_PASS_CRITERIA_WORDS = {
    "well",
    "good",
    "reasonable",
    "appropriate",
    "nice",
    "clean",
    "polished",
    "professional",
}

@dataclass
class Issue:
    """A single validation finding."""
    severity: str  # "error" | "warning"
    check_id: str  # may be "<unknown>" if the file failed to parse
    file: str
    field: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "check_id": self.check_id,
            "file": self.file,
            "field": self.field,
            "message": self.message,
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


# ---------------------------------------------------------------------------
# Schema walker (hand-rolled, stdlib-only)
# ---------------------------------------------------------------------------


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


def validate_against_schema(
    manifest: dict[str, Any],
    schema: dict[str, Any],
    *,
    check_id: str,
    file: str,
) -> list[Issue]:
    """Walk the (small, top-level) check-manifest schema. Returns errors only.

    Supports the subset of JSON Schema we actually use:
      - type
      - required
      - additionalProperties: false
      - enum
      - minLength / maxLength
      - pattern
    """
    issues: list[Issue] = []

    if schema.get("type") == "object":
        if not isinstance(manifest, dict):
            issues.append(Issue("error", check_id, file, None,
                                f"Expected an object, got {type(manifest).__name__}"))
            return issues

        # Required
        for req in schema.get("required", []):
            if req not in manifest:
                issues.append(Issue("error", check_id, file, req,
                                    f"Required field '{req}' is missing"))

        # additionalProperties
        if schema.get("additionalProperties") is False:
            allowed = set((schema.get("properties") or {}).keys())
            for key in manifest.keys():
                if key not in allowed:
                    issues.append(Issue("error", check_id, file, key,
                                        f"Unknown field '{key}' (additionalProperties: false)"))

        # Per-field
        for key, subschema in (schema.get("properties") or {}).items():
            if key not in manifest:
                continue  # required already handled
            value = manifest[key]
            issues.extend(_validate_value(value, subschema, key, check_id, file))

    return issues


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
            f"Field '{field_name}' must be {expected_type}, got {type(value).__name__}",
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

    return issues


# ---------------------------------------------------------------------------
# Structural rules (cross-file invariants the schema can't express)
# ---------------------------------------------------------------------------


def validate_structural(
    manifest: dict[str, Any],
    manifest_path: Path,
    checks_dir: Path,
) -> list[Issue]:
    """Walk invariants between the manifest and the on-disk filesystem."""
    issues: list[Issue] = []
    rel = manifest_path.relative_to(checks_dir)  # e.g. ai-slop/purple-gradient/check.json
    parts = rel.parts
    file_str = str(manifest_path)
    declared_id = manifest.get("id", "<unknown>")

    # Path shape: <category>/<name>/check.json
    if len(parts) != 3 or parts[2] != "check.json":
        issues.append(Issue(
            "error", declared_id, file_str, None,
            f"check.json must live at checks/<category>/<name>/check.json "
            f"(got {rel})",
        ))
        return issues

    category_dir, name_dir, _ = parts
    expected_id = f"{category_dir}/{name_dir}"

    # ID must match path
    if declared_id != expected_id:
        issues.append(Issue(
            "error", declared_id, file_str, "id",
            f"Declared id '{declared_id}' does not match on-disk path "
            f"(expected '{expected_id}')",
        ))

    # Implementation file must exist for the declared method
    method = manifest.get("method")
    if method in METHOD_IMPLS:
        impl = manifest_path.parent / METHOD_IMPLS[method]
        if not impl.exists():
            issues.append(Issue(
                "error", declared_id, file_str, "method",
                f"Method '{method}' requires {METHOD_IMPLS[method]} next to "
                f"check.json, but {impl.name} is missing",
            ))

    # Subtype conditional: required for `ux` band, forbidden for `ui-risk` band.
    # The dashboard groups ux checks by subtype (understand → decide → act →
    # recover); ui-risk checks have no subtype because they're not about a
    # user action.
    band = manifest.get("band")
    has_subtype = "subtype" in manifest
    if band == "ux" and not has_subtype:
        issues.append(Issue(
            "error", declared_id, file_str, "subtype",
            "subtype is required when band is 'ux'. Pick one of: "
            "understand, decide, act, recover.",
        ))
    if band == "ui-risk" and has_subtype:
        issues.append(Issue(
            "error", declared_id, file_str, "subtype",
            "subtype must NOT be set when band is 'ui-risk'. Remove the field.",
        ))

    return issues


# ---------------------------------------------------------------------------
# Soft heuristics (warnings, not errors)
# ---------------------------------------------------------------------------


def soft_signals(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> list[Issue]:
    """Heuristics that flag low-quality fields without blocking the run."""
    issues: list[Issue] = []
    file_str = str(manifest_path)
    check_id = manifest.get("id", "<unknown>")

    # Too-many-sources cap. The source field is copied verbatim into every
    # Judge dispatch prompt, so length here is context cost. '+' is the
    # canonical separator between citations, so 3 citations max = 2 '+'
    # separators. We do NOT count " and " as a separator because article
    # titles routinely contain it (e.g., Krug Ch 6 "Street signs and
    # breadcrumbs"). Taste (which sources are acceptable) lives in
    # references/knowledge/sources.md and is enforced by human review.
    raw_source = manifest.get("source") or ""
    separator_count = raw_source.count("+")
    if separator_count >= 3:
        issues.append(Issue(
            "warning", check_id, file_str, "source",
            f"Source field has {separator_count + 1} citations joined by '+'. "
            "Cap at 3 (two '+' separators). Redundant citations bloat the Judge "
            "prompt without adding rigor; move secondary references into the "
            "rationale prose instead.",
        ))

    # Vague rationale
    rationale = (manifest.get("rationale") or "").lower()
    vague_hits = sorted(w for w in VAGUE_RATIONALE_WORDS if w in rationale)
    if rationale and len(vague_hits) >= 2:
        issues.append(Issue(
            "warning", check_id, file_str, "rationale",
            f"Rationale is light on substance — uses generic boost-words: "
            f"{', '.join(vague_hits)}. Cite the specific principle and the "
            "concrete cost the user pays when this fails.",
        ))

    # Adjective-heavy pass_criteria
    pass_criteria = (manifest.get("pass_criteria") or "").lower()
    adj_hits = sorted(w for w in ADJECTIVE_PASS_CRITERIA_WORDS if w in pass_criteria)
    has_threshold = bool(re.search(r"\d+\s*(%|px|em|chars?|rems?|>=|<=|<|>)|"
                                    r">=|<=|<|>|≥|≤|threshold|"
                                    r"\bfewer than\b|\bat least\b|\bno more than\b|"
                                    r"\bno\b|\bzero\b", pass_criteria))
    if pass_criteria and adj_hits and not has_threshold:
        issues.append(Issue(
            "warning", check_id, file_str, "pass_criteria",
            f"pass_criteria is adjective-heavy ({', '.join(adj_hits)}) but has no "
            "measurable threshold. Two judges should agree on the verdict from "
            "this string alone — express it in counts/ratios/ranges, not "
            "qualities.",
        ))

    return issues


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------


def validate_all(
    checks_dir: Path = CHECKS_DIR_DEFAULT,
    schema_path: Path = SCHEMA_PATH_DEFAULT,
) -> Report:
    """Validate every check.json under `checks_dir`. Returns a Report."""
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

    if not checks_dir.exists():
        report.issues.append(Issue(
            "error", "<checks-dir>", str(checks_dir), None,
            f"Checks directory not found: {checks_dir}",
        ))
        return report

    for manifest_path in sorted(checks_dir.rglob("check.json")):
        report.checked += 1
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as e:
            report.issues.append(Issue(
                "error", "<unparseable>", str(manifest_path), None,
                f"Invalid JSON: {e}",
            ))
            continue

        check_id = manifest.get("id", "<unknown>")
        report.issues.extend(validate_against_schema(
            manifest, schema, check_id=check_id, file=str(manifest_path),
        ))
        report.issues.extend(validate_structural(
            manifest, manifest_path, checks_dir,
        ))
        report.issues.extend(soft_signals(manifest, manifest_path))

    return report


def format_report(report: Report) -> str:
    lines: list[str] = []
    err = report.errors
    warn = report.warnings
    lines.append(f"Checked {report.checked} manifest(s)")
    lines.append(f"  errors:   {len(err)}")
    lines.append(f"  warnings: {len(warn)}")
    lines.append("")

    if err:
        lines.append("ERRORS")
        for i in err:
            lines.append(f"  ✗ [{i.check_id}] {i.field or '-'}")
            lines.append(f"    {i.message}")
            lines.append(f"    in {i.file}")
        lines.append("")

    if warn:
        lines.append("WARNINGS")
        for i in warn:
            lines.append(f"  ! [{i.check_id}] {i.field or '-'}")
            lines.append(f"    {i.message}")
        lines.append("")

    if not err and not warn:
        lines.append("All check manifests are valid.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate uxaudit check manifests against the schema "
                    "and structural rules.",
    )
    parser.add_argument("--checks-dir", type=Path, default=CHECKS_DIR_DEFAULT,
                        help="Root directory containing check.json manifests "
                             f"(default: {CHECKS_DIR_DEFAULT})")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH_DEFAULT,
                        help=f"Path to check-manifest.schema.json "
                             f"(default: {SCHEMA_PATH_DEFAULT})")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON report instead of human-readable text")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress output unless there are errors")
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors (exit non-zero on warnings)")
    args = parser.parse_args()

    report = validate_all(args.checks_dir, args.schema)

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
