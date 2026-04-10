#!/usr/bin/env python3
"""Detect generic-only font stacks (Inter/Roboto/Arial/system) in body font-family."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Fonts NN/g's "AI Prototyping in Real Design Contexts" research flags as
# part of the homogenized AI-tool default look (sans-serif typefaces, generic
# system stacks), plus generic CSS keywords that don't represent any choice
# at all.
GENERIC_FONTS = {
    "inter",
    "roboto",
    "arial",
    "helvetica",
    "helvetica neue",
    "system-ui",
    "-apple-system",
    "blinkmacsystemfont",
    "segoe ui",
    "sans-serif",
    "serif",
    "monospace",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
    # Tailwind preflight default expansion:
    "noto sans",
    "noto color emoji",
    "apple color emoji",
    "segoe ui emoji",
    "segoe ui symbol",
}


def normalize_font_name(name: str) -> str:
    return name.strip().strip('"').strip("'").lower()


def parse_font_family(value: str) -> list[str]:
    """Split a CSS font-family value into individual font names."""
    return [normalize_font_name(p) for p in value.split(",") if p.strip()]


def detect(*, manifest, target, evidence_dir, output_path):
    computed = target.get("computed-styles.json") or {}
    css = target.get("stylesheets.css") or ""

    # Primary: read body's computed font-family
    body_styles = computed.get("body") or {}
    body_font = body_styles.get("font-family", "")
    body_fonts = parse_font_family(body_font) if body_font else []

    matches = []
    distinctive_fonts: list[str] = []

    if body_fonts:
        distinctive_fonts = [f for f in body_fonts if f not in GENERIC_FONTS]
        matches.append({
            "type": "body-font-stack",
            "matched_text": body_font[:200],
            "distinctive_fonts": distinctive_fonts,
            "generic_fonts": [f for f in body_fonts if f in GENERIC_FONTS],
        })

    # Secondary: scan all @font-face declarations and font-family declarations in CSS
    custom_font_faces = re.findall(
        r"@font-face\s*\{[^}]*font-family:\s*['\"]?([^;'\"]+)['\"]?[^}]*\}",
        css,
        re.IGNORECASE,
    )
    custom_font_faces = [normalize_font_name(f) for f in custom_font_faces]
    custom_font_faces = [f for f in custom_font_faces if f not in GENERIC_FONTS]

    if custom_font_faces:
        matches.append({
            "type": "@font-face declarations",
            "matched_text": ", ".join(sorted(set(custom_font_faces))),
            "count": len(custom_font_faces),
        })

    # Decision: pass if either body has a distinctive font OR any custom @font-face is loaded
    has_distinctive_body = bool(distinctive_fonts)
    has_custom_face = bool(custom_font_faces)

    if has_distinctive_body or has_custom_face:
        details = (
            f"Distinctive font detected: "
            f"body uses {distinctive_fonts or '(none distinctive)'}, "
            f"@font-face: {sorted(set(custom_font_faces)) or '(none)'}."
        )
        write_result(
            output_path, manifest,
            result="pass",
            details=details,
            matches=matches,
        )
    else:
        details = (
            "Body font-family contains only generic fonts (Inter / Roboto / Arial / "
            "system-ui / sans-serif). No custom @font-face declarations found. "
            "NN/g's 'AI Prototyping in Real Design Contexts' research documents "
            "the generic sans-serif look as a primary fingerprint of AI-generated "
            "UIs: 'a similar, generic look' across every tool tested."
        )
        suggestion = (
            "Load at least one distinctive font (e.g., a display face from Google Fonts, "
            "or a self-hosted variable font). Pair a display font for headings with a "
            "refined body font. Even one intentional font is enough to break the slop signal."
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
