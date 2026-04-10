#!/usr/bin/env python3
"""Detect the ✨ + AI-keyword combo — a high-signal AI-slop fingerprint.

Unlike emoji-as-icon (which checks a threshold of 3+ leading emojis in
section headers), this check fires at count 1 because the sparkle-plus-
AI-keyword combination is so specific to LLM-generated UI that a single
occurrence is already evidence. Real products with AI features use brand
marks, custom icons, or icon-system glyphs — not ✨.

Scans visible-text.txt for U+2728 (✨) within a short proximity window of
any AI-related keyword, case-insensitive.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

SPARKLE = "\u2728"  # ✨

# Keywords that co-locate with ✨ in slop-generated AI UIs. Case-insensitive
# whole-word matches (word boundary on both sides). The list deliberately
# stops short — adding too many keywords (e.g. "new", "fast") causes false
# positives; these are the ones that genuinely signal "AI feature".
AI_KEYWORDS = [
    r"AI",
    r"A\.I\.",
    r"artificial intelligence",
    r"magic",
    r"magical",
    r"smart",
    r"generate",
    r"generated",
    r"generator",
    r"generating",
    r"assistant",
    r"powered",
    r"agentic",
    r"autocomplete",
    r"intelligence",
    r"copilot",
]
# Compile as one alternation with word boundaries.
AI_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(AI_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Proximity: the sparkle and the keyword must be within PROXIMITY characters
# of each other. 40 covers "✨ AI-powered editor" and "Generate ✨" without
# pulling in distant unrelated matches.
PROXIMITY = 40


def find_combos(text: str) -> list[dict]:
    """Return a list of {sparkle_pos, keyword, keyword_pos, snippet} hits.

    Each hit is a (sparkle, keyword) pair whose character positions are
    within PROXIMITY of one another. A single sparkle can match multiple
    keywords; each pair is reported once.
    """
    hits: list[dict] = []
    sparkle_positions = [i for i, ch in enumerate(text) if ch == SPARKLE]
    if not sparkle_positions:
        return hits

    for m in AI_KEYWORD_RE.finditer(text):
        kw_start = m.start()
        kw_end = m.end()
        for sp_pos in sparkle_positions:
            # Distance is from the nearest edge of the keyword span.
            if sp_pos < kw_start:
                distance = kw_start - sp_pos
            elif sp_pos >= kw_end:
                distance = sp_pos - (kw_end - 1)
            else:
                distance = 0  # sparkle is inside the keyword span (shouldn't happen)
            if distance <= PROXIMITY:
                # Build a short snippet around the match for evidence.
                ctx_start = max(0, min(sp_pos, kw_start) - 15)
                ctx_end = min(len(text), max(sp_pos, kw_end) + 15)
                snippet = text[ctx_start:ctx_end].replace("\n", " ").strip()
                hits.append({
                    "keyword": m.group(0),
                    "distance": distance,
                    "snippet": snippet,
                })
    return hits


def detect(*, manifest, target, evidence_dir, output_path):
    text = target.get("visible-text.txt")
    if not text:
        # Fall back to rendered.html text extraction if visible-text.txt
        # is missing, so this check still runs even when capture.mjs
        # skipped the plain-text side-channel.
        html = target.get("rendered.html")
        if html:
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
        else:
            write_result(
                output_path, manifest,
                result="skipped",
                details="No visible-text.txt or rendered.html captured.",
            )
            return

    hits = find_combos(text)

    if not hits:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(text)} chars of visible text; no ✨ within "
                f"{PROXIMITY} chars of any AI-related keyword."
            ),
            matches=[],
        )
        return

    # Deduplicate snippets — the same sparkle near multiple keywords can
    # produce repeated evidence; keep it compact for the dashboard.
    seen = set()
    unique_hits = []
    for h in hits:
        key = h["snippet"]
        if key not in seen:
            seen.add(key)
            unique_hits.append(h)

    distinct_keywords = sorted({h["keyword"].lower() for h in unique_hits})
    details = (
        f"Found {len(unique_hits)} ✨ + AI-keyword co-location(s) "
        f"(keywords: {', '.join(distinct_keywords[:6])}). "
        "The sparkle+AI combo is a near-universal fingerprint of LLM-"
        "generated UIs — Vercel v0, Bolt, Cursor, Copilot all ship it. "
        "Using it signals that the product reached for the default token "
        "for ‘AI feature’ instead of committing to a brand mark."
    )
    suggestion = (
        "Remove the ✨ and commit to a deliberate signal for AI features: a "
        "brand mark, a custom icon (lucide ‘wand’, ‘zap’, ‘cpu’), or — "
        "strongest — no icon at all, letting the feature name carry the "
        "weight. If the sparkle is load-bearing in your brand (rare), "
        "ignore this check via .uxauditignore; otherwise removing it is a "
        "one-line fix that meaningfully raises perceived craft."
    )
    write_result(
        output_path, manifest,
        result="fail",
        details=details,
        matches=unique_hits[:15],
        suggestion=suggestion,
    )


if __name__ == "__main__":
    run_detect(detect)
