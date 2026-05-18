"""Write screening results to Notion: update existing pages or create new ones."""

import requests

from ..sources.from_notion import notion_headers


def build_properties(fields: dict, result: dict) -> dict:
    """Build Notion properties dict from screening result + field mapping.

    Covers ai_* fields (status, score, comments, iteration). Identity fields
    (name, linkedin_url, vacancy_filter) are added separately by create_page —
    update_page doesn't touch them.
    """
    properties = {}

    if fields.get("write_status") and result.get("recommendation"):
        properties[fields["write_status"]] = {
            "select": {"name": result["recommendation"]}
        }

    if fields.get("write_score") and result.get("score") is not None:
        properties[fields["write_score"]] = {
            "number": result["score"]
        }

    if fields.get("write_comments") and result.get("evaluation"):
        comments = result["evaluation"]
        if len(comments) > 2000:
            comments = comments[:1997] + "..."
        properties[fields["write_comments"]] = {
            "rich_text": [{"type": "text", "text": {"content": comments}}]
        }

    if fields.get("write_iteration") and result.get("iteration"):
        properties[fields["write_iteration"]] = {
            "rich_text": [{"type": "text", "text": {"content": str(result["iteration"])}}]
        }

    return properties


def update_page(token: str, page_id: str, fields: dict, result: dict):
    """Update an existing Notion page with screening results."""
    properties = build_properties(fields, result)
    if not properties:
        return

    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = requests.patch(url, headers=notion_headers(token), json={"properties": properties})
    resp.raise_for_status()
    return resp.json()


def create_page(
    token: str,
    database_id: str,
    fields: dict,
    result: dict,
    vacancy_filter_value: str,
):
    """Create a new candidate page in a Notion database.

    `result` must include at minimum: name, linkedin_url.
    Optional ai_* fields (score, recommendation, evaluation, iteration) are
    written if present.

    `vacancy_filter_value` — value for fields["vacancy_filter"] multi_select
    (e.g. "Sonia_python") — couples candidate to a vacancy.
    """
    properties = build_properties(fields, result)

    if result.get("name"):
        properties[fields["name"]] = {
            "title": [{"type": "text", "text": {"content": result["name"]}}]
        }

    if result.get("linkedin_url"):
        properties[fields["linkedin_url"]] = {"url": result["linkedin_url"]}

    if vacancy_filter_value and fields.get("vacancy_filter"):
        properties[fields["vacancy_filter"]] = {
            "multi_select": [{"name": vacancy_filter_value}]
        }

    url = "https://api.notion.com/v1/pages"
    resp = requests.post(
        url,
        headers=notion_headers(token),
        json={"parent": {"database_id": database_id}, "properties": properties},
    )
    resp.raise_for_status()
    return resp.json()
