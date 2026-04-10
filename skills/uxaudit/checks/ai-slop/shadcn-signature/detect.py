#!/usr/bin/env python3
"""Detect unmodified shadcn/ui component class signatures."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Canonical shadcn/ui base-class signatures, lifted verbatim from ui.shadcn.com.
# Each entry: (label, substring to search for in class attributes).
# We look for substrings, not full equality, because real components compose
# the base with variant classes (cn(buttonVariants(...), ...)).
SHADCN_SIGNATURES = [
    (
        "shadcn Button (base)",
        "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium",
    ),
    (
        "shadcn Card (root)",
        "rounded-lg border bg-card text-card-foreground shadow-sm",
    ),
    (
        "shadcn Card (alt)",
        "rounded-xl border bg-card text-card-foreground shadow",
    ),
    (
        "shadcn CardHeader",
        "flex flex-col space-y-1.5 p-6",
    ),
    (
        "shadcn CardTitle",
        "text-2xl font-semibold leading-none tracking-tight",
    ),
    (
        "shadcn Input",
        "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2",
    ),
    (
        "shadcn Badge (base)",
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold",
    ),
    (
        "shadcn Dialog overlay",
        "fixed inset-0 z-50 bg-black/80",
    ),
]


def find_class_attrs(html: str) -> list[str]:
    """Return every class attribute value found in the HTML."""
    return re.findall(r'class=["\']([^"\']+)["\']', html)


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    if not html:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No rendered.html captured; cannot scan for shadcn signatures.",
        )
        return

    class_attrs = find_class_attrs(html)
    matches = []
    for label, signature in SHADCN_SIGNATURES:
        for attr in class_attrs:
            if signature in attr:
                matches.append({
                    "type": "shadcn-signature",
                    "component": label,
                    "matched_text": signature,
                })
                break  # one hit per signature is enough

    # Threshold: 2+ distinct signatures = clear evidence the page is composed
    # of unmodified shadcn primitives.
    if len(matches) < 2:
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Scanned {len(class_attrs)} class attribute(s); found "
                f"{len(matches)} shadcn signature(s) (threshold: 2)."
            ),
            matches=matches,
        )
    else:
        details = (
            f"Found {len(matches)} unmodified shadcn/ui component signature(s) in the rendered HTML. "
            "These exact class strings are emitted verbatim by v0, Bolt, Lovable, and Claude when "
            "asked to generate UI — they're a strong fingerprint that the components were generated "
            "rather than designed."
        )
        suggestion = (
            "shadcn/ui is great as a starting point — the slop signal is using it WITHOUT any visual "
            "customization. Either: (a) extend the base classes with brand-specific variants via the "
            "`cn(buttonVariants({...}), ...)` pattern, (b) override the base class strings in your own "
            "wrapper components, or (c) replace shadcn with a thin custom component that expresses your "
            "design language. The goal isn't to avoid shadcn — it's to make the UI look like YOUR product."
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
