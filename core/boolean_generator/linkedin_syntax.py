"""
LinkedIn Boolean Search syntax rules and constraints.
Reference for the AI prompt and for validation.
"""

LINKEDIN_BOOLEAN_RULES = """
## LinkedIn Boolean Search Syntax

### Operators
- AND: Both terms must be present. LinkedIn applies AND by default between words.
- OR: Either term can be present. Must be UPPERCASE.
- NOT: Excludes term. Must be UPPERCASE. Example: NOT "project manager"
- Parentheses (): Group terms. Example: (Python OR Java) AND (Senior OR Lead)
- Quotes "": Exact phrase match. Example: "machine learning"

### LinkedIn-Specific Constraints
- Maximum ~1000 characters in the search box (LinkedIn Recruiter allows more)
- LinkedIn free search: limited filters, boolean works in the main search bar
- LinkedIn Premium: better filters, boolean in keyword field
- LinkedIn Recruiter: full boolean support, longer queries, saved searches

### Best Practices
- Use quotes for multi-word terms: "data engineer" not data engineer
- Group synonyms with OR: (Python OR Java OR "C++")
- Use parentheses for complex logic: (Senior OR Lead) AND ("data engineer" OR "data scientist")
- Put NOT at the end to exclude: ... NOT (recruiter OR HR OR sales)
- Keep it readable: one concept per parenthetical group
- Avoid over-nesting: max 2-3 levels of parentheses

### Common Pitfalls
- LinkedIn ignores AND/OR/NOT if lowercase — always UPPERCASE
- Too many terms = too narrow results. Start broad, narrow down.
- LinkedIn may silently truncate very long boolean strings
- Some special characters are stripped by LinkedIn
"""

LINKEDIN_SEARCH_FIELDS = {
    "keywords": "Main search bar — full boolean support",
    "title": "Current/past title — boolean supported",
    "company": "Current/past company — boolean supported",
    "location": "Geographic filter — use LinkedIn's built-in filter, not boolean",
    "industry": "Industry filter — use LinkedIn's built-in filter",
}


BOOLEAN_ANTIPATTERNS = """
## Common Mistakes (DON'T)

NEVER use literal years like "5 years" / "6 years" / "5+ years" in boolean.
   Reason: LinkedIn doesn't reliably surface these in search.
   Solution: use --experience param in discover (mapped to Apify yearsOfExperienceIds).

NEVER add MLOps / Docker / Kubernetes as hard AND keyword unless explicitly
   listed in brief Hard Filters.
   Reason: these are usually priority signals (deeper check by screener).
   Forcing them as AND filters out senior researchers who don't write
   infra in profile keywords.

NEVER mix title filter into boolean keywords — return as separate
   "titles:" recommendation in Apify params.
   Reason: title in keywords loses PhD Candidates, CTOs, Research Engineers,
   Founders — all valid candidates for senior roles.
   Solution: title goes to Apify --titles param (currentJobTitles), separate field.

NEVER produce more than 4 AND-groups in keywords.
   Reason: each AND cuts result count exponentially. >4 AND → <10 results.
   3-4 AND-groups max for narrow search, 2-3 for normal.

NEVER use lowercase and / or / not — LinkedIn ignores them silently.
   Always UPPERCASE: AND, OR, NOT.

NEVER add brief items that are "soft" / "nice-to-have" to boolean.
   Reason: those are for screener filter (post-search AI evaluation),
   not for LinkedIn search itself. Boolean should be the widest reasonable net.
"""
