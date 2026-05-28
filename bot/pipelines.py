"""Pipeline wrappers — translate bot sessions into core/ pipeline calls.

step_5 wires up `vacancy_to_candidates` end-to-end:
    text -> generate_boolean -> [user confirms] -> discover -> screen -> report.md

`cv_to_jobs` is still a stub — step_6 will wire it the same way.

Design notes:
- Pipelines update intermediate run fields (raw_apify_path, screening_json,
  report_md). The handler creates and finalizes the run (complete_run /
  fail_run) — this is the boundary inherited from step_4.
- All blocking work (OpenAI HTTP, Apify HTTP) runs through asyncio.to_thread
  so the bot's polling loop stays responsive while a session is running.
- core/ is treated as a library: no `sys.exit`, no `print` to the user. Errors
  bubble up to the handler which surfaces them in Telegram.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from openai import OpenAI

from core.boolean_generator.generator import (
    extract_boolean,
    generate_boolean_search,
)
from core.candidate_screener.core import (
    discover_candidates,
    get_profile_url,
    screen_candidates,
)
from db.client import DB

log = logging.getLogger(__name__)

_PIPELINE_VACANCY = "vacancy_to_candidates"
_PIPELINE_CV = "cv_to_jobs"


# --------------------------------------------------------------- boolean


async def generate_boolean(
    input_text: str, brief_text: str | None, pipeline_type: str,
) -> str:
    """JD/CV text -> a single boolean query string.

    For vacancy_to_candidates the LLM returns markdown with multiple sections;
    we extract just the boolean line — that's what discover.py needs.

    cv_to_jobs (target=jobs) requires a parsed CV. Step_6 wires it in;
    until then the bot still returns a usable placeholder.
    """
    if pipeline_type == _PIPELINE_VACANCY:
        target = "candidates"
    elif pipeline_type == _PIPELINE_CV:
        # TODO(step_6): parse CV first, then call generate_boolean_search with
        # target='jobs'. For now keep the step_4-style stub so the bot flow
        # works end-to-end without crashing.
        has_brief = " (+brief)" if brief_text else ""
        return (
            f'("Senior Engineer" OR "Lead") AND (Python) '
            f'— STUB for {pipeline_type}{has_brief}'
        )
    else:
        raise ValueError(f"unknown pipeline_type: {pipeline_type!r}")

    markdown = await asyncio.to_thread(
        generate_boolean_search,
        target=target,
        source_text=input_text,
        brief=brief_text,
    )
    return extract_boolean(markdown)


# --------------------------------------------------------------- pipeline


async def run_pipeline(
    session_id: int,
    pipeline_type: str,
    *,
    run_id: int,
    db: DB,
    data_dir: str = "./data",
) -> dict:
    """Execute the pipeline for an active session.

    The handler has already created the session and the run. This function
    fills in intermediate run fields (raw_apify_path, screening_json,
    report_md) as it goes, and returns the final counters / paths for the
    handler to commit via complete_run + complete_session.

    Returns:
        {
            "found": int,           # raw Apify result count
            "screened": int,        # candidates actually sent to OpenAI
            "passed": int,          # GO + MAYBE
            "report_path": str,     # absolute path to report.md
            "cost_usd": float,      # apify + openai
            "duration_sec": float,
        }

    Raises on any failure — the handler converts that into fail_run /
    fail_session + the Telegram error message.
    """
    if pipeline_type == _PIPELINE_VACANCY:
        return await _run_vacancy_pipeline(
            session_id, run_id=run_id, db=db, data_dir=data_dir,
        )
    if pipeline_type == _PIPELINE_CV:
        return await _run_cv_pipeline_stub(
            session_id, run_id=run_id, db=db, data_dir=data_dir,
        )
    raise ValueError(f"unknown pipeline_type: {pipeline_type!r}")


# ---------------------------------------------------------------- helpers


def _session_dir(data_dir: str, session_id: int) -> Path:
    """data/sessions/<id>/ — created on demand."""
    path = Path(data_dir) / "sessions" / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------- vacancy pipeline


async def _run_vacancy_pipeline(
    session_id: int,
    *,
    run_id: int,
    db: DB,
    data_dir: str,
) -> dict:
    started_at = time.monotonic()
    session = await db.get_session(session_id)
    if session is None:
        raise RuntimeError(f"session {session_id} not found")

    user_id = session["user_id"]
    boolean = session["boolean_text"]
    if not boolean:
        raise RuntimeError("session has no confirmed boolean_text")

    sess_dir = _session_dir(data_dir, session_id)
    raw_path = sess_dir / "raw_apify.json"

    # 1) Apify discover. Resume from disk if the previous attempt for this
    # session already paid Apify — re-running it would burn money and the
    # query is the same anyway. Failures *after* discover (DB inserts,
    # OpenAI hiccups) are the common case here.
    if raw_path.exists():
        profiles = json.loads(raw_path.read_text(encoding="utf-8"))
        discover_result = {
            "profiles": profiles,
            "found_count": len(profiles),
            "cost_usd": 0.0,  # already paid, not re-charged on this run
        }
        log.info(
            "session %s: discover resumed from disk — %d profiles, $0 (already paid)",
            session_id, discover_result["found_count"],
        )
    else:
        log.info("session %s: discover starting", session_id)
        discover_result = await asyncio.to_thread(
            discover_candidates, boolean=boolean,
        )
        raw_path.write_text(
            json.dumps(discover_result["profiles"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(
            "session %s: discover done — %d profiles, ~$%.2f",
            session_id, discover_result["found_count"],
            discover_result["cost_usd"],
        )
    await db.update_run(run_id, raw_apify_path=str(raw_path))

    # 2) Dedup against this user's previously seen candidates (SQLite-only).
    seen_before = 0
    new_profiles: list[dict] = []
    for p in discover_result["profiles"]:
        url = get_profile_url(p)
        if not url:
            # No URL means we cannot dedup or store it. Skip — same as
            # discover.py CLI behaviour.
            continue
        if await db.is_candidate_known(user_id, url):
            seen_before += 1
            continue
        new_profiles.append(p)
    log.info(
        "session %s: dedup — %d already seen, %d new to screen",
        session_id, seen_before, len(new_profiles),
    )

    # 3) Screening. Empty list is fine — we still write a (very short) report
    # so the user gets the same shape of output every time.
    openai_client = _new_openai_client()
    screening = await asyncio.to_thread(
        screen_candidates,
        client=openai_client,
        profiles=new_profiles,
        vacancy_text=session["input_text"] or "",
        brief_text=session["brief_text"],
        vacancy_name=f"session_{session_id}",
    )

    # 4) Persist screened candidates (idempotent: dedup above guarantees no
    # duplicates per user). Skip if nothing was screened.
    if screening["db_rows"]:
        await db.insert_candidates(run_id, user_id, screening["db_rows"])

    # 5) Write the report file + persist the markdown body for analytics.
    report_path = sess_dir / "report.md"
    report_path.write_text(screening["report_md"], encoding="utf-8")
    await db.update_run(
        run_id,
        screening_json=json.dumps(
            [_compact_result(r) for r in screening["results"]],
            ensure_ascii=False,
        ),
        report_md=screening["report_md"],
    )

    duration = time.monotonic() - started_at
    total_cost = discover_result["cost_usd"] + screening["cost_usd"]

    return {
        "found": discover_result["found_count"],        # scraped this run
        "total_found": discover_result.get("total_found"),  # LinkedIn-wide
        "screened": screening["screened_count"],
        "passed": screening["passed_count"],            # GO + MAYBE
        "go": screening["go_count"],
        "maybe": screening["maybe_count"],
        "skip": screening["skip_count"],
        "report_path": str(report_path),
        "cost_usd": total_cost,
        "duration_sec": duration,
    }


def _compact_result(r: dict) -> dict:
    """A small, queryable subset of a screening result for runs.screening_json.

    The full evaluation text is kept too (it's useful when debugging without
    re-running) but we strip nothing else here — analytic queries can JSON-
    extract the fields they need.
    """
    return {
        "name": r.get("name"),
        "linkedin_url": r.get("linkedin_url"),
        "score": r.get("score"),
        "recommendation": r.get("recommendation"),
        "evaluation": r.get("evaluation"),
    }


def _new_openai_client() -> OpenAI:
    """OpenAI client constructor — separate so tests can monkeypatch."""
    api_key = os.getenv("OPEN_AI_KEY")
    if not api_key:
        raise RuntimeError("OPEN_AI_KEY is not set")
    return OpenAI(api_key=api_key)


# -------------------------------------------------------------- cv stub


async def _run_cv_pipeline_stub(
    session_id: int,
    *,
    run_id: int,
    db: DB,
    data_dir: str,
) -> dict:
    """cv_to_jobs is wired in step_6. Keep the step_4 stub shape so the bot
    still answers something instead of erroring out."""
    await asyncio.sleep(2)
    sess_dir = _session_dir(data_dir, session_id)
    report_path = sess_dir / "report.md"
    report_path.write_text(
        f"# STUB report — session #{session_id} (cv_to_jobs)\n\n"
        f"cv_to_jobs is wired on step_6.\n",
        encoding="utf-8",
    )
    return {
        "found": 0,
        "total_found": 0,
        "screened": 0,
        "passed": 0,
        "go": 0,
        "maybe": 0,
        "skip": 0,
        "report_path": str(report_path),
        "cost_usd": 0.0,
        "duration_sec": 2.0,
    }
