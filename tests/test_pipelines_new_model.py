"""Tests for bot.pipelines.run_pipeline against the new relational model.

Verifies that a full vacancy_to_candidates run lands in the new tables
(candidates / candidate_screenings / runs) and that the two dedup axes
(per-vacancy skip vs. per-user "already seen" count) behave correctly.

Apify and OpenAI are mocked — these tests run without network or paid calls.
The `db` fixture (conftest.py) gives each test a fresh PG schema namespace.
"""

import json
from unittest.mock import patch

from bot import pipelines
from db.client import DB


# ----------------------------------------------------------------- helpers

def _profile(url: str, first: str = "Alice", last: str = "Smith") -> dict:
    return {
        "firstName": first,
        "lastName": last,
        "linkedinUrl": url,
        "headline": "Senior Python Engineer",
        "location": {"parsed": {"text": "Berlin"}},
        "about": "Backend dev.",
    }


def _screen_row(url: str, name: str, status: str = "pass", score: int = 9) -> dict:
    """Shape db_rows from screen_candidates."""
    return {
        "linkedin_url": url,
        "name": name,
        "ai_status": status,
        "ai_score": score,
        "ai_comment": f"comment for {name}",
        "raw_profile_json": "{}",
    }


async def _seed_session(
    db: DB, user_id: int = 999, boolean: str = "(Python)",
    vacancy_name: str | None = None, apify_params: dict | None = None,
) -> tuple[int, int, int]:
    """Returns (session_id, vacancy_id, run_id) for a session in 'running'."""
    await db.upsert_user(user_id, "Test")
    sid = await db.create_session(user_id, "vacancy_to_candidates")
    vid = await db.create_vacancy(
        source="manual",
        name=vacancy_name or f"vacancy_{sid}",
        jd_text="JD body",
        created_by_user_id=user_id,
    )
    search_id = await db.create_search(
        vacancy_id=vid, boolean_text=boolean, created_by_user_id=user_id,
        apify_params=apify_params,
    )
    await db.update_session(
        sid, vacancy_id=vid, search_id=search_id, step="running",
    )
    rid = await db.create_run(sid, user_id, "vacancy_to_candidates")
    return sid, vid, rid


def _patch_apify_openai(profiles, screen_results):
    """Patch discover_candidates + screen_candidates + the OpenAI client."""
    return (
        patch.object(
            pipelines, "discover_candidates",
            return_value={
                "profiles": profiles,
                "found_count": len(profiles),
                "cost_usd": 0.20,
                "total_found": len(profiles),
            },
        ),
        patch.object(
            pipelines, "screen_candidates",
            return_value=screen_results,
        ),
        patch.object(pipelines, "_new_openai_client", return_value=object()),
    )


def _screen_results(profiles_and_rows) -> dict:
    """Build a screen_candidates return dict from (profile, row) pairs."""
    return {
        "results": [{"linkedin_url": r["linkedin_url"]} for _, r in profiles_and_rows],
        "report_md": "# report",
        "total_tokens": 100,
        "cost_usd": 0.001,
        "screened_count": len(profiles_and_rows),
        "passed_count": sum(1 for _, r in profiles_and_rows if r["ai_status"] != "fail"),
        "go_count": sum(1 for _, r in profiles_and_rows if r["ai_status"] == "pass"),
        "maybe_count": sum(1 for _, r in profiles_and_rows if r["ai_status"] == "uncertain"),
        "skip_count": sum(1 for _, r in profiles_and_rows if r["ai_status"] == "fail"),
        "db_rows": [r for _, r in profiles_and_rows],
    }


# ---------------------------------------------------- happy-path landing

async def test_run_creates_candidates_and_screenings(db, tmp_path):
    sid, vid, rid = await _seed_session(db)
    profiles = [
        _profile("https://li/alice", "Alice"),
        _profile("https://li/bob", "Bob", "Brown"),
    ]
    rows = [
        _screen_row("https://li/alice", "Alice Smith", "pass", 9),
        _screen_row("https://li/bob",   "Bob Brown",   "fail", 3),
    ]
    pairs = list(zip(profiles, rows))
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p:
        result = await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid, db=db, data_dir=str(tmp_path),
        )

    # candidates: one global row per LinkedIn URL.
    assert (await db.get_candidate_by_url("https://li/alice"))["name"] == "Alice Smith"
    assert (await db.get_candidate_by_url("https://li/bob"))["name"] == "Bob Brown"
    # candidate_screenings: one per (candidate, vacancy, run).
    screenings = await db.list_screenings_by_run(rid)
    assert len(screenings) == 2
    statuses = {s["ai_status"] for s in screenings}
    assert statuses == {"pass", "fail"}
    # Pipeline result reports the new dedup counters.
    assert result["already_seen"] == 0
    assert result["skipped_same_vacancy"] == 0
    assert result["go"] == 1
    assert result["skip"] == 1


# ---------------------------------------------------- step_11.5 locations

async def test_locations_passed_to_discover(db, tmp_path):
    """search.apify_params['locations'] must reach discover_candidates."""
    sid, vid, rid = await _seed_session(
        db, apify_params={"locations": ["Germany", "Austria"], "experience": []},
    )
    profiles = [_profile("https://li/alice", "Alice")]
    rows = [_screen_row("https://li/alice", "Alice Smith", "pass", 9)]
    pairs = list(zip(profiles, rows))
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p:
        await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid, db=db, data_dir=str(tmp_path),
        )
        assert (
            pipelines.discover_candidates.call_args.kwargs["locations"]
            == ["Germany", "Austria"]
        )


async def test_null_apify_params_passes_none_locations(db, tmp_path):
    """A search with no apify_params (old rows) -> locations=None, no crash."""
    sid, vid, rid = await _seed_session(db)  # apify_params defaults to None
    profiles = [_profile("https://li/alice", "Alice")]
    rows = [_screen_row("https://li/alice", "Alice Smith", "pass", 9)]
    pairs = list(zip(profiles, rows))
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p:
        await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid, db=db, data_dir=str(tmp_path),
        )
        assert pipelines.discover_candidates.call_args.kwargs["locations"] is None


async def test_empty_locations_list_passes_none(db, tmp_path):
    """An empty locations list -> None (don't send an empty filter to Apify)."""
    sid, vid, rid = await _seed_session(
        db, apify_params={"locations": [], "experience": ["6-10"]},
    )
    profiles = [_profile("https://li/alice", "Alice")]
    rows = [_screen_row("https://li/alice", "Alice Smith", "pass", 9)]
    pairs = list(zip(profiles, rows))
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p:
        await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid, db=db, data_dir=str(tmp_path),
        )
        assert pipelines.discover_candidates.call_args.kwargs["locations"] is None


# ---------------------------------------------------- per-vacancy dedup

async def test_dedup_skips_same_vacancy_screening(db, tmp_path):
    """A candidate already screened for this vacancy in an earlier run must
    NOT hit the LLM again — they're skipped before screen_candidates is called."""
    sid, vid, rid_old = await _seed_session(db)

    # Plant a prior screening of Alice on THIS vacancy via an earlier run.
    alice_id = await db.upsert_candidate(_profile("https://li/alice", "Alice"))
    await db.create_screening(
        candidate_id=alice_id, vacancy_id=vid, run_id=rid_old, user_id=999,
        ai_status="pass", ai_score=9, ai_comment="prior",
    )

    # New run: Apify returns Alice (already-screened) + Bob (fresh).
    rid_new = await db.create_run(sid, 999, "vacancy_to_candidates")
    profiles = [
        _profile("https://li/alice", "Alice"),
        _profile("https://li/bob", "Bob", "Brown"),
    ]
    # Only Bob should reach screen_candidates.
    rows = [_screen_row("https://li/bob", "Bob Brown", "pass", 8)]
    pairs = [(profiles[1], rows[0])]
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p as _openai:
        result = await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid_new, db=db, data_dir=str(tmp_path),
        )
        # Verify screen_candidates was called with ONLY Bob.
        called_profiles = pipelines.screen_candidates.call_args.kwargs["profiles"]
        assert [p["linkedinUrl"] for p in called_profiles] == ["https://li/bob"]

    assert result["skipped_same_vacancy"] == 1
    assert result["already_seen"] == 0      # Alice was on the SAME vacancy
    assert result["screened"] == 1
    # The prior screening row is untouched (still 1 screening for Alice on this vacancy).
    alice_screenings = await db.list_screenings_by_candidate(alice_id)
    assert len(alice_screenings) == 1
    assert alice_screenings[0]["run_id"] == rid_old


# ---------------------------------------------------- per-user "already seen"

async def test_already_seen_counts_cross_vacancy_match(db, tmp_path):
    """A candidate seen by this user on a DIFFERENT vacancy must be counted
    in `already_seen` but still screened (different requirements)."""
    user_id = 999
    # Vacancy A: Alice was screened there earlier.
    _, vid_a, rid_a = await _seed_session(db, user_id=user_id, vacancy_name="vac_A")
    alice_id = await db.upsert_candidate(_profile("https://li/alice", "Alice"))
    await db.create_screening(
        candidate_id=alice_id, vacancy_id=vid_a, run_id=rid_a, user_id=user_id,
        ai_status="fail", ai_score=2, ai_comment="wrong stack",
    )

    # Vacancy B: a fresh session. Apify brings Alice again.
    sid_b, vid_b, rid_b = await _seed_session(
        db, user_id=user_id, vacancy_name="vac_B",
    )
    profiles = [_profile("https://li/alice", "Alice")]
    rows = [_screen_row("https://li/alice", "Alice Smith", "pass", 7)]
    pairs = list(zip(profiles, rows))
    d_p, s_p, o_p = _patch_apify_openai(profiles, _screen_results(pairs))
    with d_p, s_p, o_p:
        result = await pipelines.run_pipeline(
            sid_b, "vacancy_to_candidates",
            run_id=rid_b, db=db, data_dir=str(tmp_path),
        )

    assert result["already_seen"] == 1      # known to user from vacancy A
    assert result["skipped_same_vacancy"] == 0
    assert result["screened"] == 1          # still went through screening
    # Alice now has two screenings, one per vacancy.
    history = await db.list_screenings_by_candidate(alice_id)
    assert {h["vacancy_id"] for h in history} == {vid_a, vid_b}


# ---------------------------------------------------- failure modes

async def test_session_without_search_id_fails_cleanly(db, tmp_path):
    """Missing search_id (e.g. someone calls run_pipeline before confirm) must
    raise — not silently produce a junk run."""
    user_id = 999
    await db.upsert_user(user_id, "Test")
    sid = await db.create_session(user_id, "vacancy_to_candidates")
    vid = await db.create_vacancy(
        source="manual", name="v", jd_text="JD", created_by_user_id=user_id,
    )
    await db.update_session(sid, vacancy_id=vid, step="running")
    rid = await db.create_run(sid, user_id, "vacancy_to_candidates")

    try:
        await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=rid, db=db, data_dir=str(tmp_path),
        )
    except RuntimeError as e:
        assert "search_id" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
