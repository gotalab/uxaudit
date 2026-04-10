#!/usr/bin/env python3
"""Detect decorative emoji-as-icon used in headings, buttons, and section labels."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Conservative emoji ranges that cover the LLM-favored decorative set:
# - Misc symbols & pictographs (1F300-1F5FF): 📊 📈 📁 📌 ...
# - Emoticons (1F600-1F64F)
# - Transport & map symbols (1F680-1F6FF): 🚀 ⏱ ...
# - Misc symbols (2600-26FF): ☀ ⚡ ⭐ ...
# - Dingbats (2700-27BF): ✅ ✨ ✏ ✔ ...
# - Supplemental symbols & pictographs (1F900-1F9FF): 🤖 🧠 💎 ...
# - Symbols & pictographs extended-A (1FA70-1FAFF)
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

# We scan h1-h4, buttons, and a tags for leading emojis. Variation selectors and
# zero-width joiners are stripped before testing for "starts with emoji."
STRIP_INVISIBLES = re.compile(r"[\uFE0E\uFE0F\u200D\u200B\s]+")


def extract_labels(html: str) -> list[tuple[str, str]]:
    """Return (selector, text) for h1-h4, button, and link labels."""
    labels = []
    for tag in ["h1", "h2", "h3", "h4", "button", "a"]:
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE):
            inner = m.group(1)
            text = re.sub(r"<[^>]+>", " ", inner)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                labels.append((tag, text))
    return labels


def starts_with_emoji(text: str) -> str | None:
    """Return the leading emoji character if the text starts with one, else None."""
    stripped = STRIP_INVISIBLES.sub("", text)
    if not stripped:
        return None
    first = stripped[0]
    if EMOJI_RE.match(first):
        return first
    return None


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    if not html:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No rendered.html captured.",
        )
        return

    labels = extract_labels(html)
    matches = []
    for selector, text in labels:
        emoji = starts_with_emoji(text)
        if emoji:
            matches.append({
                "type": f"<{selector}> leading emoji",
                "emoji": emoji,
                "matched_text": text[:120],
            })

    # Threshold: 3+ section emojis = pattern, not accident
    if len(matches) < 3:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(labels)} heading/button label(s); found {len(matches)} emoji-prefixed "
                "(threshold: 3)."
            ),
            matches=matches,
        )
        return

    distinct_emojis = sorted({m["emoji"] for m in matches})
    details = (
        f"Found {len(matches)} heading/button label(s) starting with a decorative emoji "
        f"({', '.join(distinct_emojis[:8])}). When LLMs are asked to generate landing-page "
        "sections without art direction, they prefix every section with an emoji because it's "
        "the highest-probability way to add visual interest with text."
    )
    suggestion = (
        "Replace section emojis with real icons (lucide-react, heroicons, or custom SVG) to "
        "signal that an icon system was chosen deliberately. If the product genuinely uses "
        "emojis as part of its design language (e.g., reaction picker, playlist categories), "
        "ignore this check via .uxauditignore — but for landing-page section headers, an "
        "icon set is the right call."
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
