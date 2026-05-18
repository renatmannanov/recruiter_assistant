"""Dump screening results to a JSON file (for debugging / further analysis)."""

import json
from pathlib import Path


def dump_results(results: list[dict], output_path: str) -> None:
    """Write results list as pretty-printed JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
