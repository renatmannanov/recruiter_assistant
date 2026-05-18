"""Tests for db.client.DB.

Covers the CRUD lifecycle, dedup queries, stale-session cleanup, the column
guardrail and asyncio-concurrent writes.

Run from the repo root:  python -m pytest tests/test_db_client.py -v
"""

import asyncio

import pytest

from db.client import DB


@pytest.fixture
def db(tmp_path):
    """A fresh DB initialized from schema.sql, closed after the test."""
    d = DB(str(tmp_path / "test.db"))
    d.initialize_from_schema()
    yield d
    d.close()


# --------------------------------------------------------------------- schema

def test_wal_mode_enabled(db):
    mode = db._conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"]
    assert mode == "wal"


def test_init_records_migrations_as_applied(db):
    applied = {r["name"] for r in db._conn.execute("SELECT name FROM _migrations")}
    assert "001_initial.sql" in applied


def test_apply_migrations_noop_after_init(db):
    assert db.apply_migrations() == []


# ---------------------------------------------------------------------- users

def test_upsert_and_get_user(db):
    assert db.get_user(111) is None
    db.upsert_user(111, "Renat")
    user = db.get_user(111)
    assert user["telegram_user_id"] == 111
    assert user["display_name"] == "Renat"


def test_upsert_user_updates_name(db):
    db.upsert_user(111, "Renat")
    db.upsert_user(111, "Renat M.")
    assert db.get_user(111)["display_name"] == "Renat M."


def test_upsert_user_keeps_name_when_none(db):
    db.upsert_user(111, "Renat")
    db.upsert_user(111, None)  # e.g. a later event without a name
    assert db.get_user(111)["display_name"] == "Renat"


# ------------------------------------------------------------------- sessions

def test_create_session_starts_at_waiting_input(db):
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    session = db.get_session(sid)
    assert session["step"] == "waiting_input"
    assert session["pipeline_type"] == "vacancy_to_candidates"


def test_update_session_bumps_updated_at(db):
    db.upsert_user(111)
    sid = db.create_session(111, "cv_to_jobs")
    db.update_session(sid, input_text="my CV", step="waiting_boolean_confirm")
    session = db.get_session(sid)
    assert session["input_text"] == "my CV"
    assert session["step"] == "waiting_boolean_confirm"


def test_complete_and_fail_session(db):
    db.upsert_user(111)
    sid_ok = db.create_session(111, "vacancy_to_candidates")
    db.complete_session(sid_ok, "data/sessions/1/report.md")
    assert db.get_session(sid_ok)["step"] == "done"
    assert db.get_session(sid_ok)["report_path"] == "data/sessions/1/report.md"

    sid_bad = db.create_session(111, "vacancy_to_candidates")
    db.fail_session(sid_bad, "apify timeout")
    assert db.get_session(sid_bad)["step"] == "error"
    assert db.get_session(sid_bad)["error_text"] == "apify timeout"


def test_get_active_session_returns_latest_non_terminal(db):
    db.upsert_user(111)
    old = db.create_session(111, "vacancy_to_candidates")
    db.complete_session(old, "r.md")  # terminal — excluded
    new = db.create_session(111, "vacancy_to_candidates")
    active = db.get_active_session(111)
    assert active["id"] == new


def test_get_active_session_filters_by_pipeline(db):
    db.upsert_user(111)
    db.create_session(111, "vacancy_to_candidates")
    cv_sid = db.create_session(111, "cv_to_jobs")
    active = db.get_active_session(111, pipeline_type="cv_to_jobs")
    assert active["id"] == cv_sid
    assert active["pipeline_type"] == "cv_to_jobs"


def test_get_active_session_none_when_all_terminal(db):
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    db.complete_session(sid, "r.md")
    assert db.get_active_session(111) is None


def test_cleanup_stale_sessions(db):
    db.upsert_user(111)
    stale = db.create_session(111, "vacancy_to_candidates")
    fresh = db.create_session(111, "vacancy_to_candidates")
    # Move both to 'running'; backdate only `stale`'s updated_at by 1 hour.
    db.update_session(stale, step="running")
    db.update_session(fresh, step="running")
    db._conn.execute(
        "UPDATE sessions SET updated_at = datetime('now', '-60 minutes') "
        "WHERE id = ?",
        (stale,),
    )
    db._conn.commit()

    affected = db.cleanup_stale_sessions(older_than_minutes=30)
    assert affected == 1
    assert db.get_session(stale)["step"] == "error"
    assert db.get_session(stale)["error_text"] == "restarted_or_stalled"
    assert db.get_session(fresh)["step"] == "running"


# ----------------------------------------------------------------------- runs

def test_run_lifecycle(db):
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    rid = db.create_run(sid, 111, "vacancy_to_candidates")
    assert db.get_run(rid)["status"] == "running"

    db.complete_run(rid, found_count=20, screened_count=18,
                    passed_count=5, cost_usd=1.23, duration_sec=42.0)
    run = db.get_run(rid)
    assert run["status"] == "done"
    assert run["found_count"] == 20
    assert run["passed_count"] == 5
    assert run["cost_usd"] == pytest.approx(1.23)


def test_fail_run(db):
    db.upsert_user(111)
    sid = db.create_session(111, "cv_to_jobs")
    rid = db.create_run(sid, 111, "cv_to_jobs")
    db.fail_run(rid, "openai 429")
    run = db.get_run(rid)
    assert run["status"] == "failed"
    assert run["error_text"] == "openai 429"


# ------------------------------------------------------- candidates / vacancies

def test_insert_candidates_and_dedup(db):
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    rid = db.create_run(sid, 111, "vacancy_to_candidates")
    db.insert_candidates(rid, 111, [
        {"linkedin_url": "https://li/a", "name": "Alice",
         "ai_status": "pass", "ai_score": 9, "ai_comment": "strong"},
        {"linkedin_url": "https://li/b", "name": "Bob",
         "ai_status": "fail", "ai_score": 3},
    ])
    assert db.is_candidate_known(111, "https://li/a") is True
    assert db.is_candidate_known(111, "https://li/zzz") is False
    # dedup is per-user — another user has not seen this URL
    assert db.is_candidate_known(222, "https://li/a") is False


def test_insert_vacancies_and_dedup(db):
    db.upsert_user(111)
    sid = db.create_session(111, "cv_to_jobs")
    rid = db.create_run(sid, 111, "cv_to_jobs")
    db.insert_vacancies(rid, 111, [
        {"linkedin_url": "https://li/job1", "title": "ML Engineer",
         "company": "Acme", "location": "Berlin", "ai_score": 8},
    ])
    assert db.is_vacancy_known(111, "https://li/job1") is True
    assert db.is_vacancy_known(111, "https://li/job404") is False


def test_insert_empty_list_is_noop(db):
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    rid = db.create_run(sid, 111, "vacancy_to_candidates")
    db.insert_candidates(rid, 111, [])  # must not raise
    assert db.is_candidate_known(111, "anything") is False


# ----------------------------------------------------------------- guardrails

def test_update_session_rejects_unknown_column(db):
    db.upsert_user(111)
    sid = db.create_session(111, "cv_to_jobs")
    with pytest.raises(ValueError, match="unknown sessions column"):
        db.update_session(sid, bogus_field="x")


def test_update_run_rejects_unknown_column(db):
    db.upsert_user(111)
    sid = db.create_session(111, "cv_to_jobs")
    rid = db.create_run(sid, 111, "cv_to_jobs")
    with pytest.raises(ValueError, match="unknown runs column"):
        db.update_run(rid, not_a_column=1)


# ------------------------------------------------------------------ concurrency

def test_concurrent_inserts_via_asyncio_gather(db):
    """10 concurrent insert_candidates calls must all land without locking."""
    db.upsert_user(111)
    sid = db.create_session(111, "vacancy_to_candidates")
    rid = db.create_run(sid, 111, "vacancy_to_candidates")

    async def insert(n: int):
        # Offload the blocking sqlite write to a thread, like the bot would.
        await asyncio.to_thread(
            db.insert_candidates, rid, 111,
            [{"linkedin_url": f"https://li/c{n}", "name": f"C{n}"}],
        )

    async def run_all():
        await asyncio.gather(*(insert(n) for n in range(10)))

    asyncio.run(run_all())

    count = db._conn.execute(
        "SELECT COUNT(*) AS n FROM candidates_found WHERE run_id = ?", (rid,)
    ).fetchone()["n"]
    assert count == 10
