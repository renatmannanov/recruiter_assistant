"""
Discover new candidates: Apify search (Full mode) → dedup against Notion.

Pipeline:
1. Search LinkedIn via Apify in Full mode — returns full profiles with public slug URLs
2. Read existing candidates for this vacancy from Notion
3. Diff: keep only profiles whose URLs are NOT already in Notion
4. Save JSON for next step (run_local --push-to-notion)

Why Full and not Short+Scraper:
Short mode returns LinkedIn member-ID URLs (linkedin.com/in/ACwAA...) while Notion
stores public slug URLs (linkedin.com/in/john-doe). Dedup is impossible until URLs
are resolved to slug form, which requires fetching full profiles anyway. So we do
it in one Apify call instead of two.

Usage:
    # Dry run — show counts without spending Apify credits on full-fetch
    python -m candidate_screener.cli.discover \
      --config clients/sonia/config.yaml \
      --vacancy python \
      --query "Python AND FastAPI" \
      --locations Germany \
      --pages 1 \
      --dry-run

    # Real run — saves JSON of new full profiles
    python -m candidate_screener.cli.discover \
      --config clients/sonia/config.yaml \
      --vacancy python \
      --locations Germany Luxembourg \
      --experience 6-10 10+ \
      --pages 1 \
      --output candidate_screener/test_results/sonia_python_new.json

    # Without --query: reads boolean from clients/<client>/<vacancy>/boolean.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

from core.utils.env import load_project_env

from ..sources.from_apify_search import (
    search_linkedin_profiles,
    SENIORITY_MAP,
    EXPERIENCE_MAP,
    MODE_FULL,
)
from ..sources.from_apify_urls import normalize_url
from ..sources.from_notion import (
    load_config,
    query_database,
    extract_candidate_info,
)


def get_url(candidate: dict) -> str:
    """Profiles may have URL in linkedinUrl or profileUrl."""
    return candidate.get("linkedinUrl") or candidate.get("profileUrl") or ""


def read_default_boolean(config_path: str, vacancy_key: str) -> str:
    """Read boolean.md from clients/<client>/<vacancy>/boolean.md (next to config.yaml)."""
    config_dir = Path(config_path).parent
    boolean_path = config_dir / vacancy_key / "boolean.md"
    if not boolean_path.exists():
        raise SystemExit(
            f"No --query provided and no boolean.md at {boolean_path}\n"
            f"Either pass --query or generate boolean first via boolean_generator.generator"
        )
    return boolean_path.read_text(encoding="utf-8").strip()


def main():
    parser = argparse.ArgumentParser(
        description="Discover new candidates: Apify search + dedup against Notion + fetch full profiles"
    )
    parser.add_argument(
        "--config", "-c", required=True,
        help="Path to client config.yaml"
    )
    parser.add_argument(
        "--vacancy", "-v", required=True,
        help="Vacancy key from config (e.g. python, asr)"
    )
    parser.add_argument(
        "--query", "-q",
        help="Boolean query for LinkedIn keywords. If not set, reads <vacancy>/boolean.md"
    )
    parser.add_argument(
        "--titles", "-t", nargs="+",
        help="Job title filters (Apify currentJobTitles)"
    )
    parser.add_argument(
        "--locations", "-l", nargs="+",
        help="Location filters (e.g. Germany Luxembourg)"
    )
    parser.add_argument(
        "--experience", "-e", nargs="+",
        choices=list(EXPERIENCE_MAP.keys()),
        help="Years of experience (raw values: <1, 1-2, 3-5, 6-10, 10+)"
    )
    parser.add_argument(
        "--seniority", "-s", nargs="+",
        choices=list(SENIORITY_MAP.keys()),
        help="Seniority levels (raw values: training, entry, senior, ...)"
    )
    parser.add_argument(
        "--exclude-titles", nargs="+",
        help="Titles to exclude (e.g. recruiter HR sales)"
    )
    parser.add_argument(
        "--pages", "-p", type=int, default=1,
        help="Pages of search results (25 profiles per page). Default: 1"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output path for new profiles JSON"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show counts without fetching full profiles or saving"
    )

    args = parser.parse_args()

    # Validate output path requirement
    if not args.dry_run and not args.output:
        parser.error("--output is required (or use --dry-run)")

    # Env
    load_project_env()

    notion_token = os.getenv("NOTION_SECRET")
    if not notion_token:
        sys.exit("Error: NOTION_SECRET not found in .env")

    # Config + vacancy
    config = load_config(args.config)
    fields = config["fields"]
    vacancy_config = config["vacancies"].get(args.vacancy)
    if not vacancy_config:
        available = ", ".join(config["vacancies"].keys())
        sys.exit(f"Error: vacancy '{args.vacancy}' not in config. Available: {available}")
    filter_value = vacancy_config["filter_value"]

    # Boolean query
    query = args.query or read_default_boolean(args.config, args.vacancy)

    # Map raw experience/seniority → Apify IDs
    experience_ids = [EXPERIENCE_MAP[e] for e in args.experience] if args.experience else None
    seniority_ids = [SENIORITY_MAP[s] for s in args.seniority] if args.seniority else None

    # 1. Apify SEARCH — Full mode (one call, returns full profiles with slug URLs)
    print(f"=== {config['client']} / {args.vacancy} ===")
    print(f"  Filter: {fields['vacancy_filter']} = {filter_value}")
    print()

    search_results, total = search_linkedin_profiles(
        query=query,
        titles=args.titles,
        locations=args.locations,
        seniority_ids=seniority_ids,
        experience_ids=experience_ids,
        exclude_titles=args.exclude_titles,
        pages=args.pages,
        mode=MODE_FULL,
    )

    # 2. Read existing from Notion
    print(f"\nReading existing candidates from Notion...")
    pages = query_database(
        notion_token,
        config["database_id"],
        fields["vacancy_filter"],
        filter_value,
    )
    existing_urls = {
        normalize_url(extract_candidate_info(p, fields)["linkedin_url"])
        for p in pages
    }
    existing_urls.discard("")

    # 3. Diff (URLs from Full mode are public slugs, same format as Notion)
    new_candidates = [
        c for c in search_results
        if get_url(c) and normalize_url(get_url(c)) not in existing_urls
    ]
    skipped_no_url = sum(1 for c in search_results if not get_url(c))

    print(f"\nSearch: {len(search_results)} found (total ~{total}), "
          f"{len(existing_urls)} already in Notion, "
          f"{len(new_candidates)} new"
          + (f", {skipped_no_url} skipped (no URL)" if skipped_no_url else ""))

    if args.dry_run:
        for c in new_candidates[:10]:
            name = c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or "?"
            headline = (c.get("headline") or "")[:60]
            line = f"  {name} | {headline} | {get_url(c)}"
            print(line.encode("ascii", "replace").decode())
        if len(new_candidates) > 10:
            print(f"  ... and {len(new_candidates) - 10} more")
        print("(dry run — no file written)")
        return

    if not new_candidates:
        print("No new candidates — done.")
        return

    # 4. Save JSON (profiles are already full from Search Full mode)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(new_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(new_candidates)} new profiles to {output_path}")


if __name__ == "__main__":
    main()
