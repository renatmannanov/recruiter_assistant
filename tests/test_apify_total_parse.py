"""Test the regex that pulls 'total found' out of the Apify actor log."""

from unittest.mock import MagicMock

from core.candidate_screener.sources.from_apify_search import (
    _TOTAL_FOUND_RE,
    _extract_total_found,
)


def test_regex_matches_real_actor_line():
    line = 'Found 4510 profiles total for input {"search":"(...)"}'
    m = _TOTAL_FOUND_RE.search(line)
    assert m is not None
    assert int(m.group(1)) == 4510


def test_regex_misses_unrelated_lines():
    assert _TOTAL_FOUND_RE.search("Some random log entry") is None
    # "found" appears in the wrong shape — must not match
    assert _TOTAL_FOUND_RE.search("Found profile https://...") is None


def test_extract_total_found_reads_log():
    fake_client = MagicMock()
    fake_client.log.return_value.get.return_value = (
        "Starting...\n"
        "Found 1234 profiles total for input {...}\n"
        "Scraped page 1\n"
    )
    assert _extract_total_found(fake_client, "RUN_X") == 1234


def test_extract_total_found_returns_none_on_failure():
    fake_client = MagicMock()
    fake_client.log.side_effect = RuntimeError("boom")
    assert _extract_total_found(fake_client, "RUN_X") is None
