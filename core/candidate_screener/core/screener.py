"""Core screening functions — no CLI, no I/O.

Two directions:
- screen_candidate(): vacancy + profile -> evaluation (existing flow)
- screen_job():       cv + job posting    -> evaluation (cv-to-jobs flow)

Both use the same response_parser for SCORE/RECOMMENDATION extraction.
"""

import json

from openai import OpenAI

from .profile_cleaner import clean_profile
from .prompts_candidates import SYSTEM_PROMPT, build_screening_prompt
from .prompts_jd_screening import (
    SYSTEM_PROMPT as JD_SCREENING_SYSTEM_PROMPT,
    build_screening_prompt as build_jd_screening_prompt,
)


def screen_candidate(
    client: OpenAI,
    vacancy_text: str,
    profile: dict,
    model: str = "gpt-4o",
    internal_brief: str | None = None,
) -> tuple[str, dict]:
    """
    Screen a single candidate against a vacancy.

    Returns:
        Tuple of (AI response text, usage dict with token counts)
    """
    cleaned = clean_profile(profile)
    profile_json = json.dumps(cleaned, indent=2, ensure_ascii=False)

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_screening_prompt(
                vacancy_text, profile_json, internal_brief=internal_brief,
            )},
        ],
    )

    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }

    return response.choices[0].message.content, usage


def screen_job(
    client: OpenAI,
    job: dict,
    cv_structured: dict,
    candidate_brief: str | None = None,
    model: str = "gpt-4o",
) -> tuple[str, dict]:
    """
    Screen a single job posting against a candidate (mirror of screen_candidate).

    Args:
        client: OpenAI client.
        job: cleaned job dict from job_cleaner.clean_job().
        cv_structured: parsed CV from cv_parser.parse_cv() — raw_cv key is
            preserved on the dict and used as cv_text in the prompt.
        candidate_brief: optional brief.md content (visa, salary, blocklist).
        model: OpenAI model.

    Returns:
        Tuple of (AI response text, usage dict).
    """
    cv_text = cv_structured.get("raw_cv", "")

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": JD_SCREENING_SYSTEM_PROMPT},
            {"role": "user", "content": build_jd_screening_prompt(
                cv_structured=cv_structured,
                cv_text=cv_text,
                job=job,
                candidate_brief=candidate_brief,
            )},
        ],
    )

    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }

    return response.choices[0].message.content, usage
