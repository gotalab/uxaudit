#!/usr/bin/env python3
"""Detect default LLM-cliché taglines in heading elements."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Tagline patterns. Each is a regex; matched against heading text content.
# These are the highest-probability "write a SaaS landing page tagline" outputs.
TAGLINE_PATTERNS = [
    (r"\bbuild\s+\w[\w\s]{0,30}\s+in\s+(minutes|seconds|hours)\b", "Build X in minutes"),
    (r"\bthe\s+future\s+of\s+\w[\w\s]{0,30}\b", "The future of X"),
    (r"\b\w[\w\s]{0,30}\s+for\s+the\s+modern\s+web\b", "X for the modern web"),
    (r"\b\w[\w\s]{0,30},?\s+reimagined\b", "X, reimagined"),
    (r"\breimagining\s+\w[\w\s]{0,30}\b", "Reimagining X"),
    (r"\bbeautiful\s+\w[\w\s]{0,30},\s+simple\s+\w+\b", "Beautiful X, simple Y"),
    (r"\bpowerful\s+\w[\w\s]{0,30}\s+for\s+\w[\w\s]{0,30}\b", "Powerful X for Y"),
    (r"\bnext[-\s]gen(eration)?\s+\w[\w\s]{0,30}\b", "Next-generation X"),
    (r"\bAI[-\s]powered\s+\w[\w\s]{0,30}\b", "AI-powered X"),
    (r"\bsupercharge\s+your\s+\w[\w\s]{0,30}\b", "Supercharge your X"),
    (r"\bunlock\s+the\s+power\s+of\s+\w[\w\s]{0,30}\b", "Unlock the power of X"),
    (r"\beverything\s+you\s+need\s+to\s+\w[\w\s]{0,30}\b", "Everything you need to X"),
    (r"\b\w[\w\s]{0,30},\s+all\s+in\s+one\s+place\b", "X, all in one place"),
    (r"\bwhere\s+\w[\w\s]{0,30}\s+meets?\s+\w[\w\s]{0,30}\b", "Where X meets Y"),
]


def extract_headings(html: str) -> list[tuple[str, str]]:
    """Extract (tag, text) from h1-h3 elements. Crude but adequate for AI-generated HTML."""
    headings = []
    for tag in ["h1", "h2", "h3"]:
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE):
            inner = m.group(1)
            # Strip nested tags
            text = re.sub(r"<[^>]+>", " ", inner)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                headings.append((tag, text))
    return headings


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    headings = extract_headings(html)

    matches = []
    for tag, text in headings:
        for pattern, label in TAGLINE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append({
                    "type": f"<{tag}> tagline",
                    "pattern": label,
                    "matched_text": text[:160],
                })
                break  # one pattern per heading is enough

    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details=f"Scanned {len(headings)} heading(s); none match default tagline patterns.",
        )
    else:
        details = (
            f"Found {len(matches)} heading(s) matching default LLM-cliché tagline patterns. "
            "These are the highest-probability outputs of 'write a SaaS landing page tagline' "
            "and signal a tagline that names no actual differentiator."
        )
        suggestion = (
            "Replace with a tagline that names something concrete and specific to YOUR product. "
            "Test: would the same tagline work for any other app in the category? If yes, it's "
            "the LLM default and should be rewritten with the product's actual point of view."
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
