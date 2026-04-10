#!/usr/bin/env python3
"""Detect the AI slop purple/violet/indigo gradient pattern in CSS."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Hex codes commonly used in "AI slop" purple gradients (Tailwind defaults).
# We're looking for gradients that combine 2+ of these.
PURPLE_HEX = [
    # Tailwind purple
    "#a855f7", "#9333ea", "#7e22ce", "#6b21a8", "#581c87",
    # Tailwind violet
    "#8b5cf6", "#7c3aed", "#6d28d9", "#5b21b6", "#4c1d95",
    # Tailwind indigo
    "#6366f1", "#4f46e5", "#4338ca", "#3730a3", "#312e81",
    # Tailwind pink (often the third stop)
    "#ec4899", "#db2777", "#be185d", "#9d174d",
    # Bootstrap-style
    "#667eea", "#764ba2", "#6a11cb", "#2575fc",
    # Common AI gradient blues that pair with purple
    "#3b82f6", "#2563eb", "#1d4ed8",
]


def hex_to_rgb_string(hex_code: str) -> str:
    """#667eea -> 'rgb(102, 126, 234)'  (matches browser-computed format)."""
    h = hex_code.lstrip("#")
    if len(h) != 6:
        return ""
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgb({r}, {g}, {b})"


# Build a lookup of all the indicator strings to scan for.
# Each indicator is the hex form OR the rgb() form (browsers convert hex -> rgb).
PURPLE_INDICATORS = []
for hex_code in PURPLE_HEX:
    PURPLE_INDICATORS.append((hex_code, hex_code))  # display, search
    rgb = hex_to_rgb_string(hex_code)
    if rgb:
        PURPLE_INDICATORS.append((hex_code, rgb))

# Tailwind gradient utility class hints
TAILWIND_HINTS = [
    r"from-purple-\d{3}", r"to-purple-\d{3}", r"via-purple-\d{3}",
    r"from-violet-\d{3}", r"to-violet-\d{3}", r"via-violet-\d{3}",
    r"from-indigo-\d{3}", r"to-indigo-\d{3}", r"via-indigo-\d{3}",
    r"from-pink-\d{3}\s+via-purple-\d{3}",
    r"from-purple-\d{3}\s+to-pink-\d{3}",
    r"from-indigo-\d{3}\s+via-purple-\d{3}",
]


def find_gradients(css: str) -> list[str]:
    """Return the text of every linear-gradient(...) call in the CSS, handling nested parens."""
    gradients = []
    i = 0
    needle = "linear-gradient("
    text = css
    while True:
        idx = text.lower().find(needle, i)
        if idx == -1:
            break
        # Walk forward to find the matching closing paren
        depth = 0
        j = idx + len(needle) - 1  # position of the opening (
        end = -1
        while j < len(text):
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if end == -1:
            break
        gradients.append(text[idx:end + 1])
        i = end + 1
    return gradients


def gradient_uses_purple(gradient: str) -> tuple[bool, list[str]]:
    """Return (is_purple_gradient, matched_indicators)."""
    text = gradient.lower()
    matched = []
    for display, search in PURPLE_INDICATORS:
        if search in text and display not in matched:
            matched.append(display)
    # Also check for 'purple', 'violet', 'indigo' keywords
    keyword_hits = []
    for kw in ["purple", "violet", "indigo"]:
        if kw in text:
            keyword_hits.append(kw)
    return (len(matched) >= 2 or len(keyword_hits) >= 1, matched + keyword_hits)


def detect(*, manifest, target, evidence_dir, output_path):
    css = target.get("stylesheets.css") or ""
    html = target.get("rendered.html") or ""

    matches = []

    # 1. Inspect linear-gradient() calls in CSS
    for grad in find_gradients(css):
        is_purple, hits = gradient_uses_purple(grad)
        if is_purple:
            matches.append({
                "type": "css-gradient",
                "matched_text": grad[:120],
                "indicators": hits,
            })

    # 2. Inspect Tailwind utility classes in HTML
    for pat in TAILWIND_HINTS:
        for m in re.finditer(pat, html, re.IGNORECASE):
            matches.append({
                "type": "tailwind-class",
                "matched_text": m.group(0),
                "indicators": [m.group(0)],
            })

    # Dedupe by matched_text
    seen = set()
    unique = []
    for m in matches:
        key = m["matched_text"]
        if key not in seen:
            seen.add(key)
            unique.append(m)
    matches = unique

    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No purple/violet/indigo default gradient patterns detected in CSS or class names.",
        )
    else:
        details = (
            f"Found {len(matches)} purple-default gradient indicator(s). "
            "These are the statistical-average colors LLMs use when no design language is specified."
        )
        suggestion = (
            "If purple was a deliberate choice, ignore. Otherwise, replace with a single accent color "
            "from your spec's design language. A distinctive product uses 1-2 brand colors with intent, "
            "not the Tailwind/Stripe gradient defaults. Consider monochrome + one accent."
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
