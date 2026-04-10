#!/usr/bin/env python3
"""Detect lorem ipsum and generic placeholder data in visible text."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

PATTERNS = [
    (r"\blorem\s+ipsum\s+dolor\s+sit\s+amet\b", "Lorem ipsum"),
    (r"\bconsectetur\s+adipiscing\s+elit\b", "Lorem ipsum continuation"),
    (r"\bsed\s+do\s+eiusmod\s+tempor\b", "Lorem ipsum continuation"),
    (r"\bjohn\s+doe\b", "John Doe placeholder"),
    (r"\bjane\s+(doe|smith)\b", "Jane Doe/Smith placeholder"),
    (r"\buser@example\.com\b", "user@example.com"),
    (r"\btest@test\.com\b", "test@test.com"),
    (r"\b123\s+main\s+st\b", "123 Main St placeholder address"),
    (r"\bfoo\s*bar\b", "Foo bar placeholder"),
    (r"\bsample\s+text\b", "Sample text label"),
    (r"\bexample\s+content\b", "Example content label"),
]


def detect(*, manifest, target, evidence_dir, output_path):
    visible_text = target.get("visible-text.txt") or ""
    if not visible_text.strip():
        write_result(
            output_path, manifest,
            result="skipped",
            details="No visible text captured.",
        )
        return

    matches = []
    for pat, label in PATTERNS:
        for m in re.finditer(pat, visible_text, re.IGNORECASE):
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
            details="No lorem ipsum or generic placeholder data found.",
        )
    else:
        details = f"Found {len(matches)} placeholder data pattern(s) in user-visible content."
        suggestion = (
            "Replace with real seed data appropriate to the domain, or show an empty state. "
            "Lorem ipsum tells users 'this isn't finished'. Either populate with realistic content "
            "(generated to fit the domain) or guide the user to create their own."
        )
        write_result(
            output_path, manifest,
            result="fail",
            details=details,
            matches=matches[:20],
            suggestion=suggestion,
        )


if __name__ == "__main__":
    run_detect(detect)
