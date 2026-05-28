"""Tests for db.client.DB.

Covers the CRUD lifecycle, dedup queries, stale-session cleanup, the column
guardrail and asyncio-concurrent writes against a real Postgres instance.

The `db` fixture (in conftest.py) gives each test a fresh schema namespace
on the shared `recruiter_assistant_dev` DB.

Run from the repo root:  python -m pytest tests/test_db_client.py -v
"""

import pytest


# --------------------------------------------------------------------- schema

async def test_init_records_migrations_as_applied(db):
    async with db._pool.acquire() as conn:
        applied = {r["name"] for r in await conn.fetch("SELECT name FROM _migrations")}
    assert "001_initial.sql" in applied


async def test_apply_migrations_noop_after_init(db):
    assert await db.apply_migrations() == []


# ---------------------------------------------------------------------- users

async def test_upsert_and_get_user(db):
    assert await db.get_user(111) is None
    await db.upsert_user(111, "Renat")
    user = await db.get_user(111)
    assert user["telegram_user_id"] == 111
    assert user["display_name"] == "Renat"


async def test_upsert_user_updates_name(db):
    await db.upsert_user(111, "Renat")
    await db.upsert_user(111, "Renat M.")
    assert (await db.get_user(111))["display_name"] == "Renat M."


async def test_upsert_user_keeps_name_when_none(db):
    await db.upsert_user(111, "Renat")
    await db.upsert_user(111, None)  # e.g. a later event without a name
    assert (await db.get_user(111))["display_name"] == "Renat"


# ------------------------------------------------------------------- sessions

async def test_create_session_starts_at_waiting_input(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "vacancy_to_candidates")
    session = await db.get_session(sid)
    assert session["step"] == "waiting_input"
    assert session["pipeline_type"] == "vacancy_to_candidates"


async def test_update_session_bumps_updated_at(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "cv_to_jobs")
    await db.update_session(sid, step="waiting_boolean_confirm")
    session = await db.get_session(sid)
    assert session["step"] == "waiting_boolean_confirm"


async def test_complete_and_fail_session(db):
    await db.upsert_user(111)
    sid_ok = await db.create_session(111, "vacancy_to_candidates")
    await db.complete_session(sid_ok, "data/sessions/1/report.md")
    assert (await db.get_session(sid_ok))["step"] == "done"
    assert (await db.get_session(sid_ok))["report_path"] == "data/sessions/1/report.md"

    sid_bad = await db.create_session(111, "vacancy_to_candidates")
    await db.fail_session(sid_bad, "apify timeout")
    assert (await db.get_session(sid_bad))["step"] == "error"
    assert (await db.get_session(sid_bad))["error_text"] == "apify timeout"


async def test_get_active_session_returns_latest_non_terminal(db):
    await db.upsert_user(111)
    old = await db.create_session(111, "vacancy_to_candidates")
    await db.complete_session(old, "r.md")  # terminal — excluded
    new = await db.create_session(111, "vacancy_to_candidates")
    active = await db.get_active_session(111)
    assert active["id"] == new


async def test_get_active_session_filters_by_pipeline(db):
    await db.upsert_user(111)
    await db.create_session(111, "vacancy_to_candidates")
    cv_sid = await db.create_session(111, "cv_to_jobs")
    active = await db.get_active_session(111, pipeline_type="cv_to_jobs")
    assert active["id"] == cv_sid
    assert active["pipeline_type"] == "cv_to_jobs"


async def test_get_active_session_none_when_all_terminal(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "vacancy_to_candidates")
    await db.complete_session(sid, "r.md")
    assert await db.get_active_session(111) is None


async def test_cleanup_stale_sessions(db):
    await db.upsert_user(111)
    stale = await db.create_session(111, "vacancy_to_candidates")
    fresh = await db.create_session(111, "vacancy_to_candidates")
    # Move both to 'running'; backdate only `stale`'s updated_at by 1 hour.
    await db.update_session(stale, step="running")
    await db.update_session(fresh, step="running")
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET updated_at = now() - interval '60 minutes' "
            "WHERE id = $1",
            stale,
        )

    affected = await db.cleanup_stale_sessions(older_than_minutes=30)
    assert affected == 1
    assert (await db.get_session(stale))["step"] == "error"
    assert (await db.get_session(stale))["error_text"] == "restarted_or_stalled"
    assert (await db.get_session(fresh))["step"] == "running"


# ----------------------------------------------------------------------- runs

async def test_run_lifecycle(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "vacancy_to_candidates")
    rid = await db.create_run(sid, 111, "vacancy_to_candidates")
    assert (await db.get_run(rid))["status"] == "running"

    await db.complete_run(rid, found_count=20, screened_count=18,
                          passed_count=5, cost_usd=1.23, duration_sec=42.0)
    run = await db.get_run(rid)
    assert run["status"] == "done"
    assert run["found_count"] == 20
    assert run["passed_count"] == 5
    assert run["cost_usd"] == pytest.approx(1.23)


async def test_fail_run(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "cv_to_jobs")
    rid = await db.create_run(sid, 111, "cv_to_jobs")
    await db.fail_run(rid, "openai 429")
    run = await db.get_run(rid)
    assert run["status"] == "failed"
    assert run["error_text"] == "openai 429"


# ------------------------------------------------------------------ guardrails
# (Tests for the new relational model — candidates / vacancies / searches /
#  candidate_screenings — live in test_db_relational.py.)
#
# Removed at step_8: test_insert_candidates_and_dedup,
#                    test_insert_vacancies_and_dedup,
#                    test_insert_empty_list_is_noop
# — the underlying tables (candidates_found / vacancies_found) and methods
# (insert_candidates / is_candidate_known / ...) were dropped in migration 002.

async def test_update_session_rejects_unknown_column(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "cv_to_jobs")
    with pytest.raises(ValueError, match="unknown sessions column"):
        await db.update_session(sid, bogus_field="x")


async def test_update_run_rejects_unknown_column(db):
    await db.upsert_user(111)
    sid = await db.create_session(111, "cv_to_jobs")
    rid = await db.create_run(sid, 111, "cv_to_jobs")
    with pytest.raises(ValueError, match="unknown runs column"):
        await db.update_run(rid, not_a_column=1)


# Concurrency test was removed at step_8 — it inserted into candidates_found,
# which is dropped in migration 002. A new concurrency test against the
# relational model (upsert_candidate via asyncio.gather) lives in
# test_db_relational.py.
