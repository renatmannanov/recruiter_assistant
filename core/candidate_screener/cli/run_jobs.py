"""CLI: CV -> Apify Jobs Search -> JD-vs-CV screening -> Markdown report.

Mirror of cli/run_local.py for the cv-to-jobs pipeline.

Pipeline:
1. Load CV from candidates/<name>/cv.md and parse via cv_parser.
2. Load boolean from candidates/<name>/boolean.md (or use --query).
3. Apify Jobs search via curious_coder/linkedin-jobs-scraper with auto-derived
   params (locations from CV, experience from CV seniority).
4. Clean each job, screen against the CV via screen_job().
5. Write markdown report to candidates/<name>/jobs_results.md.

Usage:
    cd services/recruiter_assistant
    python -m candidate_screener.cli.run_jobs --candidate test_python
    python -m candidate_screener.cli.run_jobs --candidate test_python --limit 3
    python -m candidate_screener.cli.run_jobs --candidate test_python --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from core.utils.env import load_project_env
from ..core.cv_parser import parse_cv
from ..core.job_cleaner import clean_job
from ..core.report import format_jobs_report
from ..core.response_parser import parse_score, parse_recommendation
from ..core.screener import screen_job
from ..sources.from_apify_jobs import (
    search_linkedin_jobs,
    EXPERIENCE_MAP,
    EMPLOYMENT_MAP,
    POSTED_WITHIN_MAP,
    REMOTE_MAP,
)


def resolve_candidate_dir(args) -> Path:
    """Resolve candidate folder from --candidate or --candidate-dir.

    --candidate <name> resolves to candidates/<name>/ relative to CWD.
    PIPELINE_cv_to_jobs.md documents that run_jobs is called from services/recruiter_assistant/.
    """
    if args.candidate_dir:
        path = Path(args.candidate_dir)
    elif args.candidate:
        path = Path("candidates") / args.candidate
    else:
        raise ValueError("Either --candidate or --candidate-dir is required")

    if not path.exists():
        raise FileNotFoundError(f"Candidate directory not found: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="CV -> Apify Jobs Search -> AI screening -> Markdown report"
    )

    parser.add_argument(
        "--candidate", "-c",
        help="Candidate folder name in candidates/ (CWD-relative)"
    )
    parser.add_argument(
        "--candidate-dir",
        help="Direct path to a candidate folder (alternative to --candidate)"
    )

    parser.add_argument(
        "--query", "-q",
        help="Override boolean string (else reads candidates/<name>/boolean.md)"
    )
    parser.add_argument(
        "--locations", "-l", nargs="+",
        help="Override search locations (default: CV's current_location)"
    )
    parser.add_argument(
        "--experience", "-e",
        choices=list(EXPERIENCE_MAP.keys()),
        help="Override experience filter (default: derived from CV seniority)"
    )
    parser.add_argument(
        "--employment",
        choices=list(EMPLOYMENT_MAP.keys()),
        help="Employment type filter"
    )
    parser.add_argument(
        "--posted-within", default="past_month",
        choices=list(POSTED_WITHIN_MAP.keys()),
        help="Posted-within filter (default: past_month)"
    )
    parser.add_argument(
        "--remote", default="any", choices=list(REMOTE_MAP.keys()),
        help="Remote filter: yes / no / any (default: any)"
    )
    parser.add_argument(
        "--count", "-n", type=int, default=10,
        help="Number of jobs to scrape (min 10, default 10)"
    )
    parser.add_argument(
        "--confirm-large-run", action="store_true",
        help="Allow --count above MAX_COUNT_DEFAULT"
    )
    parser.add_argument(
        "--limit", type=int,
        help="Screen only the first N scraped jobs (for cheaper tests)"
    )
    parser.add_argument("--model", "-m", default="gpt-4o")
    parser.add_argument(
        "--output", "-o",
        help="Override output path (default: candidates/<name>/jobs_results.md)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse CV, show search params, do not call Apify or LLM"
    )

    args = parser.parse_args()

    # === 1. Resolve paths ===
    cand_dir = resolve_candidate_dir(args)
    cv_path = cand_dir / "cv.md"
    brief_path = cand_dir / "brief.md"
    boolean_path = cand_dir / "boolean.md"
    output_path = Path(args.output) if args.output else cand_dir / "jobs_results.md"

    if not cv_path.exists():
        print(f"Error: CV not found at {cv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"=== run_jobs: {cand_dir.name} ===")
    print(f"  CV: {cv_path}")
    print(f"  Brief: {brief_path if brief_path.exists() else 'none'}")
    print(f"  Boolean: {boolean_path if boolean_path.exists() else 'none (will require --query)'}")
    print(f"  Output: {output_path}")
    print()

    # === 2. Parse CV ===
    print("Parsing CV...")
    cv = parse_cv(cv_path)
    print(f"  Name: {cv.get('name', '?')}")
    print(f"  Seniority: {cv.get('seniority', '?')}")
    print(f"  Stack: {cv.get('primary_stack', [])[:5]}")
    print(f"  Location: {cv.get('current_location', '?')}")
    print()

    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else None

    # === 3. Determine search params ===
    if args.query:
        query = args.query
    elif boolean_path.exists():
        query = boolean_path.read_text(encoding="utf-8").strip()
    else:
        print(f"Error: no --query provided and {boolean_path} not found.", file=sys.stderr)
        print("Run boolean_generator first or pass --query explicitly.", file=sys.stderr)
        sys.exit(1)

    locations = args.locations
    if not locations and cv.get("current_location"):
        locations = [cv["current_location"]]

    experience = args.experience or cv.get("seniority")

    print("Search params:")
    print(f"  Query: {query}")
    print(f"  Locations: {locations}")
    print(f"  Experience: {experience}")
    print(f"  Posted within: {args.posted_within}")
    print(f"  Remote: {args.remote}")
    print(f"  Count: {args.count}")
    if args.limit:
        print(f"  (will screen only first {args.limit} after scraping)")
    print()

    if args.dry_run:
        print("(dry run — no Apify, no screening)")
        return

    # === 4. Apify Jobs search ===
    raw_jobs, total = search_linkedin_jobs(
        query=query,
        locations=locations,
        experience=experience,
        employment_type=args.employment,
        posted_within=args.posted_within,
        remote=args.remote,
        count=args.count,
        confirm_large_run=args.confirm_large_run,
    )

    if not raw_jobs:
        print("No jobs found. Exiting.")
        return

    # Archive this iteration into <candidate>/runs/<timestamp>/.
    # Latest report is also copied into <candidate>/jobs_results.md for quick access.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = cand_dir / "runs" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_path = run_dir / "raw_jobs.json"
    raw_path.write_text(
        json.dumps(raw_jobs, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Snapshot the boolean as a standalone file too — easier to diff
    # across iterations than digging it out of search_params.json.
    (run_dir / "boolean.md").write_text(query, encoding="utf-8")

    print(f"Archived raw Apify dump: {raw_path}")

    # Persist the search params for this iteration so it can be replayed.
    params = {
        "timestamp": timestamp,
        "query": query,
        "locations": locations,
        "experience": experience,
        "employment_type": args.employment,
        "posted_within": args.posted_within,
        "remote": args.remote,
        "count": args.count,
        "limit": args.limit,
        "model": args.model,
    }
    (run_dir / "search_params.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    if args.limit:
        raw_jobs = raw_jobs[:args.limit]
        print(f"Limited to first {args.limit} jobs for screening\n")

    # === 5. Clean + screen each job ===
    cleaned_jobs = [clean_job(j) for j in raw_jobs]

    load_project_env()
    api_key = os.getenv("OPEN_AI_KEY")
    if not api_key:
        print("Error: OPEN_AI_KEY not in .env", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    print(f"Screening {len(cleaned_jobs)} jobs...\n")

    results = []
    total_tokens = 0

    for i, job in enumerate(cleaned_jobs, 1):
        title_short = (job.get("title") or "<no title>")[:50]
        company = job.get("company") or "<no company>"
        try:
            print(f"  [{i}/{len(cleaned_jobs)}] {title_short} @ {company}...", end=" ", flush=True)
        except UnicodeEncodeError:
            print(f"  [{i}/{len(cleaned_jobs)}] <encoding-issue> @ {company}...",
                  end=" ", flush=True)

        start = time.time()
        evaluation, usage = screen_job(
            client=client,
            job=job,
            cv_structured=cv,
            candidate_brief=brief_text,
            model=args.model,
        )
        elapsed = time.time() - start

        score = parse_score(evaluation)
        rec = parse_recommendation(evaluation)
        total_tokens += usage["total_tokens"]

        results.append({
            "job": job,
            "score": score,
            "recommendation": rec,
            "evaluation": evaluation,
        })

        print(f"Score: {score}/10 ({rec}) [{elapsed:.1f}s, {usage['total_tokens']} tok]")

    # === 6. Write report ===
    cv_summary = (
        f"**{cv.get('name', '?')}** — {cv.get('headline', '')}\n\n"
        f"Stack: {', '.join(cv.get('primary_stack', [])[:5])}\n\n"
        f"Seniority: {cv.get('seniority', '?')} | YoE: {cv.get('years_experience', '?')}\n\n"
        f"Location: {cv.get('current_location', '?')}"
    )

    report = format_jobs_report(
        candidate_name=cand_dir.name,
        cv_summary=cv_summary,
        results=results,
        model=args.model,
        total_tokens=total_tokens,
    )

    # Archived per-run copy (history) + latest copy at the candidate root.
    archive_report_path = run_dir / "jobs_results.md"
    archive_report_path.write_text(report, encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    # Also archive cleaned + scored results as JSON, so the screening can be
    # re-rendered (or re-screened with a different prompt) without a new Apify call.
    results_json = [
        {
            "job": r["job"],
            "score": r["score"],
            "recommendation": r["recommendation"],
            "evaluation": r["evaluation"],
        }
        for r in results
    ]
    (run_dir / "screening_results.json").write_text(
        json.dumps(results_json, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Cost estimate per blended gpt-4o pricing (matches format_jobs_report).
    cost = total_tokens * 10.0 / 1_000_000

    print(f"\n{'=' * 40}")
    print(f"Run archive: {run_dir}")
    print(f"Latest report: {output_path}")
    print(f"Total tokens: {total_tokens:,}, est. cost: ~${cost:.2f}")

    go_count = sum(1 for r in results if r["recommendation"] == "GO")
    maybe_count = sum(1 for r in results if r["recommendation"] == "MAYBE")
    skip_count = sum(1 for r in results if r["recommendation"] == "SKIP")
    print(f"GO: {go_count} | MAYBE: {maybe_count} | SKIP: {skip_count}")


if __name__ == "__main__":
    main()
