#!/usr/bin/env python3
"""Detect hotlinks to undraw / storyset / freepik / similar stock illustration hosts."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Hosts whose presence in img src / background-image url() is a slop tell.
# We DELIBERATELY exclude unsplash + pexels + pixabay because real products
# legitimately use them for photography. The flagged sources are specifically
# the flat-figure illustration libraries that AI tools fall back on.
SLOP_HOSTS = [
    ("undraw.co", "unDraw"),
    ("storyset.com", "Storyset"),
    ("freepik.com", "Freepik"),
    ("manypixels.co", "ManyPixels"),
    ("popsy.co", "Popsy"),
    ("drawkit.com", "DrawKit"),
    ("icons8.com", "Icons8"),
    ("absurd.design", "Absurd Design"),
    ("opendoodles.com", "Open Doodles"),
    ("humaaans.com", "Humaaans"),
    ("blush.design", "Blush"),
]


def detect(*, manifest, target, evidence_dir, output_path):
    html = target.get("rendered.html") or ""
    css = target.get("stylesheets.css") or ""

    if not html and not css:
        write_result(
            output_path, manifest,
            result="skipped",
            details="No rendered.html or stylesheets.css captured.",
        )
        return

    matches = []
    haystack_pairs = [("html", html), ("css", css)]
    for source, text in haystack_pairs:
        if not text:
            continue
        # Find every src= and url(...) reference; check the URL substring.
        candidates = []
        candidates += re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', text, re.IGNORECASE)
        candidates += re.findall(r'\bsrcset=["\']([^"\']+)["\']', text, re.IGNORECASE)
        candidates += re.findall(r"url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", text, re.IGNORECASE)
        for raw in candidates:
            for url in raw.split(","):
                url = url.strip().split(" ")[0]
                if not url:
                    continue
                low = url.lower()
                for host, label in SLOP_HOSTS:
                    if host in low:
                        matches.append({
                            "type": f"{source}-asset",
                            "host": label,
                            "matched_text": url[:160],
                        })
                        break

    # Dedupe by URL
    seen = set()
    unique = []
    for m in matches:
        if m["matched_text"] not in seen:
            seen.add(m["matched_text"])
            unique.append(m)
    matches = unique

    if not matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No stock-illustration hotlinks detected.",
        )
        return

    hosts = sorted({m["host"] for m in matches})
    details = (
        f"Found {len(matches)} hotlink(s) to stock illustration host(s): {', '.join(hosts)}. "
        "These libraries are the visual Lorem ipsum of AI-generated UI — pastel flat figures "
        "used by tens of thousands of landing pages because they're free and Tailwind-friendly."
    )
    suggestion = (
        "Pick ONE of: (a) commission/draw simple custom illustration in the product's voice, "
        "(b) use meaningful product screenshots that show what the app actually does, or "
        "(c) drop the imagery entirely and lean on typography. Removing stock figures usually "
        "improves the page — they distract from the product without adding meaning."
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
