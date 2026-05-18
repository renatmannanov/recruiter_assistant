"""Fetch full LinkedIn profiles from Apify by a list of LinkedIn URLs."""

from apify_client import ApifyClient


APIFY_SCRAPER_ACTOR = "harvestapi/linkedin-profile-scraper"


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.rstrip("/").lower()
    if "?" in url:
        url = url.split("?")[0]
    return url


def fetch_profiles(
    apify_token: str,
    linkedin_urls: list[str],
) -> dict[str, dict]:
    """Fetch full profiles from Apify by LinkedIn URLs.

    Returns a dict keyed by normalized URL → profile JSON.
    """
    if not linkedin_urls:
        return {}

    client = ApifyClient(apify_token)

    run_input = {
        "urls": linkedin_urls,
        "profileScraperMode": "Profile details no email ($4 per 1k)",
    }

    print(f"  Fetching {len(linkedin_urls)} profiles via Apify...", flush=True)
    run = client.actor(APIFY_SCRAPER_ACTOR).call(run_input=run_input)
    items = client.dataset(run["defaultDatasetId"]).list_items().items

    result = {}
    for item in items:
        url = item.get("linkedinUrl", "")
        if url:
            result[normalize_url(url)] = item

    return result
