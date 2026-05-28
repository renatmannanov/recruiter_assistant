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


async def _seed_session_with_input(
    db: DB, user_id: int = 999, boolean: str = "(Python)",
) -> int:
    """Create a confirmed session ready for the run step.

    Re-enabled at step_9 to use the new model (vacancy + search rows). Until
    then, the body of this helper writes to dropped columns and the tests
    are skipped below.
    """
    await db.upsert_user(user_id, "Test")
    sid = await db.create_session(user_id, "vacancy_to_candidates")
    await db.update_session(
        sid,
        input_text="Senior Python role",
        boolean_text=boolean,
        boolean_text_original=boolean,
        step="running",
    )
    return sid


@pytest.mark.skip(
    reason="step_9 rewrites pipelines.run_pipeline against the new model "
           "(vacancy/search/candidates/candidate_screenings). Until then "
           "this test seeds sessions with dropped columns."
)
async def test_resumes_from_existing_raw_apify(db, tmp_path):
    """If raw_apify.json exists, discover_candidates must NOT be called."""
    sid = await _seed_session_with_input(db)
    run_id = await db.create_run(sid, 999, "vacancy_to_candidates")

    # Plant a previous-run raw_apify.json on disk.
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
        side_effect=AssertionError("discover_candidates must not be called when raw exists"),
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


@pytest.mark.skip(
    reason="step_9 rewrites pipelines.run_pipeline against the new model "
           "(vacancy/search/candidates/candidate_screenings). Until then "
           "this test seeds sessions with dropped columns."
)
async def test_calls_discover_when_no_raw_apify(db, tmp_path):
    """Fresh session (no raw file) must call discover_candidates once."""
    sid = await _seed_session_with_input(db)
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
