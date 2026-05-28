"""Tests for screen_runner — focused on the LLM recommendation -> ai_status
mapping (a CHECK-constrained DB column, easy to mis-map)."""

from core.candidate_screener.core.screen_runner import (
    _ai_status_from_recommendation,
)


def test_recommendation_maps_to_db_check_values():
    # candidates_found.ai_status CHECK is ('pass', 'fail', 'uncertain') or NULL.
    # Mis-mapping here means the whole bot pipeline fails on INSERT.
    assert _ai_status_from_recommendation("GO") == "pass"
    assert _ai_status_from_recommendation("SKIP") == "fail"
    assert _ai_status_from_recommendation("MAYBE") == "uncertain"


def test_unknown_recommendation_returns_none():
    # parse_recommendation falls back to '?' when the LLM response doesn't
    # match — that must become NULL, not a constraint violation.
    assert _ai_status_from_recommendation("?") is None
    assert _ai_status_from_recommendation("") is None
