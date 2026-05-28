"""Pure discover — Apify search, no Notion, no dedup, no config.yaml.

CLI flow (`cli/discover.py`) keeps its Notion-based dedup. The bot flow uses
this function and deduplicates against SQLite afterwards.

The result is intentionally small: raw Apify profiles plus a few counters.
Persistence (writing raw_apify.json, DB dedup, report.md) is the caller's
responsibility.
"""

from ..sources.from_apify_search import MODE_FULL, search_linkedin_profiles


# Apify Search Full pricing — ~$0.20 per page of 25 profiles. See
# discover_pipeline memory note. Real per-run cost lives in the Apify run
# object; wiring that through is tracked in BACKLOG.md.
_APIFY_COST_PER_PAGE_USD = 0.20


def discover_candidates(
    boolean: str,
    locations: list[str] | None = None,
    pages: int = 1,
) -> dict:
    """Run an Apify Full search and return raw profiles.

    Args:
        boolean: LinkedIn boolean query (the contents of boolean.md).
        locations: optional location filter (e.g. ["Germany", "Luxembourg"]).
            For v1 the bot does not parse locations out of the boolean — it
            passes None. See BACKLOG.md.
        pages: pages of 25 profiles. Default 1.

    Returns:
        {
            "profiles": list[dict],   # raw Apify Full profiles
            "found_count": int,
            "cost_usd": float,        # rough estimate, see note above
        }
    """
    profiles, total_found = search_linkedin_profiles(
        query=boolean,
        locations=locations,
        pages=pages,
        mode=MODE_FULL,
    )
    return {
        "profiles": profiles,
        "found_count": len(profiles),     # what we scraped this run
        "total_found": total_found,       # total LinkedIn matches for the query
        "cost_usd": pages * _APIFY_COST_PER_PAGE_USD,
    }


def get_profile_url(profile: dict) -> str:
    """Apify Full profiles use 'linkedinUrl'; older shapes used 'profileUrl'."""
    return profile.get("linkedinUrl") or profile.get("profileUrl") or ""
