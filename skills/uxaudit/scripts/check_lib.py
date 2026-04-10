"""Shared helpers for uxaudit detect.py scripts.

Each detect.py:
1. Loads its check.json manifest
2. Reads target/ artifacts (rendered.html, visible-text.txt, computed-styles.json, stylesheets.css)
3. Returns a result dict via write_result()
"""
import argparse
import json
import sys
from pathlib import Path


def parse_args():
    """Standard argparse for detect.py scripts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-dir", required=True, type=Path,
                        help="Directory with captured artifacts (rendered.html, etc.)")
    parser.add_argument("--evidence-dir", required=True, type=Path,
                        help="Directory to write evidence files into")
    parser.add_argument("--output", required=True, type=Path,
                        help="Path to write result.json")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="Path to this check's check.json")
    return parser.parse_args()


def load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text())


def load_target(target_dir: Path) -> dict:
    """Load all captured artifacts. Missing files become None."""
    out = {}
    for name in ["rendered.html", "visible-text.txt", "stylesheets.css"]:
        path = target_dir / name
        out[name] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None

    styles_path = target_dir / "computed-styles.json"
    if styles_path.exists():
        try:
            out["computed-styles.json"] = json.loads(styles_path.read_text())
        except json.JSONDecodeError:
            out["computed-styles.json"] = {}
    else:
        out["computed-styles.json"] = {}

    meta_path = target_dir / "meta.json"
    if meta_path.exists():
        try:
            out["meta"] = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            out["meta"] = {}
    else:
        out["meta"] = {}

    return out


def write_result(
    output_path: Path,
    manifest: dict,
    *,
    result: str,
    details: str = "",
    matches: list | None = None,
    suggestion: str = "",
    evidence_files: list | None = None,
) -> None:
    """Write a verdict-shaped result.json.

    result: 'pass' | 'fail' | 'skipped' | 'error'

    Writes ONLY the dynamic fields (`check_id`, `result`, `evidence`,
    `suggestion`). Catalog metadata (`name`, `band`, `subtype`, `method`,
    `severity`, `source`, `rationale`, `pass_criteria`) lives in check.json
    and is joined into the dashboard record by `aggregate.py` after the run
    finishes; `category` is derived from the first segment of `check_id` by
    that same join. Storing any of it here would duplicate the catalog and
    drift over iterations.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "check_id": manifest.get("id"),
        "result": result,
        "evidence": {
            "details": details,
            "matches": matches or [],
            "files": evidence_files or [],
        },
        "suggestion": suggestion,
    }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def run_detect(detect_fn):
    """Standard wrapper: parse args, load context, call detect_fn, exit cleanly."""
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest)
        target = load_target(args.target_dir)
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        detect_fn(manifest=manifest, target=target, evidence_dir=args.evidence_dir, output_path=args.output)
    except Exception as e:
        # Always produce a result file, even on error
        output_path = args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            manifest = load_manifest(args.manifest)
        except Exception:
            manifest = {}
        write_result(
            output_path,
            manifest,
            result="error",
            details=f"Detect script error: {type(e).__name__}: {e}",
        )
        print(f"[detect error] {e}", file=sys.stderr)
        sys.exit(0)  # don't fail the orchestrator
