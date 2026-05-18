"""Write a Markdown screening report to disk."""

from pathlib import Path

from ..core.report import format_markdown_report


def write_report(
    results: list[dict],
    output_path: str,
    vacancy_name: str,
    model: str,
    total_tokens: int,
) -> None:
    """Format results as Markdown and write to output_path (creates parent dirs)."""
    report = format_markdown_report(results, vacancy_name, model, total_tokens)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
