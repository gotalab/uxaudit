#!/usr/bin/env python3
"""Detect outline:none / outline:0 without :focus replacement."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_lib import run_detect, write_result  # noqa: E402

# Match `outline: none` or `outline: 0` declarations
OUTLINE_REMOVED = re.compile(
    r"outline\s*:\s*(none|0|0px)\s*[;}]",
    re.IGNORECASE,
)

# Match :focus, :focus-visible, :focus-within rules
FOCUS_RULE = re.compile(
    r":focus(?:-visible|-within)?\b",
    re.IGNORECASE,
)


def detect(*, manifest, target, evidence_dir, output_path):
    css = target.get("stylesheets.css") or ""
    if not css.strip():
        write_result(
            output_path, manifest,
            result="skipped",
            details="No CSS captured.",
        )
        return

    # Find all outline-removing declarations
    outline_removed_matches = list(OUTLINE_REMOVED.finditer(css))
    if not outline_removed_matches:
        write_result(
            output_path, manifest,
            result="pass",
            details="No `outline: none` or `outline: 0` declarations found in CSS.",
        )
        return

    # Has outline removal — check if :focus / :focus-visible / :focus-within
    # rules exist anywhere in CSS as a baseline replacement
    focus_rules = list(FOCUS_RULE.finditer(css))

    # Stronger check: are the :focus rules providing a visible indicator?
    # We look at the rule body for box-shadow, border, outline (with non-none value)
    focus_with_indicator = 0
    for fr in focus_rules:
        # Find the next `{` and matching `}` after this :focus selector
        start = css.find("{", fr.end())
        if start == -1:
            continue
        depth = 1
        i = start + 1
        while i < len(css) and depth > 0:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        body = css[start + 1:i - 1]
        # Check if body contains a visible-focus declaration
        if re.search(r"box-shadow\s*:\s*(?!none)", body, re.IGNORECASE) or \
           re.search(r"outline\s*:\s*(?!none|0)", body, re.IGNORECASE) or \
           re.search(r"border(-\w+)?\s*:[^;]*\d", body, re.IGNORECASE) or \
           re.search(r"background(-color)?\s*:", body, re.IGNORECASE):
            focus_with_indicator += 1

    # Heuristic: if there are roughly as many :focus rules with visible indicators
    # as outline-removed declarations, the developer is doing it intentionally.
    matches = []
    for m in outline_removed_matches[:10]:
        # Try to identify the selector by walking back to the previous `{`
        start = css.rfind("{", 0, m.start())
        if start == -1:
            selector_start = 0
        else:
            # Walk back from `{` to the previous `}` (or 0)
            prev_close = css.rfind("}", 0, start)
            selector_start = prev_close + 1 if prev_close != -1 else 0
        selector = css[selector_start:start].strip()[:80]
        matches.append({
            "type": "outline-removed",
            "matched_text": f"{selector} {{ outline: none ... }}",
        })

    if focus_with_indicator >= len(outline_removed_matches):
        write_result(
            output_path, manifest,
            result="pass",
            details=(
                f"Found {len(outline_removed_matches)} outline-removed declaration(s) "
                f"AND {focus_with_indicator} :focus rule(s) with visible indicators "
                "(box-shadow, border, background, or non-none outline). Developer is providing replacements."
            ),
        )
    else:
        details = (
            f"Found {len(outline_removed_matches)} `outline: none` declaration(s) "
            f"but only {focus_with_indicator} :focus rule(s) with a visible-indicator "
            "replacement (box-shadow, non-none outline, etc.). Keyboard users will lose track of focus."
        )
        suggestion = (
            "For every `outline: none`, add a corresponding `:focus-visible` rule with a "
            "visible indicator: e.g., `button:focus-visible { box-shadow: 0 0 0 2px var(--accent); }` "
            "or `outline: 2px solid var(--accent); outline-offset: 2px;`. WCAG 2.4.7 (AA) requires "
            "a visible focus indicator on every keyboard-operable element."
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
