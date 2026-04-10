#!/usr/bin/env python3
"""Detect default Tailwind shadow on white cards over gray bg."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Tailwind default shadow-md / shadow-lg / shadow-xl signatures.
# Browsers may reorder offsets and color components, so match by characteristic
# offset-tuple substrings within a box-shadow declaration.
# Each entry: (label, list of substrings that must all be present in the box-shadow text)
TAILWIND_SHADOW_SIGNATURES = [
    ("shadow-sm", ["0px 1px 2px", "rgba(0, 0, 0, 0.05)"]),
    ("shadow", ["0px 1px 3px", "rgba(0, 0, 0, 0.1)"]),
    ("shadow-md", ["0px 4px 6px -1px", "rgba(0, 0, 0, 0.1)"]),
    ("shadow-md alt", ["0px 4px 6px", "rgba(0, 0, 0, 0.1)"]),
    ("shadow-lg", ["0px 10px 15px -3px", "rgba(0, 0, 0, 0.1)"]),
    ("shadow-xl", ["0px 20px 25px -5px", "rgba(0, 0, 0, 0.1)"]),
    ("shadow-2xl", ["0px 25px 50px -12px", "rgba(0, 0, 0, 0.25)"]),
    ("material-md", ["0px 1px 3px", "rgba(0, 0, 0, 0.12)"]),
]

TAILWIND_CLASS_HINTS = [
    r"\bshadow-md\b", r"\bshadow-lg\b", r"\bshadow-xl\b", r"\bshadow-sm\b",
]


def detect(*, manifest, target, evidence_dir, output_path):
    css = target.get("stylesheets.css") or ""
    html = target.get("rendered.html") or ""

    matches = []

    # 1. Find every box-shadow declaration and check against signatures
    for m in re.finditer(r"box-shadow:\s*[^;]+;?", css, re.IGNORECASE):
        decl = m.group(0).strip().rstrip(";")
        decl_lower = decl.lower()
        for label, parts in TAILWIND_SHADOW_SIGNATURES:
            if all(p.lower() in decl_lower for p in parts):
                matches.append({
                    "type": "css-box-shadow",
                    "label": label,
                    "matched_text": decl[:160],
                })
                break  # one signature per declaration

    # 2. Tailwind class names in HTML
    for pat in TAILWIND_CLASS_HINTS:
        hits = list(re.finditer(pat, html))
        if hits:
            matches.append({
                "type": "tailwind-class",
                "matched_text": hits[0].group(0),
                "count": len(hits),
            })

    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No default Tailwind shadow patterns detected.",
        )
    else:
        details = (
            f"Found {len(matches)} default-shadow indicator(s). "
            "These are the Tailwind/Material defaults that signal a templated look."
        )
        suggestion = (
            "Pick one of: (a) borders instead of shadows for a flatter look, (b) custom shadow values "
            "tuned to your background color (e.g., colored shadows), or (c) no decoration with strong "
            "typography hierarchy. The default Tailwind shadow on white cards is the AI dashboard cliché."
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
