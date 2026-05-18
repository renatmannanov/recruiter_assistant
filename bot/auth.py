"""Whitelist-based authorization.

v1 auth is a flat list of allowed telegram_user_id in config/whitelist.json
(gitignored — real IDs never go to git). The file is read once and cached;
the bot restarts to pick up changes.
"""

import json
import os
from pathlib import Path

_DEFAULT_WHITELIST = "./config/whitelist.json"

# Loaded lazily on first use, then cached. {telegram_user_id: {...config}}.
_whitelist: dict[int, dict] | None = None


def _whitelist_path() -> Path:
    return Path(os.environ.get("WHITELIST_PATH", _DEFAULT_WHITELIST))


def _load_whitelist() -> dict[int, dict]:
    """Read and index the whitelist file. Missing file → empty whitelist."""
    path = _whitelist_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    indexed = {}
    for entry in data.get("users", []):
        uid = entry.get("telegram_user_id")
        if uid is None:
            continue
        indexed[int(uid)] = entry
    return indexed


def _get_whitelist() -> dict[int, dict]:
    global _whitelist
    if _whitelist is None:
        _whitelist = _load_whitelist()
    return _whitelist


def reload_whitelist() -> dict[int, dict]:
    """Force a re-read of the whitelist file (e.g. for tests)."""
    global _whitelist
    _whitelist = _load_whitelist()
    return _whitelist


def is_authorized(telegram_user_id: int) -> bool:
    """True if this user id is in the whitelist."""
    return int(telegram_user_id) in _get_whitelist()


def get_user_config(telegram_user_id: int) -> dict | None:
    """The whitelist entry for a user, or None if not whitelisted."""
    return _get_whitelist().get(int(telegram_user_id))
