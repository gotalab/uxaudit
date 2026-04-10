#!/usr/bin/env python3
"""Check that h1/h2/body have distinct font sizes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402


def parse_px(value: str) -> float | None:
    if not value:
        return None
    try:
        v = value.strip().lower()
        if v.endswith("px"):
            return float(v[:-2])
    except ValueError:
        return None
    return None


def detect(*, manifest, target, evidence_dir, output_path):
    styles = target.get("computed-styles.json") or {}
    body_style = styles.get("body", {})
    h1_style = styles.get("h1", {})
    h2_style = styles.get("h2", {})

    body_size = parse_px(body_style.get("font-size", ""))
    h1_size = parse_px(h1_style.get("font-size", ""))
    h2_size = parse_px(h2_style.get("font-size", ""))

    matches = [
        {"selector": "body", "font-size": body_style.get("font-size", "?")},
        {"selector": "h1", "font-size": h1_style.get("font-size", "?")},
        {"selector": "h2", "font-size": h2_style.get("font-size", "?")},
    ]

    if not body_size or (not h1_size and not h2_size):
        write_result(
            output_path, manifest,
            result="skipped",
            details="Could not determine font sizes (missing h1/h2 or computed styles).",
            matches=matches,
        )
        return

    issues = []
    if h1_size and h1_size <= body_size * 1.3:
        issues.append(f"h1 ({h1_size:.0f}px) is barely larger than body ({body_size:.0f}px)")
    if h1_size and h2_size and abs(h1_size - h2_size) < 2:
        issues.append(f"h1 ({h1_size:.0f}px) and h2 ({h2_size:.0f}px) are nearly the same size")
    if h2_size and h2_size <= body_size * 1.1:
        issues.append(f"h2 ({h2_size:.0f}px) barely differs from body ({body_size:.0f}px)")

    if not issues:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Font hierarchy is distinct: body {body_size:.0f}px, "
                f"h1 {h1_size:.0f}px, h2 {h2_size:.0f}px."
            ),
            matches=matches,
        )
    else:
        write_result(
            output_path, manifest,
            result="fail",
            details="; ".join(issues),
            matches=matches,
            suggestion=(
                "Establish a clear typographic scale. Recommended ratios: body 16px, h2 24px (1.5×), "
                "h1 32-40px (2-2.5×). Larger contrast helps users scan and focuses attention on what matters."
            ),
        )


if __name__ == "__main__":
    run_detect(detect)
