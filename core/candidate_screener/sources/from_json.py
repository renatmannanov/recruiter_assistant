"""Load Apify-style profile JSON from a local file."""

import json
from pathlib import Path


def load_profiles(path: str) -> list[dict]:
    """Read a JSON file containing a list of Apify profile objects."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
