#!/usr/bin/env python3
"""Detect when a page uses only canonical Tailwind colors with no custom palette."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Canonical Tailwind v3 default palette hex values (lowercase, no leading #).
# Source: tailwindcss.com/docs/customizing-colors. We don't need ALL of them —
# the most-used 500/700/900 weights of the gray-family + a few accents is enough
# to recognize "the default Tailwind look."
TAILWIND_HEX = {
    # slate
    "f8fafc", "f1f5f9", "e2e8f0", "cbd5e1", "94a3b8", "64748b", "475569", "334155", "1e293b", "0f172a", "020617",
    # gray
    "f9fafb", "f3f4f6", "e5e7eb", "d1d5db", "9ca3af", "6b7280", "4b5563", "374151", "1f2937", "111827", "030712",
    # zinc
    "fafafa", "f4f4f5", "e4e4e7", "d4d4d8", "a1a1aa", "71717a", "52525b", "3f3f46", "27272a", "18181b", "09090b",
    # neutral
    "f5f5f5", "e5e5e5", "d4d4d4", "a3a3a3", "737373", "525252", "404040", "262626", "171717", "0a0a0a",
    # stone
    "fafaf9", "f5f5f4", "e7e5e4", "d6d3d1", "a8a29e", "78716c", "57534e", "44403c", "292524", "1c1917", "0c0a09",
    # red
    "fef2f2", "fee2e2", "fecaca", "fca5a5", "f87171", "ef4444", "dc2626", "b91c1c", "991b1b", "7f1d1d", "450a0a",
    # orange
    "fff7ed", "ffedd5", "fed7aa", "fdba74", "fb923c", "f97316", "ea580c", "c2410c", "9a3412", "7c2d12",
    # amber
    "fffbeb", "fef3c7", "fde68a", "fcd34d", "fbbf24", "f59e0b", "d97706", "b45309", "92400e", "78350f",
    # yellow
    "fefce8", "fef9c3", "fef08a", "fde047", "facc15", "eab308", "ca8a04", "a16207", "854d0e", "713f12",
    # lime
    "f7fee7", "ecfccb", "d9f99d", "bef264", "a3e635", "84cc16", "65a30d", "4d7c0f", "365314", "1a2e05",
    # green
    "f0fdf4", "dcfce7", "bbf7d0", "86efac", "4ade80", "22c55e", "16a34a", "15803d", "166534", "14532d",
    # emerald
    "ecfdf5", "d1fae5", "a7f3d0", "6ee7b7", "34d399", "10b981", "059669", "047857", "065f46", "064e3b",
    # teal
    "f0fdfa", "ccfbf1", "99f6e4", "5eead4", "2dd4bf", "14b8a6", "0d9488", "0f766e", "115e59", "134e4a",
    # cyan
    "ecfeff", "cffafe", "a5f3fc", "67e8f9", "22d3ee", "06b6d4", "0891b2", "0e7490", "155e75", "164e63",
    # sky
    "f0f9ff", "e0f2fe", "bae6fd", "7dd3fc", "38bdf8", "0ea5e9", "0284c7", "0369a1", "075985", "0c4a6e",
    # blue
    "eff6ff", "dbeafe", "bfdbfe", "93c5fd", "60a5fa", "3b82f6", "2563eb", "1d4ed8", "1e40af", "1e3a8a", "172554",
    # indigo
    "eef2ff", "e0e7ff", "c7d2fe", "a5b4fc", "818cf8", "6366f1", "4f46e5", "4338ca", "3730a3", "312e81",
    # violet
    "f5f3ff", "ede9fe", "ddd6fe", "c4b5fd", "a78bfa", "8b5cf6", "7c3aed", "6d28d9", "5b21b6", "4c1d95",
    # purple
    "faf5ff", "f3e8ff", "e9d5ff", "d8b4fe", "c084fc", "a855f7", "9333ea", "7e22ce", "6b21a8", "581c87",
    # fuchsia
    "fdf4ff", "fae8ff", "f5d0fe", "f0abfc", "e879f9", "d946ef", "c026d3", "a21caf", "86198f", "701a75",
    # pink
    "fdf2f8", "fce7f3", "fbcfe8", "f9a8d4", "f472b6", "ec4899", "db2777", "be185d", "9d174d", "831843",
    # rose
    "fff1f2", "ffe4e6", "fecdd3", "fda4af", "fb7185", "f43f5e", "e11d48", "be123c", "9f1239", "881337",
    # base
    "ffffff", "000000",
}

HEX_RE = re.compile(r"#([0-9a-fA-F]{6})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"{r:02x}{g:02x}{b:02x}"


def collect_colors(css: str) -> set[str]:
    """Return the set of unique 6-digit lowercase hexes referenced in the CSS,
    converting any rgb()/rgba() encountered to hex first."""
    colors: set[str] = set()
    for m in HEX_RE.finditer(css):
        colors.add(m.group(1).lower())
    for m in RGB_RE.finditer(css):
        try:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                colors.add(rgb_to_hex(r, g, b))
        except ValueError:
            continue
    return colors


def detect(*, manifest, target, evidence_dir, output_path):
    css = target.get("stylesheets.css") or ""
    if not css:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No stylesheets.css captured; cannot scan palette.",
        )
        return

    colors = collect_colors(css)
    if not colors:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No colors found in captured CSS.",
        )
        return

    canonical = {c for c in colors if c in TAILWIND_HEX}
    custom = colors - canonical
    canonical_ratio = len(canonical) / len(colors)

    # Pass conditions:
    # - At least one custom color exists, OR
    # - The canonical ratio is below 0.85 (the page has a deliberate palette
    #   that doesn't lean entirely on Tailwind defaults).
    if custom or canonical_ratio < 0.85:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Found {len(colors)} unique color(s); {len(canonical)} canonical Tailwind, "
                f"{len(custom)} custom (ratio: {canonical_ratio:.0%}). At least one brand color exists."
            ),
            matches=[{"type": "custom-color", "matched_text": f"#{c}"} for c in sorted(custom)[:10]],
        )
        return

    details = (
        f"Found {len(colors)} unique color(s), all canonical Tailwind defaults "
        f"({canonical_ratio:.0%} canonical ratio). Zero custom brand colors detected — "
        "the project never extended tailwind.config theme.extend.colors. This is the "
        "fingerprint of an AI-generated UI that skipped the color decision entirely."
    )
    suggestion = (
        "Pick ONE accent color that means something for the product (the brand color, the "
        "category color, the founder's favorite — anything intentional) and add it to "
        "tailwind.config.ts under theme.extend.colors. Then use it for primary CTAs, "
        "active states, and one accent surface. The point isn't to be colorful — it's to "
        "have made a color decision."
    )
    sample_canonical = sorted(canonical)[:8]
    write_result(
        output_path, manifest,
        result="fail",
        details=details,
        matches=[{"type": "canonical-tailwind-color", "matched_text": f"#{c}"} for c in sample_canonical],
        suggestion=suggestion,
    )


if __name__ == "__main__":
    run_detect(detect)
