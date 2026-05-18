"""Read candidates from a Notion database (config-based)."""

from pathlib import Path

import requests
import yaml


# --- Config ---


def load_config(config_path: str) -> dict:
    """Load and validate client config YAML.

    Resolves vacancy paths (jd, brief) relative to the config file directory.
    """
    config_file = Path(config_path)
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    config_dir = config_file.parent
    for vac_key, vac in config.get("vacancies", {}).items():
        if vac.get("jd"):
            vac["_jd_path"] = config_dir / vac["jd"]
        if vac.get("brief"):
            vac["_brief_path"] = config_dir / vac["brief"]

    return config


# --- Notion ---


def notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def query_database(
    token: str,
    database_id: str,
    filter_field: str,
    filter_value: str,
    filter_type: str = "multi_select",
) -> list[dict]:
    """Query pages from a Notion database with flexible filtering."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = notion_headers(token)

    if filter_type == "multi_select":
        body = {
            "page_size": 100,
            "filter": {
                "property": filter_field,
                "multi_select": {"contains": filter_value},
            },
        }
    elif filter_type == "select":
        body = {
            "page_size": 100,
            "filter": {
                "property": filter_field,
                "select": {"equals": filter_value},
            },
        }
    else:
        body = {"page_size": 100}

    pages = []
    has_more = True
    start_cursor = None

    while has_more:
        if start_cursor:
            body["start_cursor"] = start_cursor

        resp = requests.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        pages.extend(data["results"])
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    return pages


def parse_iteration(prop: dict) -> int | None:
    """Read ai_iteration value from a Notion page property dict.

    Supports rich_text and number types. Returns None if missing/unparseable.
    """
    if "number" in prop and prop["number"] is not None:
        try:
            return int(prop["number"])
        except (ValueError, TypeError):
            return None

    rich_text = prop.get("rich_text", [])
    if not rich_text:
        return None
    text = rich_text[0].get("plain_text", "").strip()
    try:
        return int(text)
    except ValueError:
        return None


def max_iteration(pages: list[dict], field_name: str) -> int:
    """Return max(ai_iteration) across pages, or 0 if all empty/unparseable."""
    values = []
    for page in pages:
        prop = page.get("properties", {}).get(field_name, {})
        parsed = parse_iteration(prop)
        if parsed is not None:
            values.append(parsed)
    return max(values) if values else 0


def extract_candidate_info(page: dict, fields: dict) -> dict:
    """Extract candidate info using field mapping from config."""
    props = page["properties"]

    # Name (title field)
    name_field = props.get(fields["name"], {})
    name_data = name_field.get("title", [])
    name = name_data[0]["plain_text"] if name_data else ""

    # LinkedIn URL
    url_field = props.get(fields["linkedin_url"], {})
    linkedin_url = url_field.get("url", "") or ""

    return {
        "page_id": page["id"],
        "name": name,
        "linkedin_url": linkedin_url,
    }
