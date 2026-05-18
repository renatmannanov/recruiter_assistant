"""
Notion screening runner — read candidates from Notion, screen with AI, write results back.

Uses config.yaml for field mapping — no hardcoded Notion schema.

Usage:
    # Dry run — show candidates, estimate cost
    python -m candidate_screener.run_notion \
      --config ../clients/sonia/config.yaml \
      --vacancy python \
      --dry-run

    # Run screening and write results back to Notion
    python -m candidate_screener.run_notion \
      --config ../clients/sonia/config.yaml \
      --vacancy python

    # Limit to first N candidates
    python -m candidate_screener.run_notion \
      --config ../clients/sonia/config.yaml \
      --vacancy python \
      --limit 2

    # Save markdown report alongside Notion update
    python -m candidate_screener.run_notion \
      --config ../clients/sonia/config.yaml \
      --vacancy python \
      --output test_results/screening_report.md
"""

import argparse
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

from core.utils.env import load_project_env
from ..core import (
    screen_candidate,
    parse_score,
    parse_recommendation,
)
from ..core.profile_cleaner import clean_profile
from ..sources.from_notion import (
    load_config,
    query_database,
    extract_candidate_info,
    max_iteration,
)
from ..sources.from_apify_urls import fetch_profiles, normalize_url
from ..sinks.to_notion import update_page
from ..sinks.to_markdown import write_report


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Notion AI screening — config-based pipeline"
    )
    parser.add_argument(
        "--config", "-c", required=True,
        help="Path to client config YAML (e.g. clients/sonia/config.yaml)"
    )
    parser.add_argument(
        "--vacancy", "-v", required=True,
        help="Vacancy key from config (e.g. python, ml, fullstack)"
    )
    parser.add_argument(
        "--model", "-m", default="gpt-4o",
        help="OpenAI model (default: gpt-4o)"
    )
    parser.add_argument(
        "--limit", "-l", type=int,
        help="Screen only first N candidates"
    )
    parser.add_argument(
        "--iteration", "-i", type=int,
        help="Iteration number to write to ai_iteration field (e.g. 1, 2, 3)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show candidates without screening or writing to Notion"
    )
    parser.add_argument(
        "--output", "-o",
        help="Also save Markdown report to file"
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    fields = config["fields"]

    vacancy_config = config["vacancies"].get(args.vacancy)
    if not vacancy_config:
        available = ", ".join(config["vacancies"].keys())
        print(f"Error: vacancy '{args.vacancy}' not found in config. Available: {available}", file=sys.stderr)
        sys.exit(1)

    # Load env
    load_project_env()

    notion_token = os.getenv("NOTION_SECRET")
    if not notion_token:
        print("Error: NOTION_SECRET not found in .env", file=sys.stderr)
        sys.exit(1)

    apify_token = os.getenv("APIFY_AI_TOKEN_V2") or os.getenv("APIFY_AI_TOKEN")
    if not apify_token and not args.dry_run:
        print("Error: APIFY_AI_TOKEN_V2 / APIFY_AI_TOKEN not found in .env", file=sys.stderr)
        sys.exit(1)

    openai_key = os.getenv("OPEN_AI_KEY")
    if not openai_key and not args.dry_run:
        print("Error: OPEN_AI_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    # Load vacancy + optional brief
    jd_path = vacancy_config.get("_jd_path")
    if not jd_path or not jd_path.exists():
        print(f"Error: JD file not found: {jd_path}", file=sys.stderr)
        sys.exit(1)
    vacancy_text = jd_path.read_text(encoding="utf-8").strip()

    brief_path = vacancy_config.get("_brief_path")
    brief_text = None
    if brief_path and brief_path.exists():
        brief_text = brief_path.read_text(encoding="utf-8").strip()

    # Query Notion
    filter_value = vacancy_config["filter_value"]
    print(f"=== {config['client']} / {args.vacancy} ===")
    print(f"  Database: {config['database_id']}")
    print(f"  Filter: {fields['vacancy_filter']} = {filter_value}")
    print(f"  JD: {jd_path}")
    print(f"  Brief: {brief_path or 'none'}")
    print(f"  Model: {args.model}")
    print()

    print(f"Querying Notion...")
    pages = query_database(
        notion_token,
        config["database_id"],
        fields["vacancy_filter"],
        filter_value,
    )
    candidates = [extract_candidate_info(p, fields) for p in pages]

    # Determine iteration value (auto or override)
    iteration_field = fields.get("write_iteration")
    if args.iteration is not None:
        iteration_value = args.iteration
        print(f"Iteration: {iteration_value} (override via --iteration)")
    elif iteration_field:
        iteration_value = max_iteration(pages, iteration_field) + 1
        print(f"Iteration: {iteration_value} (auto: max+1)")
    else:
        iteration_value = None
        print(f"Iteration: not set (no write_iteration field in config)")

    # Filter: must have LinkedIn URL
    with_url = [c for c in candidates if c["linkedin_url"]]
    without_url = [c for c in candidates if not c["linkedin_url"]]

    print(f"Found {len(candidates)} candidates, {len(with_url)} with LinkedIn URL")
    if without_url:
        print(f"  Skipping {len(without_url)} without URL: {[c['name'] for c in without_url]}")

    if args.limit:
        with_url = with_url[:args.limit]
        print(f"  Limited to first {args.limit}")

    print()
    for c in with_url:
        try:
            print(f"  {c['name']} | {c['linkedin_url']}")
        except UnicodeEncodeError:
            print(f"  {c['name'].encode('ascii', 'replace').decode()} | {c['linkedin_url']}")

    if args.dry_run:
        print(f"\n(dry run — no Apify calls, no screening, no Notion updates)")
        print(f"Est. Apify cost: ~${len(with_url) * 0.004:.2f} ({len(with_url)} profiles)")
        return

    # Fetch profiles via Apify
    urls = [c["linkedin_url"] for c in with_url]
    profile_index = fetch_profiles(apify_token, urls)
    print(f"  Got {len(profile_index)} profiles from Apify\n")

    # Match fetched profiles to candidates
    to_screen = []
    for c in with_url:
        norm = normalize_url(c["linkedin_url"])
        if norm in profile_index:
            to_screen.append((c, profile_index[norm]))
        else:
            print(f"  WARNING: No profile returned for {c['name']} ({c['linkedin_url']})")

    if not to_screen:
        print("No profiles to screen!")
        return

    # Screen candidates
    client = OpenAI(api_key=openai_key)
    total_tokens = 0

    print(f"Screening {len(to_screen)} candidates...\n")

    results = []
    for i, (c, profile) in enumerate(to_screen, 1):
        print(f"  [{i}/{len(to_screen)}] {c['name']}...", end=" ", flush=True)

        start = time.time()
        evaluation, usage = screen_candidate(
            client, vacancy_text, profile, args.model, internal_brief=brief_text,
        )
        elapsed = time.time() - start

        score = parse_score(evaluation)
        recommendation = parse_recommendation(evaluation)
        total_tokens += usage["total_tokens"]

        cleaned = clean_profile(profile)
        results.append({
            "page_id": c["page_id"],
            "name": c["name"],
            "linkedin_url": c["linkedin_url"],
            "headline": cleaned.get("headline", ""),
            "location": cleaned.get("location", ""),
            "score": score,
            "recommendation": recommendation,
            "evaluation": evaluation,
            "iteration": iteration_value,
        })

        print(f"Score: {score}/10 ({recommendation}) [{elapsed:.1f}s, {usage['total_tokens']} tok]")

    # Write results back to Notion
    print(f"\nWriting results to Notion...")
    for r in results:
        update_page(notion_token, r["page_id"], fields, r)
        print(f"  Updated: {r['name']} -> {r['score']}/10 ({r['recommendation']})")

    cost = total_tokens * 0.005 / 1000
    print(f"\nDone! Total tokens: {total_tokens:,}, est. cost: ~${cost:.2f}")

    # Optional: save markdown report
    if args.output:
        write_report(
            results,
            args.output,
            f"{config['client']}_{args.vacancy}",
            args.model,
            total_tokens,
        )
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
