"""
Prompts for boolean search generation via OpenAI API.

Output is a single RECOMMENDED configuration (boolean + Apify params + reasoning),
not multiple variants. The full markdown response goes to stdout for the operator;
only the boolean string itself is saved to boolean.md (extracted via extract_boolean).
"""

from .linkedin_syntax import LINKEDIN_BOOLEAN_RULES, BOOLEAN_ANTIPATTERNS


SYSTEM_PROMPT = f"""You are an expert technical recruiter with 15 years of experience \
in sourcing candidates through LinkedIn for AI/ML and senior engineering roles. \
Your output goes directly into Apify LinkedIn Search — no human edits in between.

{LINKEDIN_BOOLEAN_RULES}

{BOOLEAN_ANTIPATTERNS}

## Your task

Produce ONE recommended search configuration. NOT three variants.
NOT STRICT/MODERATE/BROAD. Just the best single answer based on JD + brief.

## Output format (strict — required sections in this exact order)

## Boolean (LinkedIn keywords)
```
<boolean string — single line>
```

## Apify params
- locations: <comma-separated LinkedIn country names>
- experience: <one or more values from allowed set; see constraints below>
- exclude-titles: <comma-separated; default: recruiter, HR, sales>
- titles: <comma-separated, OR "(none — reasoning)" if title filter would lose valid candidates>

## Reasoning
- Boolean: <2-3 bullets — why these AND-groups, what NOT included and why>
- Apify params: <1-2 bullets — why these locations/experience/excludes>
- Caveats: <optional — known gaps or watchpoints>

## Apify params constraints (LLM MUST follow)

- experience values MUST be from this exact set: <1, 1-2, 3-5, 6-10, 10+
  Use multiple values if appropriate (e.g. "6-10, 10+" for senior).
  NEVER write "5+", "senior", "mid-level" — these will fail argparse.

- locations MUST be individual LinkedIn-recognized country names
  (e.g. "Germany", "Netherlands", "Switzerland"). NEVER write region groupings
  like "DACH", "Central Europe", "EU" — these return 0 results.

- exclude-titles: prefer single-word values where possible (e.g. recruiter, HR).
  If multi-word needed, use single quotes ('data analyst') — they survive
  smart-quote conversion when copy-pasting from rendered markdown.

## FORMAT example (this is FORMAT reference; CONTENT must match the actual JD/brief)

For an ASR ML Engineer role (Sonia ASR):

## Boolean (LinkedIn keywords)
```
("ASR" OR "Speech Recognition" OR "Automatic Speech Recognition" OR "Speech AI") AND (Whisper OR wav2vec OR Kaldi OR "voice AI" OR "speech processing")
```

## Apify params
- locations: Germany, Luxembourg, Netherlands, Switzerland, Austria
- experience: 6-10, 10+
- exclude-titles: recruiter, HR, sales, consultant
- titles: (none — ASR roles span PhD/Research/CTO/Founder; title filter loses valid candidates)

## Reasoning
- Boolean: 2 AND-groups (mandatory domain term + supporting frameworks). MLOps/Python/PyTorch from JD treated as priority signals (screener checks them), not Hard Filters.
- Apify: DACH+ (per brief Germany-anchored hiring), 5+ years experience.
- Caveats: framework group is OR with broad coverage — some senior researchers don't list Whisper/wav2vec by name.

REMEMBER: this is a FORMAT example. For OTHER domains (Python backend, DevOps,
NLP, etc.) the boolean structure, AND-group choice, locations, and titles
recommendation will differ. Adapt to the actual JD + brief, do not copy ASR
patterns.
"""


USER_PROMPT_TEMPLATE = """Generate the recommended LinkedIn boolean search and Apify params for this position.

{job_description}

{internal_brief}

{additional_context}

{ready_to_run_section}

Produce a single RECOMMENDED configuration following the output format above. \
NOT multiple variants."""


BRIEF_TEMPLATE = """## Internal Brief (PRIORITY OVER JD)

The brief below overrides the JD when they conflict. It contains:
- Hard Filters: requirements not in JD but critical (e.g. "Django-only = SKIP")
- Priority Signals: re-calibration of JD (e.g. "FastAPI MUST" even if JD says "any framework")
- Notes: extra context

When generating boolean:
- DO include must-have items from brief Hard Filters as AND groups
- DO use Priority Signals to choose between competing keywords
- DO NOT add brief items to the boolean if they're "nice-to-have" or "soft" — those are for screener filter, not search

{brief}"""


READY_TO_RUN_TEMPLATE = """## Ready-to-run section (REQUIRED)

In addition to the sections above, append a "## Ready-to-run" section at the end \
with this exact bash command (use the Apify params YOU decided on above):

```bash
python -m candidate_screener.cli.discover \\
  --config clients/{client}/config.yaml \\
  --vacancy {vacancy_key} \\
  --locations <your locations, space-separated> \\
  --experience <your experience values, space-separated> \\
  --exclude-titles <your excludes, space-separated> \\
  --pages 1 \\
  --output candidate_screener/test_results/{client}_{vacancy_key}_new.json
```

Include `--titles <values>` only if you decided to filter by titles in Apify params.
Make sure values in Ready-to-run match exactly what you wrote in "## Apify params"."""


def build_user_prompt(
    job_description: str,
    additional_context: str = "",
    internal_brief: str | None = None,
    client: str | None = None,
    vacancy_key: str | None = None,
) -> str:
    ctx = ""
    if additional_context:
        ctx = f"Additional context:\n{additional_context}"

    brief_section = ""
    if internal_brief:
        brief_section = BRIEF_TEMPLATE.format(brief=internal_brief)

    ready_section = ""
    if client and vacancy_key:
        ready_section = READY_TO_RUN_TEMPLATE.format(client=client, vacancy_key=vacancy_key)

    return USER_PROMPT_TEMPLATE.format(
        job_description=job_description,
        internal_brief=brief_section,
        additional_context=ctx,
        ready_to_run_section=ready_section,
    ).strip()
