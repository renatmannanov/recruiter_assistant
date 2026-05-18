"""Parse a CV file (.md) into a structured profile.

Single LLM call (gpt-4o, temperature=0, response_format=json_object) extracts:
name, primary_stack, seniority, locations, languages, experience, education.
The raw CV text is preserved on the returned dict for downstream screening.
"""

import json
import os
from pathlib import Path

from openai import OpenAI

from .prompts_cv import SYSTEM_PROMPT, build_user_prompt


def parse_cv(
    cv_path: str | Path,
    client: OpenAI | None = None,
    model: str = "gpt-4o",
) -> dict:
    """Parse a CV file into a structured dict.

    Args:
        cv_path: path to a cv.md file (markdown).
        client: optional OpenAI client. If None, one is created from OPEN_AI_KEY
            env var (loads .env files automatically).
        model: OpenAI model to use.

    Returns:
        dict with keys: name, headline, summary, primary_stack, seniority,
        years_experience, current_location, languages, experience, education,
        raw_cv.
    """
    cv_text = Path(cv_path).read_text(encoding="utf-8").strip()

    if not cv_text:
        raise ValueError(f"CV file is empty: {cv_path}")

    if client is None:
        client = OpenAI(api_key=os.getenv("OPEN_AI_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(cv_text)},
        ],
    )

    parsed = json.loads(response.choices[0].message.content)
    parsed["raw_cv"] = cv_text
    return parsed
