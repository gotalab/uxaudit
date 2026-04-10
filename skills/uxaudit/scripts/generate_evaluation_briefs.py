#!/usr/bin/env python3
"""Generate compressed evaluation briefs from project-context.json.

These briefs are the safe middle layer between Scout and Judge:
  - richer than generic catalog prompts
  - much smaller than the full project context/spec
  - generated only for checks that materially benefit from project-shaped context

Output layout:
  <output-dir>/
    index.json
    core-experience-value-prop-clarity.json
    usability-empty-state-guidance.json
    ...
    core-experience-primary-journey--reserve-viewing.json

The orchestrator can inject the relevant brief into Judge prompts without
granting Judges read access to project-context.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_project_context import format_report, validate_project_context

LENS_BY_CHECK: dict[str, str] = {
    "core-experience/value-prop-clarity": "understand",
    "usability/empty-state-guidance": "act",
    "core-experience/primary-journey": "act",
    "usability/first-time-user-experience": "act",
}

GENERIC_L3_CHECKS: tuple[str, ...] = (
    "core-experience/value-prop-clarity",
    "usability/empty-state-guidance",
)

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _slugify_check_id(check_id: str) -> str:
    return check_id.replace("/", "-")


def _priority(job: dict[str, Any]) -> tuple[int, str]:
    return PRIORITY_RANK.get(job.get("priority", "low"), 99), job.get("id", "")


def _select_job_fields(job: dict[str, Any], lens: str) -> dict[str, Any]:
    base = {
        "job_id": job.get("id"),
        "name": job.get("name"),
        "priority": job.get("priority"),
        "actor": job.get("actor"),
        "outcome": job.get("outcome"),
        "contexts": job.get("contexts") or [],
        "first_value": job.get("first_value"),
    }
    if lens == "understand":
        base["must_understand"] = job.get("must_understand") or []
    elif lens == "act":
        base["progress_signals"] = job.get("progress_signals") or []
        base["simplicity_rules"] = job.get("simplicity_rules") or []
        base["recovery_points"] = job.get("recovery_points") or []
    return base


def _top_jobs(project_context: dict[str, Any], lens: str, *, contexts: set[str] | None = None) -> list[dict[str, Any]]:
    jobs = sorted((project_context.get("experience_model") or {}).get("jobs") or [], key=_priority)
    selected: list[dict[str, Any]] = []
    for job in jobs:
        if contexts:
            job_contexts = set(job.get("contexts") or [])
            if not job_contexts.intersection(contexts):
                continue
        selected.append(_select_job_fields(job, lens))
    return selected[:3]

def _jobs_by_id(project_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = (project_context.get("experience_model") or {}).get("jobs") or []
    return {
        job["id"]: job
        for job in jobs
        if isinstance(job, dict) and job.get("id")
    }


def _journey_brief(project_context: dict[str, Any], journey: dict[str, Any], check_id: str) -> dict[str, Any]:
    lens = LENS_BY_CHECK[check_id]
    jobs = _jobs_by_id(project_context)
    matched_jobs: list[dict[str, Any]] = []
    for job_id in journey.get("job_ids") or []:
        if job_id in jobs:
            matched_jobs.append(_select_job_fields(jobs[job_id], lens))
    if not matched_jobs:
        # Fallback: pick top jobs for the same context if explicit mapping is absent.
        matched_jobs = _top_jobs(project_context, lens, contexts={journey.get("context", "returning")})

    # Lift first_value from the primary matched job to the top of the journey
    # block so the L4 Judge can find it with one key instead of diving into
    # job_summaries. The job-level first_value is the abstract value
    # ("user has a recipe to cook"); the journey-level first_value_signals
    # are the concrete observable indicators on *this* specific journey.
    # The 4-axis value_delivery evaluation uses both.
    primary_first_value: str | None = None
    for mj in matched_jobs:
        if mj.get("first_value"):
            primary_first_value = mj.get("first_value")
            break

    journey_block: dict[str, Any] = {
        "journey_id": journey.get("id"),
        "name": journey.get("name"),
        "goal": journey.get("goal"),
        "starting_url": journey.get("starting_url"),
        "success_criteria": journey.get("success_criteria"),
        "context": journey.get("context"),
        "steps_hint": journey.get("steps_hint") or [],
        "job_ids": journey.get("job_ids") or [],
        # Hypothesis strength — the downstream pipeline weights fails by this.
        # Absent in the journey → default to `medium` at the brief level so
        # downstream readers never have to check `None`.
        "confidence": journey.get("confidence") or "medium",
        # First-value: abstract (from the linked job) + concrete journey-level
        # signals. Both feed the L4 Judge's `value_delivery` axis.
        "first_value": primary_first_value,
        "first_value_signals": journey.get("first_value_signals") or [],
        # Intentional friction declared by the Scout. The L4 Judge matches
        # actual steps semantically against these entries and classifies
        # unmatched excess as unintentional excise.
        "intentional_friction": journey.get("intentional_friction") or [],
    }

    return {
        "check_id": check_id,
        "lens": lens,
        "purpose": project_context.get("purpose"),
        "target_audience": project_context.get("target_audience"),
        "category": project_context.get("category"),
        "journey": journey_block,
        "job_summaries": matched_jobs,
        "open_questions": ((project_context.get("experience_model") or {}).get("open_questions") or [])[:3],
    }


def _check_brief(project_context: dict[str, Any], check_id: str) -> dict[str, Any]:
    lens = LENS_BY_CHECK[check_id]
    contexts: set[str] | None = None
    if check_id == "usability/first-time-user-experience":
        contexts = {"cold-start"}
    top_jobs = _top_jobs(project_context, lens, contexts=contexts)
    return {
        "check_id": check_id,
        "lens": lens,
        "purpose": project_context.get("purpose"),
        "target_audience": project_context.get("target_audience"),
        "category": project_context.get("category"),
        "journey_count": len(project_context.get("primary_journeys") or []),
        "job_summaries": top_jobs,
        "open_questions": ((project_context.get("experience_model") or {}).get("open_questions") or [])[:3],
    }


def generate_briefs(project_context: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    briefs: list[tuple[str, dict[str, Any]]] = []

    for check_id in GENERIC_L3_CHECKS:
        briefs.append((_slugify_check_id(check_id) + ".json", _check_brief(project_context, check_id)))

    briefs.append((
        _slugify_check_id("usability/first-time-user-experience") + ".json",
        _check_brief(project_context, "usability/first-time-user-experience"),
    ))

    for journey in project_context.get("primary_journeys") or []:
        if not isinstance(journey, dict) or not journey.get("id"):
            continue
        check_id = "core-experience/primary-journey"
        filename = f"{_slugify_check_id(check_id)}--{journey['id']}.json"
        briefs.append((filename, _journey_brief(project_context, journey, check_id)))

    return briefs


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate evaluation briefs from project-context.json")
    parser.add_argument("project_context", type=Path, help="Path to project-context.json")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write evaluation brief JSON files into")
    parser.add_argument("--force", action="store_true", help="Generate briefs even if project-context validation has warnings/errors")
    args = parser.parse_args()

    report = validate_project_context(args.project_context)
    if not report.ok and not args.force:
        print(format_report(report), file=sys.stderr)
        return 1

    if report.warnings:
        print(format_report(report), file=sys.stderr)

    project_context = json.loads(args.project_context.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)

    briefs = generate_briefs(project_context)
    index: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_context": str(args.project_context),
        "briefs": [],
    }

    for filename, brief in briefs:
        path = args.output_dir / filename
        path.write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n")
        entry = {
            "path": str(path),
            "check_id": brief["check_id"],
            "lens": brief["lens"],
        }
        if "journey" in brief:
            entry["journey_id"] = brief["journey"]["journey_id"]
        index["briefs"].append(entry)

    (args.output_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(briefs)} evaluation brief(s) to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
