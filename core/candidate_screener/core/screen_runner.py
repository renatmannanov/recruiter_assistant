"""Pure screening runner — list of profiles + vacancy text -> results + report.

Extracted from cli/run_local.py so the same loop can be driven from the bot
without any CLI / Notion concerns. Caller supplies the OpenAI client (handy
for tests). No file I/O, no Notion, no printing.

The shape of `results` matches what `format_markdown_report` and
`db.insert_candidates` expect, so the bot can pass them through unchanged.
"""

import json

from openai import OpenAI

from .profile_cleaner import clean_profile
from .report import format_markdown_report
from .response_parser import parse_recommendation, parse_score
from .screener import screen_candidate


# gpt-4o blended cost (~$5/M input + $15/M output → ~$10/M). Kept here so it
# matches the figure used in report.py and the bot's run.cost_usd.
_GPT_4O_USD_PER_1K_TOKENS = 0.005


def _ai_status_from_recommendation(recommendation: str) -> str | None:
    """Map LLM recommendation to candidates_found.ai_status.

    The column has a CHECK constraint (pass / fail / uncertain / NULL):
    - GO    -> pass
    - SKIP  -> fail
    - MAYBE -> uncertain
    - anything else (parser returned '?') -> NULL
    """
    return {"GO": "pass", "SKIP": "fail", "MAYBE": "uncertain"}.get(recommendation)


def screen_candidates(
    *,
    client: OpenAI,
    profiles: list[dict],
    vacancy_text: str,
    brief_text: str | None = None,
    vacancy_name: str = "session",
    model: str = "gpt-4o",
    on_progress=None,
) -> dict:
    """Screen each profile against the vacancy, build a markdown report.

    Args:
        client: OpenAI client (caller owns it — easier for testing).
        profiles: raw Apify profile dicts.
        vacancy_text: JD text.
        brief_text: optional internal brief.
        vacancy_name: shown in the report header (e.g. "session_42").
        model: OpenAI model id.
        on_progress: optional callable (i, total, name, score, recommendation,
            usage_total) invoked after each candidate — used by the CLI for
            stdout, ignored by the bot.

    Returns:
        {
            "results": list[dict],     # one per candidate, see fields below
            "report_md": str,
            "total_tokens": int,
            "cost_usd": float,
            "screened_count": int,
            "passed_count": int,       # count of GO + MAYBE
            "db_rows": list[dict],     # ready for db.insert_candidates(...)
        }

    Result row fields: name, linkedin_url, headline, location, score,
    recommendation, evaluation. (Same shape as the old run_local loop.)

    DB row fields: linkedin_url, name, ai_status, ai_score, ai_comment,
    raw_profile_json. (Same keys db.insert_candidates() reads.)
    """
    results: list[dict] = []
    db_rows: list[dict] = []
    total_tokens = 0

    for i, profile in enumerate(profiles, 1):
        evaluation, usage = screen_candidate(
            client, vacancy_text, profile, model, internal_brief=brief_text,
        )
        score = parse_score(evaluation)
        recommendation = parse_recommendation(evaluation)
        total_tokens += usage["total_tokens"]

        cleaned = clean_profile(profile)
        results.append({
            "name": cleaned["name"],
            "linkedin_url": cleaned["linkedin_url"],
            "headline": cleaned["headline"],
            "location": cleaned["location"],
            "score": score,
            "recommendation": recommendation,
            "evaluation": evaluation,
        })

        db_rows.append({
            "linkedin_url": cleaned["linkedin_url"],
            "name": cleaned["name"],
            "ai_status": _ai_status_from_recommendation(recommendation),
            "ai_score": score,
            "ai_comment": evaluation,
            "raw_profile_json": json.dumps(profile, ensure_ascii=False),
        })

        if on_progress is not None:
            on_progress(i, len(profiles), cleaned["name"], score,
                        recommendation, usage["total_tokens"])

    report_md = format_markdown_report(
        # report.py sorts results in-place by score — pass a shallow copy so
        # our `results` list stays in input order for the caller.
        list(results), vacancy_name, model, total_tokens,
    )
    go_count = sum(1 for r in results if r["recommendation"] == "GO")
    maybe_count = sum(1 for r in results if r["recommendation"] == "MAYBE")
    skip_count = sum(1 for r in results if r["recommendation"] == "SKIP")

    return {
        "results": results,
        "report_md": report_md,
        "total_tokens": total_tokens,
        "cost_usd": total_tokens * _GPT_4O_USD_PER_1K_TOKENS / 1000,
        "screened_count": len(results),
        "passed_count": go_count + maybe_count,   # back-compat
        "go_count": go_count,
        "maybe_count": maybe_count,
        "skip_count": skip_count,
        "db_rows": db_rows,
    }
