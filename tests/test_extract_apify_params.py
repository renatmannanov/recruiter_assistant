"""Tests for extract_apify_params() — step_11.5.

Parses the '## Apify params' block out of the LLM markdown into cleaned
locations/experience lists. The parser must be defensive: any malformed or
missing input degrades to empty lists, never raises (a parse failure must not
break boolean generation).
"""

from core.boolean_generator.generator import extract_apify_params


# The real format the LLM is instructed to emit (prompts_candidates.py:66-70).
FULL_OUTPUT = """\
## Boolean (LinkedIn keywords)
```
("ASR" OR "Speech Recognition") AND (Whisper OR Kaldi)
```

## Apify params
- locations: Germany, Luxembourg, Netherlands, Switzerland, Austria
- experience: 6-10, 10+
- exclude-titles: recruiter, HR, sales, consultant
- titles: (none — ASR roles span PhD/Research/CTO/Founder)

## Reasoning
- Boolean: 2 AND-groups.
- Apify: DACH+, 5+ years experience.
"""


def test_parses_real_format():
    params = extract_apify_params(FULL_OUTPUT)
    assert params["locations"] == [
        "Germany", "Luxembourg", "Netherlands", "Switzerland", "Austria",
    ]
    assert params["experience"] == ["6-10", "10+"]


def test_single_location():
    md = (
        "## Apify params\n"
        "- locations: Germany\n"
        "- experience: 3-5\n"
    )
    assert extract_apify_params(md) == {
        "locations": ["Germany"],
        "experience": ["3-5"],
    }


def test_no_apify_params_block():
    md = "## Boolean (LinkedIn keywords)\n```\n(\"Python\")\n```\n"
    assert extract_apify_params(md) == {"locations": [], "experience": []}


def test_empty_locations_value():
    md = (
        "## Apify params\n"
        "- locations: \n"
        "- experience: 6-10\n"
    )
    params = extract_apify_params(md)
    assert params["locations"] == []
    assert params["experience"] == ["6-10"]


def test_garbage_experience_dropped():
    # "5+" and "senior" are not in the allowed bucket set — dropped. "6-10"
    # survives.
    md = (
        "## Apify params\n"
        "- locations: France\n"
        "- experience: 5+, senior, 6-10\n"
    )
    params = extract_apify_params(md)
    assert params["locations"] == ["France"]
    assert params["experience"] == ["6-10"]


def test_all_experience_buckets_allowed():
    md = (
        "## Apify params\n"
        "- locations: Spain\n"
        "- experience: <1, 1-2, 3-5, 6-10, 10+\n"
    )
    assert extract_apify_params(md)["experience"] == [
        "<1", "1-2", "3-5", "6-10", "10+",
    ]


def test_region_grouping_kept_for_apify_to_filter():
    # We do NOT validate locations against a country dict — a region grouping
    # like "DACH" is passed through; Apify returns nothing rather than erroring.
    # Cleaning location quality is the LLM's job, not the parser's.
    md = "## Apify params\n- locations: DACH, EU\n- experience: 10+\n"
    assert extract_apify_params(md)["locations"] == ["DACH", "EU"]


def test_missing_experience_line():
    md = "## Apify params\n- locations: Germany\n"
    params = extract_apify_params(md)
    assert params["locations"] == ["Germany"]
    assert params["experience"] == []


def test_block_terminates_at_next_header():
    # A "Germany" mention in a later Reasoning section must not leak into
    # locations — the block must stop at the next "## " header.
    md = (
        "## Apify params\n"
        "- locations: Germany\n"
        "- experience: 10+\n"
        "## Reasoning\n"
        "- Apify: locations: France, Italy were considered but rejected.\n"
    )
    params = extract_apify_params(md)
    assert params["locations"] == ["Germany"]
    assert params["experience"] == ["10+"]


def test_empty_input_does_not_raise():
    assert extract_apify_params("") == {"locations": [], "experience": []}
