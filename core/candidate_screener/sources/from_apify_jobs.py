"""
LinkedIn Jobs Search via Apify (curious_coder/linkedin-jobs-scraper).

Mirror of from_apify_search.py but for job postings — used by the cv-to-jobs
pipeline. The actor takes LinkedIn job-search URLs (not raw boolean strings),
so this module also exposes a URL builder that maps our params to LinkedIn's
URL query parameters (f_E, f_TPR, f_WT, ...).

Usage:
    # Dry run — print URL only (no cost)
    python -m candidate_screener.sources.from_apify_jobs \\
      --query '"Speech Scientist" OR "ASR Engineer"' \\
      --locations "Berlin, Germany" \\
      --experience senior \\
      --dry-run

    # Real run (~$0.001/result; minimum 10 jobs)
    python -m candidate_screener.sources.from_apify_jobs \\
      --query '"Speech Scientist" OR "ASR Engineer"' \\
      --locations "Berlin, Germany" \\
      --experience senior \\
      --posted-within past_month \\
      --remote any \\
      --count 10 \\
      --output _baseline_cv_to_jobs/test_jobs_search.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from apify_client import ApifyClient

from core.utils.env import load_project_env

ACTOR_ID = "curious_coder/linkedin-jobs-scraper"

# Sanity cap. curious_coder charges per result (~$0.001). 10 = minimum allowed
# by the actor input schema. 50 ≈ $0.05 Apify + ~$0.5 OpenAI for screening,
# which is the typical full E2E run; anything above is opt-in via the flag.
MAX_COUNT_DEFAULT = 50


# LinkedIn experience levels — URL query param: f_E
# Includes mappings for cv_parser seniority values (entry/mid/senior/staff/principal)
# so an auto-derived experience from a CV doesn't silently fall through.
EXPERIENCE_MAP = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid": "3",        # cv_parser uses "mid" — alias for "associate"
    "senior": "4",
    "staff": "5",      # cv_parser may return this — closest LinkedIn level is "director"
    "principal": "5",  # same — map to "director"
    "director": "5",
    "executive": "6",
}

# LinkedIn employment types — URL query param: f_JT
EMPLOYMENT_MAP = {
    "full-time": "F",
    "part-time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
}

# LinkedIn "posted within" filter — URL query param: f_TPR (seconds)
POSTED_WITHIN_MAP = {
    "past_24h": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
}

# LinkedIn workplace type — URL query param: f_WT
# 1 = Onsite, 2 = Remote, 3 = Hybrid
REMOTE_MAP = {
    "yes": "2",   # remote-first
    "no": "1",    # onsite-only
    "any": None,  # no filter
}


def build_linkedin_jobs_url(
    query: str,
    location: str | None = None,
    experience: str | None = None,
    employment_type: str | None = None,
    posted_within: str = "past_month",
    remote: str = "any",
) -> str:
    """Build a LinkedIn Jobs search URL with filters.

    Reference: https://www.linkedin.com/jobs/search/?keywords=...&location=...&f_E=...

    Args:
        query: boolean keyword string (will be URL-quoted).
        location: free-form location string ("Berlin, Germany"). One URL per
            location is built by the caller — this builder accepts a single one.
        experience: key in EXPERIENCE_MAP. Unknown values are dropped silently.
        employment_type: key in EMPLOYMENT_MAP. Unknown values dropped silently.
        posted_within: key in POSTED_WITHIN_MAP. Defaults to past_month.
        remote: "yes" | "no" | "any". "any" means no filter.
    """
    base = "https://www.linkedin.com/jobs/search/"
    params = [f"keywords={quote_plus(query)}"]

    if location:
        params.append(f"location={quote_plus(location)}")

    if experience:
        code = EXPERIENCE_MAP.get(experience.lower())
        if code:
            params.append(f"f_E={code}")

    if employment_type:
        code = EMPLOYMENT_MAP.get(employment_type.lower())
        if code:
            params.append(f"f_JT={code}")

    if posted_within in POSTED_WITHIN_MAP:
        params.append(f"f_TPR={POSTED_WITHIN_MAP[posted_within]}")

    remote_code = REMOTE_MAP.get(remote, None)
    if remote_code:
        params.append(f"f_WT={remote_code}")

    return f"{base}?{'&'.join(params)}"


def search_linkedin_jobs(
    query: str,
    locations: list[str] | None = None,
    experience: str | None = None,
    employment_type: str | None = None,
    posted_within: str = "past_month",
    remote: str = "any",
    count: int = 10,
    confirm_large_run: bool = False,
    scrape_company: bool = True,
) -> tuple[list[dict], int]:
    """Run curious_coder/linkedin-jobs-scraper and return raw job items.

    Args:
        query: boolean keyword string.
        locations: list of location strings — one search URL per location.
            None means a single URL with no location filter.
        experience: see EXPERIENCE_MAP keys.
        employment_type: see EMPLOYMENT_MAP keys.
        posted_within: see POSTED_WITHIN_MAP keys.
        remote: see REMOTE_MAP keys.
        count: number of jobs to scrape (actor minimum: 10).
        confirm_large_run: required to bypass MAX_COUNT_DEFAULT.
        scrape_company: include company details (longer run, more useful output).

    Returns:
        (list of raw job dicts from Apify, total count).
    """
    if count < 10:
        raise ValueError(f"count={count} below curious_coder minimum (10)")

    if count > MAX_COUNT_DEFAULT and not confirm_large_run:
        raise ValueError(
            f"count={count} exceeds MAX_COUNT_DEFAULT={MAX_COUNT_DEFAULT} "
            f"(~${count * 0.001:.3f} Apify alone, plus OpenAI screening). "
            f"Pass confirm_large_run=True (or --confirm-large-run) if intentional."
        )

    token = os.getenv("APIFY_AI_TOKEN_V2") or os.getenv("APIFY_AI_TOKEN")
    if not token:
        print("Error: APIFY_AI_TOKEN_V2 / APIFY_AI_TOKEN not found in .env",
              file=sys.stderr)
        sys.exit(1)

    client = ApifyClient(token)

    # Build one URL per location. None means "no location filter" — single URL.
    location_list = locations or [None]
    urls = [
        build_linkedin_jobs_url(
            query=query,
            location=loc,
            experience=experience,
            employment_type=employment_type,
            posted_within=posted_within,
            remote=remote,
        )
        for loc in location_list
    ]

    run_input = {
        "urls": urls,
        "count": count,
        "scrapeCompany": scrape_company,
    }

    print("=== LinkedIn Jobs Search ===")
    print(f"  Query: {query}")
    print(f"  Locations: {location_list}")
    print(f"  Experience: {experience or 'any'}")
    print(f"  Employment: {employment_type or 'any'}")
    print(f"  Posted within: {posted_within}")
    print(f"  Remote: {remote}")
    print(f"  Count: {count} (~${count * 0.001:.3f})")
    print(f"  URLs:")
    for u in urls:
        print(f"    {u}")
    print("Running...\n")

    run = client.actor(ACTOR_ID).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return items, len(items)


def format_short_job(job: dict) -> str:
    """One-line job summary for stdout."""
    title = job.get("title", "<no title>")
    company = job.get("companyName", "<no company>")
    location = job.get("location", "")
    return f"  {title} @ {company} ({location})"


def main():
    load_project_env()

    parser = argparse.ArgumentParser(description="Search LinkedIn Jobs via Apify (curious_coder)")
    parser.add_argument("--query", "-q", required=True, help="Boolean keyword search string")
    parser.add_argument(
        "--locations", "-l", nargs="+", default=None,
        help="One or more location strings; one search URL per location"
    )
    parser.add_argument(
        "--experience", "-e", choices=list(EXPERIENCE_MAP.keys()),
        help="Experience level filter (accepts cv_parser values: entry/mid/senior/staff/principal)"
    )
    parser.add_argument(
        "--employment", choices=list(EMPLOYMENT_MAP.keys()),
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
        help=f"Number of jobs to scrape (min 10, default 10, max without --confirm-large-run: {MAX_COUNT_DEFAULT})"
    )
    parser.add_argument(
        "--confirm-large-run", action="store_true",
        help=f"Allow --count > {MAX_COUNT_DEFAULT} (budget protection bypass)"
    )
    parser.add_argument(
        "--no-company", action="store_true",
        help="Skip scrapeCompany (faster, less data)"
    )
    parser.add_argument("--output", "-o", help="Save raw JSON to file")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without running")

    args = parser.parse_args()

    if args.dry_run:
        urls = [
            build_linkedin_jobs_url(
                args.query, loc, args.experience, args.employment,
                args.posted_within, args.remote,
            )
            for loc in (args.locations or [None])
        ]
        print("=== DRY RUN ===")
        for u in urls:
            print(f"  URL: {u}")
        print(f"  Cost: $0 (dry run)")
        return

    jobs, total = search_linkedin_jobs(
        query=args.query,
        locations=args.locations,
        experience=args.experience,
        employment_type=args.employment,
        posted_within=args.posted_within,
        remote=args.remote,
        count=args.count,
        confirm_large_run=args.confirm_large_run,
        scrape_company=not args.no_company,
    )

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(jobs, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Saved {len(jobs)} jobs to {args.output}")

    print(f"\nFound {total} jobs:\n")
    for i, j in enumerate(jobs, 1):
        try:
            print(f"{i}.")
            print(format_short_job(j))
        except UnicodeEncodeError:
            print(f"  <encoding error: {j.get('title', '?')}>")


if __name__ == "__main__":
    main()
