#!/usr/bin/env python3
"""Detect trailing emojis in CTA button labels — an AI-slop fingerprint.

Complements ai-slop/emoji-as-icon (which catches LEADING emojis in
headings/buttons/links at threshold 3+). This check targets a different
pattern: trailing emojis specifically in buttons and CTA-like links —
‘Get started ✨’, ‘Try it 🚀’, ‘Generate now ✨’. The trailing position
means the emoji is decorating the CTA rather than replacing a section
icon, and it substitutes for good microcopy.

Threshold: 2+ (a single trailing emoji on a brand/fun site can be
intentional; 2+ across buttons means it's a pattern).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Same conservative emoji ranges as ai-slop/emoji-as-icon — kept in sync
# so leading-vs-trailing decisions use the same emoji definition.
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "]"
)

STRIP_INVISIBLES = re.compile(r"[\uFE0E\uFE0F\u200D\u200B]+")

# Extract button-like elements. We scope narrower than emoji-as-icon:
# only <button> and elements with role="button" or class hints that
# suggest a CTA (btn, cta). Links with class hints are included because
# many frameworks render CTAs as <a class="btn">.
BUTTON_TAG_RE = re.compile(
    r"<(button)\b([^>]*)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)
CTA_ANCHOR_RE = re.compile(
    r"<(a)\b([^>]*?\bclass=\"[^\"]*\b(?:btn|button|cta|primary|action)\b[^\"]*\"[^>]*)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)
ROLE_BUTTON_RE = re.compile(
    r"<(\w+)\b([^>]*?\brole=\"button\"[^>]*)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)


def inner_text(html_fragment: str) -> str:
    """Strip tags and collapse whitespace."""
    t = re.sub(r"<[^>]+>", " ", html_fragment)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_cta_labels(html: str) -> list[tuple[str, str]]:
    """Return (element_tag, visible_text) for buttons and CTA-like anchors."""
    out: list[tuple[str, str]] = []
    for m in BUTTON_TAG_RE.finditer(html):
        text = inner_text(m.group(3))
        if text:
            out.append(("button", text))
    for m in CTA_ANCHOR_RE.finditer(html):
        text = inner_text(m.group(3))
        if text:
            out.append(("a.cta", text))
    for m in ROLE_BUTTON_RE.finditer(html):
        text = inner_text(m.group(3))
        if text:
            out.append((f'{m.group(1)}[role=button]', text))
    return out


def trailing_emoji(text: str) -> str | None:
    """Return the trailing emoji character, or None.

    Definition of 'trailing': after stripping zero-width joiners and
    variation selectors from the end, the LAST character is an emoji AND
    the element has at least one non-emoji character before it (pure
    emoji-only buttons are intentional icon buttons, not slop).
    """
    stripped = STRIP_INVISIBLES.sub("", text)
    if not stripped:
        return None
    # Also strip trailing whitespace (inner_text already did, but guard)
    stripped = stripped.rstrip()
    if not stripped:
        return None
    last = stripped[-1]
    if not EMOJI_RE.match(last):
        return None
    # Require at least one non-emoji character in the label, otherwise
    # this is a pure icon button (not slop).
    rest = stripped[:-1]
    if not rest.strip():
        return None
    if not re.search(r"[A-Za-z0-9]", rest):
        return None
    return last


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    if not html:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No rendered.html captured.",
        )
        return

    labels = extract_cta_labels(html)
    matches = []
    for selector, text in labels:
        tail = trailing_emoji(text)
        if tail:
            matches.append({
                "type": f"{selector} trailing emoji",
                "emoji": tail,
                "matched_text": text[:120],
            })

    THRESHOLD = 2
    if len(matches) < THRESHOLD:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(labels)} button/CTA label(s); "
                f"{len(matches)} ended with a decorative emoji "
                f"(threshold: {THRESHOLD})."
            ),
            matches=matches,
        )
        return

    distinct = sorted({m["emoji"] for m in matches})
    details = (
        f"Found {len(matches)} CTA/button label(s) ending in a decorative "
        f"emoji ({', '.join(distinct[:6])}). Trailing button emojis are "
        "the LLM's way to make CTAs feel exciting without writing "
        "persuasive copy — the emoji substitutes for the missing hook."
    )
    suggestion = (
        "Replace trailing emojis with stronger CTA microcopy. Instead of "
        "‘Try it ✨’, pick a verb that says what happens: ‘Start for "
        "free’, ‘Open the editor’, ‘Install the CLI’, ‘Talk to sales’. "
        "Trust your visual system (color, type, proximity) to carry the "
        "excitement; the emoji is a substitute for writing that hook."
    )
    write_result(
        output_path, manifest,
        result="fail",
        details=details,
        matches=matches[:15],
        suggestion=suggestion,
    )


if __name__ == "__main__":
    run_detect(detect)
