#!/usr/bin/env python3
"""Detect vague button labels (Submit / OK / Click here / etc.)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Vague labels that say nothing about what the action does.
# Cancel is intentionally NOT here — Cancel as a secondary action is fine.
VAGUE_LABELS = {
    "submit", "submit form", "ok", "okay", "click here", "click", "button",
    "go", "send", "done", "next", "back", "yes", "no", "confirm", "save",
    "閉じる", "送信", "決定",
}

# Phrases that don't quite count as the canonical vague labels but are still bad
VAGUE_PHRASES = [
    "click to continue",
    "click for more",
    "more info",
    "learn more",
    "read more",
    "find out more",
    "get started",
]

BUTTON_RE = re.compile(
    r"<(button|a|input)([^>]*)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)
INPUT_BUTTON_RE = re.compile(
    r"<input[^>]*type=['\"]?(submit|button)['\"]?[^>]*>",
    re.IGNORECASE,
)


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def get_attr(attrs: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]*)['\"]", attrs, re.IGNORECASE)
    return m.group(1) if m else ""


# Tailwind / utility-class signals that an anchor is visually a button:
# a background fill OR a border, combined with rounded corners and padding,
# inside an inline-flex / inline-block layout. We require at least 3 signal
# groups to fire to avoid false positives on plain rounded text links.
_BG_RE      = re.compile(r"\bbg-[a-z0-9-\[\]_/.,#%()]+", re.IGNORECASE)
_BORDER_RE  = re.compile(r"\bborder(?:-[a-z0-9-\[\]_/.,#%()]+)?\b", re.IGNORECASE)
_ROUNDED_RE = re.compile(r"\brounded(?:-[a-z0-9-\[\]_/.,#%()]+)?\b", re.IGNORECASE)
_PADDING_RE = re.compile(r"\bp[xytrbl]?-[a-z0-9-\[\]_/.,#%()]+", re.IGNORECASE)
_INLINE_RE  = re.compile(r"\binline-(flex|block)\b", re.IGNORECASE)


def _has_button_shaped_classes(cls: str) -> bool:
    """Heuristic: does this class string describe a Tailwind/utility button?

    Returns True when the class has at least 3 of:
      - bg-* (background fill) OR border (outline)
      - rounded* (corner radius)
      - p*-N (padding)
      - inline-flex or inline-block (button-like display)
    """
    if not cls:
        return False
    score = 0
    if _BG_RE.search(cls) or _BORDER_RE.search(cls):
        score += 1
    if _ROUNDED_RE.search(cls):
        score += 1
    if _PADDING_RE.search(cls):
        score += 1
    if _INLINE_RE.search(cls):
        score += 1
    return score >= 3


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    if not html:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No HTML captured.",
        )
        return

    # Collect button-like elements: <button>, <a> with role="button" or class hint, <input type="submit/button">
    buttons = []  # list of (label, source_tag)

    for m in BUTTON_RE.finditer(html):
        tag = m.group(1).lower()
        attrs = m.group(2)
        inner = strip_tags(m.group(3))

        if tag == "button":
            label = inner or get_attr(attrs, "aria-label")
            if label:
                buttons.append((label, "<button>"))
        elif tag == "a":
            # Count anchors that look like buttons. Three signal classes:
            # 1. Explicit role/class (legacy heuristic)
            # 2. Tailwind / utility-class styled CTAs — bg-* OR border + rounded
            #    + padding combinations are universally button-shaped even
            #    without a 'btn' substring in the class string. Most modern
            #    Next.js / Tailwind apps use this pattern.
            # 3. inline-flex/inline-block + padding + rounded — typical for
            #    primary nav CTAs.
            role = get_attr(attrs, "role").lower()
            cls = get_attr(attrs, "class").lower()
            looks_button = (
                role == "button"
                or "btn" in cls
                or "button" in cls
                or _has_button_shaped_classes(cls)
            )
            if looks_button:
                label = inner or get_attr(attrs, "aria-label")
                if label:
                    buttons.append((label, "<a role=button>"))

    for m in INPUT_BUTTON_RE.finditer(html):
        attrs = m.group(0)
        value = get_attr(attrs, "value") or get_attr(attrs, "aria-label")
        if value:
            buttons.append((value, "<input>"))

    if not buttons:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No button elements found in HTML.",
        )
        return

    # Score each button
    vague_hits = []
    for label, source in buttons:
        normalized = label.strip().rstrip(".!?").lower()
        if normalized in VAGUE_LABELS:
            vague_hits.append({
                "type": source,
                "matched_text": label[:80],
                "reason": "exact-vague",
            })
        else:
            for phrase in VAGUE_PHRASES:
                if normalized == phrase or normalized.endswith(phrase):
                    vague_hits.append({
                        "type": source,
                        "matched_text": label[:80],
                        "reason": f"phrase: {phrase}",
                    })
                    break

    total = len(buttons)
    vague_count = len(vague_hits)
    ratio = vague_count / total

    # Pass if fewer than 3 vague AND less than 30% of buttons
    if vague_count < 3 and ratio < 0.3:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"{total} button(s) inspected, {vague_count} with vague labels "
                f"({ratio:.0%}). Within tolerance."
            ),
            matches=vague_hits[:10],
        )
    else:
        details = (
            f"Found {vague_count}/{total} buttons ({ratio:.0%}) with vague labels "
            "(Submit, OK, Click, Learn more, etc.). Krug's Law #1: button labels should be "
            "self-evident — users should not have to guess what an action does."
        )
        suggestion = (
            "Replace vague labels with verb + object: 'Save changes', 'Send invoice', "
            "'Add to cart', 'Delete project'. Even 'Submit' becomes 'Submit application' or "
            "'Sign up'. The user should be able to predict what happens before clicking."
        )
        write_result(
            output_path, manifest,
            result="fail",
            details=details,
            matches=vague_hits[:15],
            suggestion=suggestion,
        )


if __name__ == "__main__":
    run_detect(detect)
