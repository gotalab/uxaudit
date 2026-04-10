#!/usr/bin/env python3
"""Detect 'coming soon' / placeholder labels in user-visible text."""
import re
import sys
from pathlib import Path

# Add scripts/ to path so we can import check_lib
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

PATTERNS = [
    (r"\bcoming\s+soon\b", "Coming soon"),
    (r"\bunder\s+construction\b", "Under construction"),
    (r"\bwork\s+in\s+progress\b", "Work in progress"),
    (r"\bTBD\b", "TBD"),
    (r"\bTODO\b(?!\s*[:.])", "TODO (visible to user)"),
    (r"\bplaceholder\b", "Placeholder"),
    (r"準備中", "準備中"),
    (r"近日公開", "近日公開"),
    (r"作業中", "作業中"),
]


def detect(*, manifest, target, evidence_dir, output_path):
    visible_text = target.get("visible-text.txt") or ""
    if not visible_text.strip():
        write_result(
            output_path, manifest,
            result="skipped",
            details="No visible text captured (target may not have rendered)",
        )
        return

    matches = []
    for pat, label in PATTERNS:
        for m in re.finditer(pat, visible_text, re.IGNORECASE):
            # Get a snippet around the match for context
            start = max(0, m.start() - 30)
            end = min(len(visible_text), m.end() + 30)
            snippet = visible_text[start:end].replace("\n", " ").strip()
            matches.append({
                "pattern": label,
                "matched_text": m.group(0),
                "context": f"…{snippet}…",
            })

    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No 'coming soon' / placeholder text found in user-visible content.",
        )
    else:
        details = f"Found {len(matches)} placeholder/coming-soon label(s) in user-visible text."
        suggestion = (
            "Either implement these features or remove the labels entirely. "
            "A missing feature is better than a stubbed one — users notice the difference. "
            "If a feature is genuinely planned, hide it from the UI until it ships."
        )
        write_result(
            output_path, manifest,
            result="fail",
            details=details,
            matches=matches[:20],  # cap to avoid huge results
            suggestion=suggestion,
        )


if __name__ == "__main__":
    run_detect(detect)
