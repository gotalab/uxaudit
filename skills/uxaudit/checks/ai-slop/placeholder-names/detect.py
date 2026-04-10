#!/usr/bin/env python3
"""Detect Alice/Bob/Charlie textbook placeholder names in visible text."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Cluster pattern: if 2+ of these names appear together, it's clearly placeholder data
TEXTBOOK_NAMES = [
    "Alice", "Bob", "Charlie", "Eve", "Mallory", "Trent", "Walter",
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

    # Find each textbook name as a standalone word (case-insensitive)
    found = {}
    for name in TEXTBOOK_NAMES:
        hits = list(re.finditer(rf"\b{name}\b", visible_text))
        if hits:
            found[name] = len(hits)

    matches = [{"name": k, "count": v} for k, v in found.items()]
    distinct = len(found)

    if distinct < 2:
        # 0 or 1 hit isn't enough — could be a real "Alice" user
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"No textbook-name cluster detected (found {distinct} distinct textbook names; "
                "need 2+ for high confidence)."
            ),
            matches=matches,
        )
    else:
        details = (
            f"Found {distinct} textbook placeholder names ({', '.join(found.keys())}). "
            "Together they signal the data is generated from defaults rather than real users."
        )
        suggestion = (
            "Replace seed/sample data with names appropriate to the app's audience. "
            "If this is for a Japanese-market app, use Japanese names. If it's a globally distributed product, "
            "use a diverse set of plausible names. Better still: empty state with a 'create your first X' CTA."
        )
        write_result(
            output_path, manifest,
            result="fail",
            details=details,
            matches=matches,
            suggestion=suggestion,
        )


if __name__ == "__main__":
    run_detect(detect)
