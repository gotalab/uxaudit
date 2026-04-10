#!/usr/bin/env python3
"""Detect rote Tailwind 'X dark:Y' utility pairings sprinkled everywhere."""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Match a Tailwind utility followed by its dark: variant on the same class attribute.
# Examples:
#   bg-white dark:bg-zinc-900
#   bg-gray-50 dark:bg-gray-900
#   text-gray-900 dark:text-gray-100
PAIRING_RE = re.compile(
    r"(bg|text|border|ring|fill|stroke)-([\w]+(?:-\d{2,3})?)\s+dark:\1-([\w]+(?:-\d{2,3})?)"
)


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    if not html:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No rendered.html captured.",
        )
        return

    # Pull all class attribute strings then look for pairings inside them.
    class_attrs = re.findall(r'class=["\']([^"\']+)["\']', html)
    pairings: list[str] = []
    for attr in class_attrs:
        for m in PAIRING_RE.finditer(attr):
            kind, light, dark = m.group(1), m.group(2), m.group(3)
            pairings.append(f"{kind}-{light} dark:{kind}-{dark}")

    if len(pairings) < 6:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(class_attrs)} class attribute(s); found {len(pairings)} "
                "rote dark-mode pairing(s) (threshold: 6)."
            ),
        )
        return

    counts = Counter(pairings)
    top = counts.most_common(8)
    matches = [{"type": "rote-pairing", "matched_text": p, "count": c} for p, c in top]
    distinct = len(counts)
    details = (
        f"Found {len(pairings)} rote 'X dark:Y' Tailwind pairings ({distinct} distinct, top: "
        f"{top[0][0]} ×{top[0][1]}). When AI tools are asked to add dark mode, they sprinkle "
        "'dark:bg-zinc-900' and 'dark:text-gray-100' on every element with no design thinking — "
        "the result looks dark but feels like a recolored light theme."
    )
    suggestion = (
        "Dark mode should be designed, not sprinkled. Move colors to CSS custom properties "
        "(--surface, --surface-elevated, --text-primary, --text-muted) and switch them at the "
        "root via a [data-theme=\"dark\"] selector. This collapses dozens of rote pairings into "
        "a small set of semantic tokens AND lets you give dark mode its own elevation system, "
        "saturation curve, and contrast targets — instead of just inverting two colors per element."
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
