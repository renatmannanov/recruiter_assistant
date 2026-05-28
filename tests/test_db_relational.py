"""Tests for the relational model CRUD added in step_8.

Covers companies, vacancies, candidates, searches, candidate_screenings, and
the two known-candidate predicates (per-user dedup vs. per-vacancy dedup).

The `db` fixture (in conftest.py) gives each test a fresh schema namespace
on the shared `recruiter_assistant_dev` DB.
"""

import asyncio
import json

import asyncpg
import pytest


# ----------------------------------------------------------------- helpers

def _profile(url: str, first: str = "Alice", last: str = "Smith", **extras) -> dict:
    """Build a raw-Apify-shape profile dict for upsert_candidate tests."""
    base = {
        "firstName": first,
        "lastName": last,
        "linkedinUrl": url,
        "headline": "Senior Python Engineer",
        "location": {"parsed": {"text": "Berlin, Germany"}},
        "about": "Backend dev, async, FastAPI.",
    }
    base.update(extras)
    return base


# ---------------------------------------------------------------- companies

async def test_get_or_create_company_is_idempotent(db):
    a = await db.get_or_create_company("Acme")
    b = await db.get_or_create_company("Acme")
    assert a == b
    c = await db.get_or_create_company("Globex")
    assert c != a


async def test_list_companies_sorted(db):
    await db.get_or_create_company("Globex")
    await db.get_or_create_company("Acme")
    names = [c["name"] for c in await db.list_companies()]
    assert names == ["Acme", "Globex"]


# ----------------------------------------------------------------- vacancies

async def test_create_vacancy_with_company(db):
    await db.upsert_user(111)
    cid = await db.get_or_create_company("Acme")
    vid = await db.create_vacancy(
        source="manual",
        name="Sonia ASR",
        jd_text="Senior Python role @ Acme",
        brief_text="internal: prefers async + FastAPI",
        company_id=cid,
        created_by_user_id=111,
    )
    v = await db.get_vacancy(vid)
    assert v["company_id"] == cid
    assert v["source"] == "manual"
    assert v["jd_text"] == "Senior Python role @ Acme"
    assert v["created_by_user_id"] == 111


async def test_list_vacancies_by_user_filters_source(db):
    await db.upsert_user(111)
    await db.upsert_user(222)
    manual_id = await db.create_vacancy(
        source="manual", name="m1", jd_text="JD",
        created_by_user_id=111,
    )
    apify_id = await db.create_vacancy(
        source="apify_job_search",
        linkedin_url="https://linkedin.com/jobs/1",
        title="ML Engineer", created_by_user_id=111,
    )
    # Vacancy belonging to a different user — must not appear.
    await db.create_vacancy(
        source="manual", name="other", jd_text="x",
        created_by_user_id=222,
    )

    all_for_111 = await db.list_vacancies_by_user(111)
    assert {v["id"] for v in all_for_111} == {manual_id, apify_id}

    manual_only = await db.list_vacancies_by_user(111, source="manual")
    assert [v["id"] for v in manual_only] == [manual_id]

    apify_only = await db.list_vacancies_by_user(111, source="apify_job_search")
    assert [v["id"] for v in apify_only] == [apify_id]


async def test_vacancy_linkedin_url_unique_only_for_apify_source(db):
    """Partial UNIQUE: same URL allowed for manual, blocked for apify_job_search."""
    await db.upsert_user(111)
    # Two manual vacancies with NULL linkedin_url — allowed (partial index
    # skips NULL).
    await db.create_vacancy(source="manual", name="m1", jd_text="x",
                            created_by_user_id=111)
    await db.create_vacancy(source="manual", name="m2", jd_text="y",
                            created_by_user_id=111)

    # First apify with a URL — fine.
    await db.create_vacancy(
        source="apify_job_search",
        linkedin_url="https://linkedin.com/jobs/42",
        created_by_user_id=111,
    )
    # Second apify with the same URL — must hit the partial UNIQUE.
    with pytest.raises(asyncpg.UniqueViolationError):
        await db.create_vacancy(
            source="apify_job_search",
            linkedin_url="https://linkedin.com/jobs/42",
            created_by_user_id=111,
        )


# ----------------------------------------------------------------- candidates

async def test_upsert_candidate_returns_same_id_for_same_url(db):
    url = "https://linkedin.com/in/alice"
    a = await db.upsert_candidate(_profile(url))
    b = await db.upsert_candidate(_profile(url, first="Alicia"))
    assert a == b
    row = await db.get_candidate(a)
    # Name from the second call (updated).
    assert row["name"] == "Alicia Smith"
    # raw_profile_json is JSONB — asyncpg returns it as str unless decoded.
    raw = row["raw_profile_json"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert raw["firstName"] == "Alicia"


async def test_upsert_candidate_extracts_cleaned_fields(db):
    url = "https://linkedin.com/in/bob"
    cid = await db.upsert_candidate(_profile(url, first="Bob", last="X"))
    row = await db.get_candidate(cid)
    assert row["name"] == "Bob X"
    assert row["linkedin_url"] == url
    assert row["headline"] == "Senior Python Engineer"
    assert row["location"] == "Berlin, Germany"
    assert row["about"] == "Backend dev, async, FastAPI."


async def test_upsert_candidate_raises_without_url(db):
    with pytest.raises(ValueError, match="linkedinUrl"):
        await db.upsert_candidate({"firstName": "X", "lastName": "Y"})


async def test_get_candidate_by_url(db):
    url = "https://linkedin.com/in/carol"
    cid = await db.upsert_candidate(_profile(url, first="Carol"))
    by_url = await db.get_candidate_by_url(url)
    assert by_url["id"] == cid
    assert await db.get_candidate_by_url("https://linkedin.com/in/missing") is None


# ------------------------------------------------------------------- searches

async def test_create_search_links_to_vacancy(db):
    await db.upsert_user(111)
    vid = await db.create_vacancy(
        source="manual", name="v1", jd_text="JD", created_by_user_id=111,
    )
    sid_a = await db.create_search(
        vacancy_id=vid, boolean_text="(Python)",
        created_by_user_id=111,
    )
    sid_b = await db.create_search(
        vacancy_id=vid, boolean_text="(Python) AND (async)",
        original_boolean="(Python)",
        created_by_user_id=111,
    )
    searches = await db.list_searches_by_vacancy(vid)
    assert [s["id"] for s in searches] == [sid_a, sid_b]
    assert searches[1]["original_boolean"] == "(Python)"
    assert searches[0]["original_boolean"] is None


# ---------------------------------------------------- candidate_screenings

async def test_create_screening_basic(db):
    await db.upsert_user(111)
    vid = await db.create_vacancy(
        source="manual", name="v", jd_text="JD", created_by_user_id=111,
    )
    sess_id = await db.create_session(111, "vacancy_to_candidates")
    rid = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    cid = await db.upsert_candidate(_profile("https://linkedin.com/in/d"))

    sc_id = await db.create_screening(
        candidate_id=cid, vacancy_id=vid, run_id=rid, user_id=111,
        ai_status="pass", ai_score=9, ai_comment="strong",
    )
    rows = await db.list_screenings_by_run(rid)
    assert [r["id"] for r in rows] == [sc_id]
    assert rows[0]["ai_status"] == "pass"
    assert rows[0]["ai_score"] == 9


async def test_create_screening_unique_returns_existing_id(db):
    """ON CONFLICT (candidate, vacancy, run) must return the existing id."""
    await db.upsert_user(111)
    vid = await db.create_vacancy(
        source="manual", name="v", jd_text="JD", created_by_user_id=111,
    )
    sess_id = await db.create_session(111, "vacancy_to_candidates")
    rid = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    cid = await db.upsert_candidate(_profile("https://linkedin.com/in/e"))

    first = await db.create_screening(
        candidate_id=cid, vacancy_id=vid, run_id=rid, user_id=111,
        ai_status="pass", ai_score=9, ai_comment="a",
    )
    # A retry with a *different* payload — id must match, payload must NOT
    # be overwritten (no-op upsert on conflict).
    second = await db.create_screening(
        candidate_id=cid, vacancy_id=vid, run_id=rid, user_id=111,
        ai_status="fail", ai_score=3, ai_comment="b",
    )
    assert first == second
    rows = await db.list_screenings_by_run(rid)
    assert len(rows) == 1
    assert rows[0]["ai_status"] == "pass"   # untouched by the retry
    assert rows[0]["ai_score"] == 9
    assert rows[0]["ai_comment"] == "a"


async def test_list_screenings_by_candidate_across_vacancies(db):
    """A candidate may be screened for multiple vacancies — history is kept."""
    await db.upsert_user(111)
    v1 = await db.create_vacancy(
        source="manual", name="v1", jd_text="JD1", created_by_user_id=111,
    )
    v2 = await db.create_vacancy(
        source="manual", name="v2", jd_text="JD2", created_by_user_id=111,
    )
    sess_id = await db.create_session(111, "vacancy_to_candidates")
    r1 = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    r2 = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    cid = await db.upsert_candidate(_profile("https://linkedin.com/in/f"))

    await db.create_screening(
        candidate_id=cid, vacancy_id=v1, run_id=r1, user_id=111,
        ai_status="fail", ai_score=2, ai_comment="wrong stack",
    )
    await db.create_screening(
        candidate_id=cid, vacancy_id=v2, run_id=r2, user_id=111,
        ai_status="pass", ai_score=8, ai_comment="match",
    )
    history = await db.list_screenings_by_candidate(cid)
    assert {h["vacancy_id"] for h in history} == {v1, v2}


# ----------------------------------------------------- dedup predicates

async def test_is_candidate_known_to_user(db):
    """Per-user history flag (for the PIPELINE_DONE 'already seen' line)."""
    await db.upsert_user(111)
    await db.upsert_user(222)
    vid = await db.create_vacancy(
        source="manual", name="v", jd_text="JD", created_by_user_id=111,
    )
    sess_id = await db.create_session(111, "vacancy_to_candidates")
    rid = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    url = "https://linkedin.com/in/g"
    cid = await db.upsert_candidate(_profile(url))
    await db.create_screening(
        candidate_id=cid, vacancy_id=vid, run_id=rid, user_id=111,
        ai_status="pass", ai_score=7, ai_comment="ok",
    )

    assert await db.is_candidate_known_to_user(111, url) is True
    # Same URL, different user — they haven't seen this person.
    assert await db.is_candidate_known_to_user(222, url) is False
    # Different URL — unknown.
    assert await db.is_candidate_known_to_user(111, "https://linkedin.com/in/zzz") is False


async def test_is_candidate_screened_for_vacancy(db):
    """Per-vacancy dedup flag (for skipping LLM on the pipeline's hot path)."""
    await db.upsert_user(111)
    v1 = await db.create_vacancy(
        source="manual", name="v1", jd_text="JD1", created_by_user_id=111,
    )
    v2 = await db.create_vacancy(
        source="manual", name="v2", jd_text="JD2", created_by_user_id=111,
    )
    sess_id = await db.create_session(111, "vacancy_to_candidates")
    rid = await db.create_run(sess_id, 111, "vacancy_to_candidates")
    url = "https://linkedin.com/in/h"
    cid = await db.upsert_candidate(_profile(url))
    await db.create_screening(
        candidate_id=cid, vacancy_id=v1, run_id=rid, user_id=111,
        ai_status="pass", ai_score=7, ai_comment="ok",
    )

    assert await db.is_candidate_screened_for_vacancy(url, v1) is True
    # Same person, different vacancy — must be False (we WANT to screen them
    # again, requirements differ).
    assert await db.is_candidate_screened_for_vacancy(url, v2) is False


# -------------------------------------------------------------- concurrency

async def test_upsert_candidate_concurrent_same_url(db):
    """Multiple coroutines upserting the same URL must converge to one row."""
    url = "https://linkedin.com/in/race"

    async def upsert():
        return await db.upsert_candidate(_profile(url))

    ids = await asyncio.gather(*(upsert() for _ in range(10)))
    assert len(set(ids)) == 1
    async with db._pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM candidates WHERE linkedin_url = $1", url
        )
    assert n == 1
