"""Pipeline wrappers.

step_4 ships STUBS so the bot flow can be exercised end-to-end without
touching OpenAI or Apify. step_5 (vacancy->candidates) and step_6
(cv->jobs) replace these with the real core/ pipeline calls.
"""

import asyncio
from pathlib import Path

_STUB_REPORT_DELAY_SEC = 5


async def generate_boolean(
    input_text: str, brief_text: str | None, pipeline_type: str
) -> str:
    """STUB: return a fake boolean string for flow testing.

    Real implementation (step_5/6) calls core.boolean_generator.
    """
    has_brief = " (+brief)" if brief_text else ""
    return (
        f'("Senior Engineer" OR "Lead") AND (Python) '
        f'— STUB for {pipeline_type}{has_brief}'
    )


async def run_pipeline(
    session_id: int, pipeline_type: str, data_dir: str = "./data"
) -> dict:
    """STUB: wait a few seconds, write a fake report, return fake metrics.

    Real implementation (step_5/6) runs discover + screening / run_jobs.
    Returns a dict: found, screened, passed, report_path.
    """
    await asyncio.sleep(_STUB_REPORT_DELAY_SEC)

    session_dir = Path(data_dir) / "sessions" / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    report_path = session_dir / "report.md"
    report_path.write_text(
        f"# STUB report — session #{session_id}\n\n"
        f"Pipeline: {pipeline_type}\n\n"
        f"This is a placeholder report produced by the step_4 stub.\n"
        f"Real results arrive once step_5/step_6 wire in the pipelines.\n",
        encoding="utf-8",
    )

    return {
        "found": 10,
        "screened": 5,
        "passed": 2,
        "report_path": str(report_path),
    }
