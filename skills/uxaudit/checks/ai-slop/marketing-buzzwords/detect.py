#!/usr/bin/env python3
"""Detect high density of marketing buzzwords in visible text."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Curated list of marketing buzzwords. Each entry is the lowercase stem.
# Sources: standard 'corporate jargon' lists, "deathless platitudes" critiques.
BUZZWORDS = {
    # The "we are amazing" set
    "powerful", "intuitive", "seamless", "robust", "elegant", "beautiful",
    "delightful", "amazing", "incredible", "stunning", "gorgeous",
    # The "tech that doesn't exist" set
    "cutting-edge", "cutting edge", "next-generation", "next generation",
    "next-gen", "state-of-the-art", "state of the art", "world-class",
    "best-in-class", "industry-leading", "groundbreaking", "revolutionary",
    "game-changing", "game changing", "disruptive", "innovative",
    # The "verbs that mean nothing" set
    "transform", "empower", "leverage", "unleash", "unlock", "supercharge",
    "streamline", "optimize", "elevate", "accelerate", "harness",
    # The "MBA word salad" set
    "synergy", "synergies", "holistic", "paradigm", "ecosystem",
    "scalable", "actionable", "frictionless",
    # AI-era buzzwords
    "ai-powered", "ai powered", "ai-driven", "ml-powered", "smart",
    "intelligent",
}

# Multi-word buzzwords need word-boundary matching, so we keep them separate.
MULTI_WORD = [bw for bw in BUZZWORDS if " " in bw or "-" in bw]
SINGLE_WORD = [bw for bw in BUZZWORDS if " " not in bw and "-" not in bw]


def detect(*, manifest, target, evidence_dir, output_path):
    visible = target.get("visible-text.txt") or ""
    if not visible.strip():
        write_result(
            output_path, manifest,
            result="skipped",
            details="No visible text captured.",
        )
        return

    text_lower = visible.lower()
    # Count words: simple whitespace tokens, excluding pure punctuation
    word_tokens = re.findall(r"\b[\w']+\b", text_lower)
    total_words = len(word_tokens)
    if total_words == 0:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No words in visible text.",
        )
        return

    word_set = set(word_tokens)
    found = {}

    # Single-word buzzwords (use set for speed)
    for bw in SINGLE_WORD:
        if bw in word_set:
            count = sum(1 for w in word_tokens if w == bw)
            found[bw] = count

    # Multi-word: substring search with word boundaries
    for bw in MULTI_WORD:
        # Use a simple regex: \b...\b with hyphens/spaces preserved
        escaped = re.escape(bw)
        count = len(re.findall(rf"\b{escaped}\b", text_lower))
        if count > 0:
            found[bw] = count

    total_hits = sum(found.values())
    density = total_hits / total_words
    distinct = len(found)

    matches = [
        {"type": "buzzword", "matched_text": bw, "count": count}
        for bw, count in sorted(found.items(), key=lambda kv: -kv[1])
    ]

    # Pass: density < 2% AND distinct < 5
    if density < 0.02 and distinct < 5:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Buzzword density: {total_hits}/{total_words} words = {density:.2%}. "
                f"{distinct} distinct buzzwords."
            ),
            matches=matches[:15],
        )
    else:
        details = (
            f"Buzzword density: {total_hits}/{total_words} words = {density:.2%} "
            f"({distinct} distinct buzzwords). "
            "Krug's Law #3: 'Get rid of half the words on each page, then get rid of half of what's left.'"
        )
        suggestion = (
            "Replace each buzzword with the concrete claim it's trying to make. "
            "Instead of 'powerful AI-driven analytics', say 'shows you which 5 customers are about to churn'. "
            "If a sentence still works after deleting the buzzword, it never needed the word."
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
