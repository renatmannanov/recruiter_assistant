"""Format screening results as a Markdown report.

Two report shapes:
- format_markdown_report(): vacancy-vs-candidates (existing flow)
- format_jobs_report():     candidate-vs-jobs (cv-to-jobs flow)
"""

from datetime import datetime


# Per-million-token prices (rough mixed input+output blended estimate).
# gpt-4o:      $5/M input + $15/M output ≈ $10/M for typical screening mix.
# gpt-4o-mini: $0.15/M input + $0.6/M output ≈ $0.4/M.
COST_PER_M_TOKENS = {
    "gpt-4o": 10.0,
    "gpt-4o-mini": 0.4,
}


def format_markdown_report(
    results: list[dict],
    vacancy_name: str,
    model: str,
    total_tokens: int,
) -> str:
    """Format screening results as a Markdown report."""
    results.sort(key=lambda r: r["score"], reverse=True)

    cost = total_tokens * 0.005 / 1000

    lines = [
        f"# Screening: {vacancy_name}",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Profiles:** {len(results)}",
        f"**Model:** {model}",
        f"**Total tokens:** {total_tokens:,}",
        f"**Est. cost:** ~${cost:.2f}",
        "",
        "---",
        "",
    ]

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| # | Name | Score | Rec | Headline |")
    lines.append("|---|------|-------|-----|----------|")
    for i, r in enumerate(results, 1):
        name = r["name"]
        score = r["score"]
        rec = r["recommendation"]
        headline = r["headline"][:60] + "..." if len(r["headline"]) > 60 else r["headline"]
        lines.append(f"| {i} | {name} | {score}/10 | {rec} | {headline} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed results
    lines.append("## Detailed Results")
    lines.append("")
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r['name']} — Score: {r['score']}/10 — {r['recommendation']}")
        lines.append(f"**LinkedIn:** {r['linkedin_url']}")
        lines.append(f"**Location:** {r['location']}")
        lines.append(f"**Headline:** {r['headline']}")
        lines.append("")
        lines.append(r["evaluation"])
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def format_jobs_report(
    candidate_name: str,
    cv_summary: str,
    results: list[dict],
    model: str,
    total_tokens: int,
) -> str:
    """Format JD-vs-CV screening results as a Markdown report.

    Args:
        candidate_name: candidate folder name (e.g. "test_python").
        cv_summary: short CV summary (headline + primary stack) for the header.
        results: list of dicts with keys:
            - job: cleaned job dict from job_cleaner.clean_job()
            - score: int (1-10)
            - recommendation: "GO" | "MAYBE" | "SKIP"
            - evaluation: full LLM response text
        model: OpenAI model used.
        total_tokens: total tokens spent across all screen_job() calls.
    """
    results.sort(key=lambda r: r["score"], reverse=True)

    cost_per_m = COST_PER_M_TOKENS.get(model, COST_PER_M_TOKENS["gpt-4o"])
    cost = total_tokens * cost_per_m / 1_000_000

    lines = [
        f"# Jobs match: {candidate_name}",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Jobs evaluated:** {len(results)}",
        f"**Model:** {model}",
        f"**Total tokens:** {total_tokens:,}",
        f"**Est. cost:** ~${cost:.2f}",
        "",
        "## Candidate summary",
        cv_summary,
        "",
        "---",
        "",
        "## Top matches",
        "",
        "| # | Score | Rec | Title | Company | Location | Recruiter |",
        "|---|-------|-----|-------|---------|----------|-----------|",
    ]

    for i, r in enumerate(results, 1):
        j = r["job"]
        recruiter_cell = ""
        rec = j.get("recruiter")
        if rec and rec.get("name"):
            url = rec.get("linkedin_url") or ""
            name = rec["name"]
            recruiter_cell = f"[{name}]({url})" if url else name

        title = (j.get("title") or "")[:40]
        company = j.get("company") or ""
        location = j.get("location") or ""
        lines.append(
            f"| {i} | {r['score']}/10 | {r['recommendation']} | "
            f"{title} | {company} | {location} | {recruiter_cell} |"
        )

    lines.extend(["", "---", "", "## Detailed evaluations", ""])

    for i, r in enumerate(results, 1):
        j = r["job"]
        title = j.get("title") or ""
        company = j.get("company") or ""
        lines.extend([
            f"### {i}. {title} @ {company} — Score: {r['score']}/10 — {r['recommendation']}",
            f"**Location:** {j.get('location', '')}",
            f"**Seniority:** {j.get('seniority', '')}",
            f"**LinkedIn:** {j.get('linkedin_url', '')}",
        ])

        rec = j.get("recruiter")
        if rec and rec.get("name"):
            recruiter_line = f"**Recruiter:** {rec['name']}"
            if rec.get("title"):
                recruiter_line += f" — {rec['title']}"
            if rec.get("linkedin_url"):
                recruiter_line += f" — {rec['linkedin_url']}"
            lines.append(recruiter_line)

        lines.extend([
            "",
            r["evaluation"],
            "",
            "---",
            "",
        ])

    return "\n".join(lines)
