"""
Clean raw Apify LinkedIn profile JSON for LLM screening.

Removes photos, logos, URLs, and other noise — keeps only data useful
for candidate evaluation.

Usage:
    # Preview cleaning on first profile
    python -m candidate_screener.profile_cleaner test_results/sonia_python_full.json --limit 1

    # Clean all profiles, save to file
    python -m candidate_screener.profile_cleaner test_results/sonia_python_full.json --output test_results/sonia_python_clean.json
"""

import argparse
import json
import sys
from pathlib import Path


def clean_experience(exp: dict) -> dict:
    """Extract useful fields from an experience entry."""
    result = {
        "position": exp.get("position"),
        "company": exp.get("companyName"),
        "duration": exp.get("duration"),
        "employment_type": exp.get("employmentType"),
        "workplace_type": exp.get("workplaceType"),
    }

    start = exp.get("startDate", {})
    end = exp.get("endDate", {})
    result["period"] = f"{start.get('text', '?')} — {end.get('text', '?')}"

    if exp.get("description"):
        result["description"] = exp["description"]
    if exp.get("skills"):
        result["skills"] = exp["skills"]

    location = exp.get("location")
    if location:
        result["location"] = location

    return {k: v for k, v in result.items() if v is not None}


def clean_education(edu: dict) -> dict:
    """Extract useful fields from an education entry."""
    result = {
        "school": edu.get("schoolName"),
        "degree": edu.get("degree"),
        "field_of_study": edu.get("fieldOfStudy"),
    }
    period = edu.get("period")
    if period:
        result["period"] = period

    return {k: v for k, v in result.items() if v is not None}


def clean_profile(profile: dict) -> dict:
    """Clean a single profile, keeping only screening-relevant data."""
    # Location
    location_raw = profile.get("location", {})
    if isinstance(location_raw, dict):
        parsed = location_raw.get("parsed", {})
        location = parsed.get("text") or location_raw.get("linkedinText", "")
    else:
        location = str(location_raw)

    result = {
        "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
        "linkedin_url": profile.get("linkedinUrl", ""),
        "headline": profile.get("headline", ""),
        "location": location,
        "about": profile.get("about", ""),
        "open_to_work": profile.get("openToWork", False),
    }

    # Experience
    experience = profile.get("experience", [])
    if experience:
        result["experience"] = [clean_experience(e) for e in experience]

    # Education
    education = profile.get("education", [])
    if education:
        result["education"] = [clean_education(e) for e in education]

    # Skills (just names)
    skills = profile.get("skills", [])
    if skills:
        result["skills"] = [s["name"] for s in skills if isinstance(s, dict) and s.get("name")]

    # Top skills (sometimes present as separate field)
    top_skills = profile.get("topSkills")
    if top_skills:
        result["top_skills"] = top_skills

    # Languages
    languages = profile.get("languages", [])
    if languages:
        result["languages"] = [
            {"name": l.get("name"), "proficiency": l.get("proficiency")}
            for l in languages
        ]

    # Certifications (just titles)
    certs = profile.get("certifications", [])
    if certs:
        result["certifications"] = [c.get("title") for c in certs if c.get("title")]

    # Projects (title + description)
    projects = profile.get("projects", [])
    if projects:
        result["projects"] = [
            {k: v for k, v in {
                "title": p.get("title"),
                "description": p.get("description"),
            }.items() if v}
            for p in projects
        ]

    return result


def main():
    parser = argparse.ArgumentParser(description="Clean Apify LinkedIn profiles for LLM screening")
    parser.add_argument("input", help="Path to raw JSON file with profiles")
    parser.add_argument("--output", "-o", help="Save cleaned JSON to file")
    parser.add_argument("--limit", "-l", type=int, help="Process only first N profiles")

    args = parser.parse_args()

    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.limit:
        raw = raw[:args.limit]

    cleaned = [clean_profile(p) for p in raw]

    output = json.dumps(cleaned, indent=2, ensure_ascii=False)

    # Stats
    raw_size = len(json.dumps(raw, ensure_ascii=False))
    clean_size = len(output)
    ratio = (1 - clean_size / raw_size) * 100

    print(f"Profiles: {len(cleaned)}", file=sys.stderr)
    print(f"Raw size:   {raw_size:,} chars", file=sys.stderr)
    print(f"Clean size: {clean_size:,} chars", file=sys.stderr)
    print(f"Reduction:  {ratio:.0f}%", file=sys.stderr)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
