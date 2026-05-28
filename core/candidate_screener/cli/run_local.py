"""
Local screening runner — JSON profiles + vacancy file → Markdown report.

Usage:
    # Screen 1 candidate (for prompt tuning)
    python -m candidate_screener.run_local \
      --profiles test_results/sonia_python_full.json \
      --vacancy ../clients/sonia/python/vacancy.md \
      --brief ../clients/sonia/python/brief.md \
      --limit 1

    # Dry run — show stats, estimate cost
    python -m candidate_screener.run_local \
      --profiles test_results/sonia_python_full.json \
      --vacancy ../clients/sonia/python/vacancy.md \
      --dry-run

    # Screen all, save to markdown
    python -m candidate_screener.run_local \
      --profiles test_results/sonia_python_full.json \
      --vacancy ../clients/sonia/python/vacancy.md \
      --brief ../clients/sonia/python/brief.md \
      --output test_results/sonia_python_screening.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from core.utils.env import load_project_env
from ..core import screen_candidates
from ..core.profile_cleaner import clean_profile
from ..sources.from_json import load_profiles


def main():
    load_project_env()

    parser = argparse.ArgumentParser(description="Local AI screening: JSON profiles vs vacancy")
    parser.add_argument(
        "--profiles", "-p", required=True,
        help="Path to JSON file with Apify profiles"
    )
    parser.add_argument(
        "--vacancy", "-v", required=True,
        help="Path to vacancy text file"
    )
    parser.add_argument(
        "--brief", "-b",
        help="Path to internal brief file (markdown) — overrides JD when conflicting"
    )
    parser.add_argument("--output", "-o", help="Save Markdown report to file")
    parser.add_argument("--limit", "-l", type=int, help="Screen only first N candidates")
    parser.add_argument(
        "--model", "-m", default="gpt-4o",
        help="OpenAI model (default: gpt-4o)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show stats without running screening"
    )
    parser.add_argument(
        "--config", help="Path to client config.yaml (required for --push-to-notion)"
    )
    parser.add_argument(
        "--vacancy-key",
        help="Vacancy key in config (required for --push-to-notion, e.g. python)"
    )
    parser.add_argument(
        "--push-to-notion", action="store_true",
        help="After screening, create new pages in Notion using --config + --vacancy-key"
    )

    args = parser.parse_args()

    if args.push_to_notion and (not args.config or not args.vacancy_key):
        parser.error("--push-to-notion requires --config and --vacancy-key")

    # Load data
    profiles = load_profiles(args.profiles)
    vacancy_text = Path(args.vacancy).read_text(encoding="utf-8").strip()
    brief_text = Path(args.brief).read_text(encoding="utf-8").strip() if args.brief else None

    if args.limit:
        profiles = profiles[:args.limit]

    # Pre-screening dedup against Notion (only when pushing — saves OpenAI cost)
    existing_urls: set[str] = set()
    if args.push_to_notion:
        from ..sources.from_notion import load_config, query_database, extract_candidate_info
        from ..sources.from_apify_urls import normalize_url

        notion_token = os.getenv("NOTION_SECRET")
        if not notion_token:
            print("Error: NOTION_SECRET not found in .env", file=sys.stderr)
            sys.exit(1)

        cfg = load_config(args.config)
        nfields = cfg["fields"]
        vac = cfg["vacancies"].get(args.vacancy_key)
        if not vac:
            available = ", ".join(cfg["vacancies"].keys())
            print(f"Error: vacancy '{args.vacancy_key}' not in config. Available: {available}", file=sys.stderr)
            sys.exit(1)

        existing_pages = query_database(
            notion_token, cfg["database_id"], nfields["vacancy_filter"], vac["filter_value"],
        )
        existing_urls = {
            normalize_url(extract_candidate_info(p, nfields)["linkedin_url"])
            for p in existing_pages
        }
        existing_urls.discard("")

        before = len(profiles)
        profiles = [
            p for p in profiles
            if normalize_url(p.get("linkedinUrl") or p.get("profileUrl") or "") not in existing_urls
        ]
        skipped_pre = before - len(profiles)
        if skipped_pre:
            print(f"Pre-screening dedup: {skipped_pre} profiles already in Notion, skipping")

        if not profiles:
            print("All profiles already in Notion — nothing to screen.")
            return

    # Estimate tokens (~4 chars per token)
    vacancy_tokens = len(vacancy_text) // 4
    avg_profile_tokens = sum(
        len(json.dumps(clean_profile(p), ensure_ascii=False)) for p in profiles
    ) // (4 * len(profiles))
    est_tokens_per_call = vacancy_tokens + avg_profile_tokens + 500  # system prompt
    est_total = est_tokens_per_call * len(profiles)
    est_cost = est_total * 0.005 / 1000

    vacancy_name = Path(args.vacancy).stem

    print(f"=== Screening: {vacancy_name} ===")
    print(f"  Profiles: {len(profiles)}")
    print(f"  Brief: {args.brief or 'none'}")
    print(f"  Model: {args.model}")
    print(f"  Est. tokens/call: ~{est_tokens_per_call:,}")
    print(f"  Est. total tokens: ~{est_total:,}")
    print(f"  Est. cost: ~${est_cost:.2f}")

    if args.dry_run:
        print("  (dry run — no API calls)")
        return

    # Init OpenAI
    api_key = os.getenv("OPEN_AI_KEY")
    if not api_key:
        print("Error: OPEN_AI_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    print(f"\nScreening {len(profiles)} candidates...\n")

    def _print_progress(i, total, name, score, recommendation, usage_total):
        line = f"  [{i}/{total}] {name}... Score: {score}/10 ({recommendation}) [{usage_total} tok]"
        print(line.encode("ascii", "replace").decode())

    screening = screen_candidates(
        client=client,
        profiles=profiles,
        vacancy_text=vacancy_text,
        brief_text=brief_text,
        vacancy_name=Path(args.vacancy).stem,
        model=args.model,
        on_progress=_print_progress,
    )
    results = screening["results"]
    total_tokens = screening["total_tokens"]
    report = screening["report_md"]

    # Optional: push results to Notion as new pages
    # Pre-screening dedup already filtered out existing — this is a final safety check
    # (e.g. if someone added a candidate manually between dedup and push).
    if args.push_to_notion:
        from ..sources.from_notion import max_iteration
        from ..sources.from_apify_urls import normalize_url
        from ..sinks.to_notion import create_page

        # cfg / nfields / vac / existing_pages / existing_urls / notion_token
        # were initialized in the pre-screening dedup block above
        filter_value = vac["filter_value"]

        iteration_field = nfields.get("write_iteration")
        if iteration_field:
            iteration = max_iteration(existing_pages, iteration_field) + 1
        else:
            print("WARNING: 'write_iteration' field not in config — ai_iteration will not be written")
            iteration = None

        print(f"\nPushing to Notion (iteration {iteration})...")
        created_count = 0
        skipped_count = 0
        for r in results:
            url_norm = normalize_url(r.get("linkedin_url", ""))
            if url_norm and url_norm in existing_urls:
                msg = f"  SKIPPED: {r['name']} already in Notion ({r['linkedin_url']})"
                print(msg.encode("ascii", "replace").decode())
                skipped_count += 1
                continue

            r["iteration"] = iteration
            try:
                create_page(notion_token, cfg["database_id"], nfields, r, filter_value)
                msg = f"  Created: {r['name']} -> {r['score']}/10 ({r['recommendation']})"
                print(msg.encode("ascii", "replace").decode())
                created_count += 1
                if url_norm:
                    existing_urls.add(url_norm)
            except Exception as e:
                msg = f"  FAILED: {r['name']} - {e}"
                print(msg.encode("ascii", "replace").decode(), file=sys.stderr)

        print(f"\nNotion: {created_count} created, {skipped_count} skipped (already exist)")

    print(f"\n{'=' * 40}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Est. cost: ~${total_tokens * 0.005 / 1000:.2f}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report saved to {args.output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(f"\n{report}")


if __name__ == "__main__":
    main()
