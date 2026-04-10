#!/usr/bin/env python3
"""Detect skipped heading levels (h1 → h3) in rendered HTML."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

HEADING_RE = re.compile(r"<h([1-6])([^>]*)>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""

    # Extract headings in document order
    headings = []
    for m in HEADING_RE.finditer(html):
        level = int(m.group(1))
        text = strip_tags(m.group(3))
        if text:
            headings.append((level, text))

    if not headings:
        write_result(
            output_path, manifest,
            result="fail",
            details="No heading elements (h1-h6) found in the rendered HTML.",
            suggestion=(
                "Add at least one h1 describing what the page is. WCAG SC 1.3.1 (A) requires "
                "structural relationships to be programmatically determinable, and headings are "
                "the primary structural mechanism."
            ),
        )
        return

    # Count h1s
    h1_count = sum(1 for lvl, _ in headings if lvl == 1)

    # Find skip violations
    skips = []
    prev_level = 0
    for i, (lvl, text) in enumerate(headings):
        if prev_level > 0 and lvl > prev_level + 1:
            skips.append({
                "type": "skip",
                "matched_text": f"h{prev_level} → h{lvl}: \"{text[:80]}\"",
                "prev_level": prev_level,
                "skipped_to": lvl,
            })
        prev_level = lvl

    issues = []
    if h1_count == 0:
        issues.append("No <h1> element found")
    elif h1_count > 1:
        issues.append(f"{h1_count} <h1> elements found (should be exactly 1)")
    if skips:
        issues.append(f"{len(skips)} skipped heading level(s)")

    if not issues:
        write_result(
            output_path, manifest,
            result="pass",
            details=f"Found {len(headings)} heading(s) with valid hierarchy. 1 h1, no level skips.",
        )
    else:
        details = (
            f"Heading outline issues: {'; '.join(issues)}. "
            f"Total headings: {len(headings)} ({h1_count} h1)."
        )
        suggestion = (
            "Fix the heading outline: exactly one <h1> for the page topic, then h2 for "
            "main sections, h3 for subsections, etc. Don't skip levels for visual styling — "
            "use CSS to make h2 look smaller if needed, but keep the document structure correct. "
            "Screen reader users navigate by headings."
        )
        write_result(
            output_path, manifest,
            result="fail",
            details=details,
            matches=skips[:10],
            suggestion=suggestion,
        )


if __name__ == "__main__":
    run_detect(detect)
