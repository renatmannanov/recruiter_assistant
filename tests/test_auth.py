"""Tests for bot.auth — whitelist-based authorization."""

import json

import pytest

from bot import auth


@pytest.fixture
def whitelist(tmp_path, monkeypatch):
    """Write a temp whitelist file, point auth at it, reload the cache."""
    path = tmp_path / "whitelist.json"
    path.write_text(json.dumps({
        "users": [
            {"telegram_user_id": 423915315, "display_name": "Renat"},
            {"telegram_user_id": 999, "display_name": "Tester"},
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("WHITELIST_PATH", str(path))
    auth.reload_whitelist()
    yield path
    auth.reload_whitelist()  # reset cache for other tests


def test_whitelisted_user_authorized(whitelist):
    assert auth.is_authorized(423915315) is True
    assert auth.is_authorized(999) is True


def test_non_whitelisted_user_rejected(whitelist):
    assert auth.is_authorized(111111) is False


def test_get_user_config(whitelist):
    cfg = auth.get_user_config(423915315)
    assert cfg["display_name"] == "Renat"
    assert auth.get_user_config(111111) is None


def test_authorized_accepts_str_and_int_ids(whitelist):
    # Telegram ids may arrive as int; ensure str also resolves.
    assert auth.is_authorized("423915315") is True


def test_missing_whitelist_file_means_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WHITELIST_PATH", str(tmp_path / "does_not_exist.json"))
    auth.reload_whitelist()
    assert auth.is_authorized(423915315) is False
    auth.reload_whitelist()
