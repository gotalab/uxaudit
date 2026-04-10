#!/usr/bin/env python3
"""Detect the 'Get Started' + 'Learn More' hero button cliché pair."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Two label families. The check fires when BOTH families have a hit on the
# same page, because either phrase alone is plausible — it's the canonical
# pair that signals the LLM default hero.
PRIMARY_PATTERNS = [
    r"\bget\s+started(\s+(free|now|today))?\b",
    r"\bstart\s+(your\s+)?free(\s+trial)?\b",
    r"\bstart\s+for\s+free\b",
    r"\btry\s+it\s+free\b",
    r"\bsign\s+up\s+free\b",
]
SECONDARY_PATTERNS = [
    r"\blearn\s+more\b",
    r"\blearn\s+how\s+it\s+works\b",
    r"\bsee\s+how\s+it\s+works\b",
    r"\bread\s+the\s+docs\b",  # only when paired with primary
]


def extract_clickables(html: str) -> list[tuple[str, str]]:
    """Return (tag, text) for every button/link/role=button element."""
    clickables = []
    for tag in ["button", "a"]:
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE):
            inner = m.group(1)
            text = re.sub(r"<[^>]+>", " ", inner)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                clickables.append((tag, text))
    return clickables


def first_match(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return pat
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

    clickables = extract_clickables(html)
    primary_hits = []
    secondary_hits = []
    for tag, text in clickables:
        if first_match(PRIMARY_PATTERNS, text):
            primary_hits.append({"type": f"<{tag}> primary CTA", "matched_text": text[:120]})
        if first_match(SECONDARY_PATTERNS, text):
            secondary_hits.append({"type": f"<{tag}> secondary CTA", "matched_text": text[:120]})

    if not (primary_hits and secondary_hits):
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(clickables)} clickable(s); "
                f"{len(primary_hits)} primary cliché(s), {len(secondary_hits)} secondary cliché(s). "
                "Both families needed to fail."
            ),
        )
        return

    matches = primary_hits[:5] + secondary_hits[:5]
    details = (
        f"Found the canonical AI-generated hero pair: {len(primary_hits)} 'Get Started'-style "
        f"CTA(s) AND {len(secondary_hits)} 'Learn More'-style secondary action(s). This exact "
        "pair appears verbatim on tens of thousands of v0/Bolt/Lovable/Claude-generated landing "
        "pages because it's the highest-probability output for 'design a hero'."
    )
    suggestion = (
        "Replace both with concrete, product-specific actions. Strong CTAs name what happens "
        "next: 'Listen to a track', 'Try the live demo', 'See pricing', 'Read the changelog', "
        "'Book a table'. The best hero CTA tells the visitor exactly what they'll experience "
        "after clicking — 'Get Started' commits to nothing."
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
