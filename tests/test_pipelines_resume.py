"""Tests for the discover-resume behaviour in bot.pipelines.

If a session already has data/sessions/<id>/raw_apify.json on disk (left over
from a previous attempt that failed after Apify but before screening
succeeded), the pipeline must reuse it instead of paying Apify again.

The `db` fixture comes from conftest.py and points at a per-test PG schema.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot import pipelines
from db.client import DB


async def _seed_running_session(
    db: DB, user_id: int = 999, boolean: str = "(Python)",
) -> int:
    """Create a session linked to a manual vacancy and a search, set to
    'running' — the state pipelines.run_pipeline expects."""
    await db.upsert_user(user_id, "Test")
    sid = await db.create_session(user_id, "vacancy_to_candidates")
    vid = await db.create_vacancy(
        source="manual",
        name=f"vacancy_{sid}",
        jd_text="Senior Python role",
        created_by_user_id=user_id,
    )
    search_id = await db.create_search(
        vacancy_id=vid, boolean_text=boolean, created_by_user_id=user_id,
    )
    await db.update_session(
        sid, vacancy_id=vid, search_id=search_id, step="running",
    )
    return sid


async def test_resumes_from_existing_raw_apify(db, tmp_path):
    """If raw_apify.json exists, discover_candidates must NOT be called."""
    sid = await _seed_running_session(db)
    run_id = await db.create_run(sid, 999, "vacancy_to_candidates")

    sess_dir = tmp_path / "sessions" / str(sid)
    sess_dir.mkdir(parents=True)
    raw = [{
        "firstName": "Alice", "lastName": "Test",
        "linkedinUrl": "https://linkedin.com/in/alice",
        "headline": "Senior Python Dev",
    }]
    (sess_dir / "raw_apify.json").write_text(
        json.dumps(raw), encoding="utf-8",
    )

    with patch.object(
        pipelines, "discover_candidates",
        side_effect=AssertionError(
            "discover_candidates must not be called when raw exists"
        ),
    ), patch.object(pipelines, "screen_candidates") as fake_screen, \
         patch.object(pipelines, "_new_openai_client", return_value=object()):
        fake_screen.return_value = {
            "results": [],
            "report_md": "# empty",
            "total_tokens": 0,
            "cost_usd": 0.0,
            "screened_count": 0,
            "passed_count": 0,
            "go_count": 0,
            "maybe_count": 0,
            "skip_count": 0,
            "db_rows": [],
        }
        result = await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=run_id, db=db, data_dir=str(tmp_path),
        )

    assert result["found"] == 1
    # cost_usd must NOT include Apify on a resume (we already paid).
    assert result["cost_usd"] == 0.0


async def test_calls_discover_when_no_raw_apify(db, tmp_path):
    """Fresh session (no raw file) must call discover_candidates once."""
    sid = await _seed_running_session(db)
    run_id = await db.create_run(sid, 999, "vacancy_to_candidates")

    fake_profiles = [{
        "firstName": "Bob", "lastName": "X",
        "linkedinUrl": "https://linkedin.com/in/bob",
    }]
    with patch.object(
        pipelines, "discover_candidates",
        return_value={
            "profiles": fake_profiles,
            "found_count": 1,
            "cost_usd": 0.20,
        },
    ) as fake_discover, patch.object(pipelines, "screen_candidates") as fake_screen, \
         patch.object(pipelines, "_new_openai_client", return_value=object()):
        fake_screen.return_value = {
            "results": [], "report_md": "# r", "total_tokens": 0,
            "cost_usd": 0.0, "screened_count": 0, "passed_count": 0,
            "go_count": 0, "maybe_count": 0, "skip_count": 0,
            "db_rows": [],
        }
        result = await pipelines.run_pipeline(
            sid, "vacancy_to_candidates",
            run_id=run_id, db=db, data_dir=str(tmp_path),
        )

    fake_discover.assert_called_once()
    assert result["cost_usd"] == pytest.approx(0.20)
    # File must have been written for future resumes.
    assert (Path(tmp_path) / "sessions" / str(sid) / "raw_apify.json").exists()
