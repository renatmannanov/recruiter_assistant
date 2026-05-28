"""
LinkedIn People Search via Apify (harvestapi/linkedin-profile-search).

Usage:
    # Search with keywords + location (recommended)
    python -m candidate_screener.linkedin_search --query "Python AND FastAPI AND Docker" --locations "Germany"

    # Search by job titles + location
    python -m candidate_screener.linkedin_search --titles "Senior Python Engineer" --locations "Germany"

    # Combined: keywords + titles + seniority + experience
    python -m candidate_screener.linkedin_search --query "Python AND FastAPI" --titles "Software Engineer" --locations "Germany" "Luxembourg" --seniority senior --experience 6-10 10+

    # Dry run — show params without spending credits
    python -m candidate_screener.linkedin_search --query "Python AND FastAPI" --locations "Germany" --dry-run

    # Save results to JSON
    python -m candidate_screener.linkedin_search --query "Python" --locations "Germany" --output results.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from apify_client import ApifyClient

from core.utils.env import load_project_env

ACTOR_ID = "harvestapi/linkedin-profile-search"

# Pulled out of the actor's stdout log — the actor prints e.g.
#   "Found 4510 profiles total for input ..."
# right after submitting the LinkedIn query. The HTTP API does not return
# this count directly, so we parse the log.
_TOTAL_FOUND_RE = re.compile(r"Found\s+(\d+)\s+profiles\s+total", re.IGNORECASE)


def _extract_total_found(apify_client: ApifyClient, run_id: str) -> int | None:
    """Read the actor log and pull out the 'Found N profiles total' line.

    Returns None if the log can't be read or the line isn't there — callers
    should treat this as 'unknown total' and fall back to len(items).
    """
    try:
        log_text = apify_client.log(run_id).get() or ""
    except Exception:
        return None
    m = _TOTAL_FOUND_RE.search(log_text)
    return int(m.group(1)) if m else None

SENIORITY_MAP = {
    "training": "100",
    "entry": "110",
    "senior": "120",
    "strategic": "130",
    "entry_mgr": "200",
    "manager": "210",
    "director": "220",
    "vp": "300",
    "cxo": "310",
    "owner": "320",
}

EXPERIENCE_MAP = {
    "<1": "1",
    "1-2": "2",
    "3-5": "3",
    "6-10": "4",
    "10+": "5",
}

# profileScraperMode values
MODE_SHORT = "Short"
MODE_FULL = "Full"
MODE_FULL_EMAIL = "Full + email search"


def search_linkedin_profiles(
    query: str = "",
    titles: list[str] | None = None,
    locations: list[str] | None = None,
    seniority_ids: list[str] | None = None,
    experience_ids: list[str] | None = None,
    exclude_titles: list[str] | None = None,
    profile_languages: list[str] | None = None,
    pages: int = 1,
    start_page: int = 1,
    mode: str = MODE_SHORT,
) -> tuple[list[dict], int]:
    """
    Search LinkedIn for people.

    Returns:
        Tuple of (list of profile dicts, total found count)
    """
    token = os.getenv("APIFY_AI_TOKEN_V2") or os.getenv("APIFY_AI_TOKEN")
    if not token:
        print("Error: APIFY_AI_TOKEN_V2 / APIFY_AI_TOKEN not found in .env", file=sys.stderr)
        sys.exit(1)

    client = ApifyClient(token)

    run_input = {
        "startPage": start_page,
        "takePages": pages,
        "profileScraperMode": mode,
    }

    if query:
        run_input["searchQuery"] = query
    if titles:
        run_input["currentJobTitles"] = titles
    if locations:
        run_input["locations"] = locations
    if seniority_ids:
        run_input["seniorityLevelIds"] = seniority_ids
    if experience_ids:
        run_input["yearsOfExperienceIds"] = experience_ids
    if exclude_titles:
        run_input["excludeCurrentJobTitles"] = exclude_titles
    if profile_languages:
        run_input["profileLanguages"] = profile_languages

    # Print search summary
    print("=== LinkedIn Search ===")
    if query:
        print(f"  Keywords: {query}")
    if titles:
        print(f"  Titles: {titles}")
    if locations:
        print(f"  Locations: {locations}")
    if seniority_ids:
        labels = [k for k, v in SENIORITY_MAP.items() if v in seniority_ids]
        print(f"  Seniority: {labels}")
    if experience_ids:
        labels = [k for k, v in EXPERIENCE_MAP.items() if v in experience_ids]
        print(f"  Experience: {labels}")
    if exclude_titles:
        print(f"  Exclude titles: {exclude_titles}")
    if profile_languages:
        print(f"  Profile languages: {profile_languages}")
    print(f"  Mode: {mode}")
    print(f"  Pages: {pages} (up to {pages * 25} results)")
    print("Running...\n")

    run = client.actor(ACTOR_ID).call(run_input=run_input)

    items = client.dataset(run["defaultDatasetId"]).list_items().items

    # Total LinkedIn matches for the query (not just what we scraped on this
    # page). Comes from the actor's log — see _extract_total_found docstring.
    total_found = _extract_total_found(client, run["id"])
    total = total_found if total_found is not None else len(items)

    return items, total


def format_short_profile(profile: dict) -> str:
    """Format a short profile for display."""
    name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
    headline = profile.get("headline", "").encode("ascii", "ignore").decode()
    location = profile.get("location", "")
    if isinstance(location, dict):
        location = location.get("linkedinText", "")
    url = profile.get("linkedinUrl", profile.get("profileUrl", ""))

    lines = [f"  {name}"]
    if headline:
        lines.append(f"  {headline}")
    if location:
        lines.append(f"  Location: {location}")
    if url:
        lines.append(f"  {url}")
    return "\n".join(lines)


def main():
    load_project_env()

    parser = argparse.ArgumentParser(
        description="Search LinkedIn profiles via Apify"
    )
    parser.add_argument(
        "--query", "-q", default="",
        help="Keyword search (supports boolean: 'Python AND FastAPI AND Docker')"
    )
    parser.add_argument(
        "--titles", "-t", nargs="+", default=None,
        help="Current job titles filter"
    )
    parser.add_argument(
        "--locations", "-l", nargs="+", default=["Germany"],
        help="Locations (default: Germany)"
    )
    parser.add_argument(
        "--seniority", "-s", nargs="+", default=None,
        choices=list(SENIORITY_MAP.keys()),
        help="Seniority level filter"
    )
    parser.add_argument(
        "--experience", "-e", nargs="+", default=None,
        choices=list(EXPERIENCE_MAP.keys()),
        help="Years of experience filter"
    )
    parser.add_argument(
        "--exclude-titles", nargs="+", default=None,
        help="Exclude these job titles"
    )
    parser.add_argument(
        "--languages", nargs="+", default=None,
        help="Profile languages filter: Russian English German French etc."
    )
    parser.add_argument(
        "--pages", "-p", type=int, default=1,
        help="Pages to scrape, 25 results/page (default: 1)"
    )
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Start from this page (default: 1)"
    )
    parser.add_argument(
        "--mode", "-m", default="Short",
        choices=["Short", "Full", "Full + email search"],
        help="Scrape mode (default: Short)"
    )
    parser.add_argument(
        "--output", "-o", help="Save results to JSON file"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show search params without running"
    )

    args = parser.parse_args()

    if not args.query and not args.titles:
        parser.error("At least --query or --titles is required")

    seniority_ids = [SENIORITY_MAP[s] for s in args.seniority] if args.seniority else None
    experience_ids = [EXPERIENCE_MAP[e] for e in args.experience] if args.experience else None

    if args.dry_run:
        print("=== DRY RUN ===")
        if args.query:
            print(f"  Keywords: {args.query}")
        if args.titles:
            print(f"  Titles: {args.titles}")
        print(f"  Locations: {args.locations}")
        if args.seniority:
            print(f"  Seniority: {args.seniority}")
        if args.experience:
            print(f"  Experience: {args.experience}")
        if args.exclude_titles:
            print(f"  Exclude titles: {args.exclude_titles}")
        if args.languages:
            print(f"  Profile languages: {args.languages}")
        print(f"  Mode: {args.mode}")
        print(f"  Pages: {args.pages} (up to {args.pages * 25} results)")
        print("  Cost: $0 (dry run)")
        return

    profiles, total = search_linkedin_profiles(
        query=args.query,
        titles=args.titles,
        locations=args.locations,
        seniority_ids=seniority_ids,
        experience_ids=experience_ids,
        exclude_titles=args.exclude_titles,
        profile_languages=args.languages,
        pages=args.pages,
        start_page=args.start_page,
        mode=args.mode,
    )

    # Save JSON first (before print which can fail on Windows encoding)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(profiles, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Saved {len(profiles)} profiles to {args.output}")

    print(f"\nFound {len(profiles)} profiles:\n")
    for i, p in enumerate(profiles, 1):
        try:
            print(f"{i}.")
            print(format_short_profile(p))
            print()
        except UnicodeEncodeError:
            name = p.get("firstName", "") + " " + p.get("lastName", "")
            print(f"  {name.encode('ascii', 'replace').decode()}")
            print(f"  {p.get('linkedinUrl', '')}\n")


if __name__ == "__main__":
    main()
