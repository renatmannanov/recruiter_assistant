"""
Boolean Search Generator — generates LinkedIn boolean search strings from JDs or CVs.

Two targets:
- target=candidates (default for clients/* paths): JD → boolean for people search
- target=jobs       (default for candidates/* paths): CV → boolean for job search

Output strategy (same for both targets):
- Full markdown response (Boolean + Apify params + Reasoning + Ready-to-run) prints to stdout.
- Only the boolean string itself is saved to <source_dir>/boolean.md (one plain line, no markdown).
- This keeps boolean.md compatible with discover.py / run_jobs.py which read it as a query.

Usage:
    # vacancy → candidates (existing flow)
    python -m boolean_generator.generator clients/sonia/asr/vacancy.md --brief clients/sonia/asr/brief.md

    # CV → jobs (new flow, target auto-detected from candidates/ path)
    python -m boolean_generator.generator candidates/test_python/cv.md --brief candidates/test_python/brief.md

    # Free-text fallback (target defaults to candidates)
    python -m boolean_generator.generator --text "Senior Python Developer, ML, Kubernetes, Europe"
"""

import argparse
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

from core.utils.env import load_project_env
from .prompts_candidates import (
    SYSTEM_PROMPT as CANDIDATES_SYSTEM_PROMPT,
    build_user_prompt as build_candidates_prompt,
)
from .prompts_jobs import (
    SYSTEM_PROMPT as JOBS_SYSTEM_PROMPT,
    build_user_prompt as build_jobs_prompt,
)


def parse_path_for_target(source_path: Path) -> tuple[str | None, str | None, str | None]:
    """Parse clients/<client>/<vacancy>/* or candidates/<candidate>/* paths.

    Returns (target, id1, id2):
        clients/<client>/<vacancy>/...  -> ("candidates", client, vacancy_key)
        candidates/<candidate>/...      -> ("jobs", candidate, None)
        unrecognized                    -> (None, None, None)

    Uses the LAST occurrence of "candidates" / "clients" — protects against the
    keyword appearing higher in the directory tree.
    """
    parts = source_path.resolve().parts

    # Prefer "candidates" if both appear (it's the more specific context).
    if "candidates" in parts:
        idx = len(parts) - 1 - parts[::-1].index("candidates")
        if idx + 1 < len(parts):
            return ("jobs", parts[idx + 1], None)

    if "clients" in parts:
        idx = len(parts) - 1 - parts[::-1].index("clients")
        if idx + 2 < len(parts):
            return ("candidates", parts[idx + 1], parts[idx + 2])

    return (None, None, None)


def extract_boolean(llm_output: str) -> str:
    """Extract boolean string from LLM markdown response.

    Looks for the first code block after a "## Boolean" header and returns
    its content (without backticks). Falls back to the full output if no
    code block matched (defensive — should not happen if LLM follows format).
    """
    match = re.search(
        r"##\s*Boolean[^\n]*\n+```[a-z]*\n(.+?)\n```",
        llm_output,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return llm_output.strip()


def generate_boolean_search(
    *,
    target: str,
    source_text: str,
    cv_structured: dict | None = None,
    brief: str | None = None,
    additional_context: str = "",
    candidate_or_client: str | None = None,
    vacancy_key: str | None = None,
    model: str = "gpt-4o",
) -> str:
    """Generate boolean search via OpenAI. Returns full markdown response.

    Args:
        target: "candidates" (vacancy → people) or "jobs" (CV → job postings).
        source_text: JD text (target=candidates) or raw CV text (target=jobs).
        cv_structured: parsed CV dict from cv_parser.parse_cv(). Required when
            target=jobs.
        brief: optional brief markdown — internal brief (candidates) or
            candidate brief (jobs).
        additional_context: free-form extra context.
        candidate_or_client: candidate folder name (jobs) or client name (candidates).
        vacancy_key: vacancy folder name. Used only for target=candidates.
        model: OpenAI model.
    """
    openai_client = OpenAI(api_key=os.getenv("OPEN_AI_KEY"))

    if target == "jobs":
        if cv_structured is None:
            raise ValueError("cv_structured required for target=jobs")
        system = JOBS_SYSTEM_PROMPT
        user = build_jobs_prompt(
            cv_structured=cv_structured,
            cv_text=source_text,
            candidate_brief=brief,
            additional_context=additional_context,
            candidate_name=candidate_or_client,
        )
    elif target == "candidates":
        system = CANDIDATES_SYSTEM_PROMPT
        user = build_candidates_prompt(
            source_text,
            additional_context,
            brief,
            client=candidate_or_client,
            vacancy_key=vacancy_key,
        )
    else:
        raise ValueError(f"Unknown target: {target!r}. Expected 'candidates' or 'jobs'.")

    response = openai_client.chat.completions.create(
        model=model,
        max_tokens=2000,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    return response.choices[0].message.content


def main():
    load_project_env()

    parser = argparse.ArgumentParser(
        description="Generate LinkedIn boolean search strings from a JD or CV"
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("file", nargs="?", help="Path to JD or CV file")
    input_group.add_argument("--text", "-t", help="JD or CV as inline text")
    input_group.add_argument(
        "--stdin", action="store_true", help="Read JD or CV from stdin"
    )

    parser.add_argument(
        "--target",
        choices=["candidates", "jobs"],
        default=None,
        help="What to search for. Auto-detected by path: "
             "clients/* -> candidates, candidates/* -> jobs. "
             "Falls back to 'candidates' for --text / --stdin.",
    )
    parser.add_argument(
        "--brief", "-b",
        help="Path to internal brief (target=candidates) or candidate brief "
             "(target=jobs) — markdown. Overrides JD/CV when conflicting.",
    )
    parser.add_argument(
        "--context", "-c", default="", help="Additional free-form context"
    )
    parser.add_argument(
        "--model", "-m", default="gpt-4o", help="OpenAI model (default: gpt-4o)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Save boolean string to file (default: <source_dir>/boolean.md)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate even if boolean.md already exists"
    )

    args = parser.parse_args()

    # Read source text (JD or CV)
    if args.stdin:
        source_text = sys.stdin.read().strip()
    elif args.text:
        source_text = args.text
    else:
        source_text = Path(args.file).read_text(encoding="utf-8").strip()

    if not source_text:
        print("Error: empty source text", file=sys.stderr)
        sys.exit(1)

    # Resolve output path: explicit --output > <source_dir>/boolean.md > stdout-only
    output_path: Path | None = None
    if args.output:
        output_path = Path(args.output)
    elif args.file:
        output_path = Path(args.file).parent / "boolean.md"

    # Reuse existing if not --force
    if output_path and output_path.exists() and not args.force:
        print(f"Boolean already exists: {output_path}")
        print()
        print(output_path.read_text(encoding="utf-8"))
        print()
        print("(use --force to regenerate)")
        return

    # Auto-detect target by path; CLI flag wins if explicit
    target = args.target
    candidate_or_client = None
    vacancy_key = None
    if args.file:
        target_auto, id1, id2 = parse_path_for_target(Path(args.file))
        if target is None:
            target = target_auto or "candidates"
        if target == "candidates":
            candidate_or_client = id1
            vacancy_key = id2
        elif target == "jobs":
            candidate_or_client = id1
    else:
        # No file path -> default to candidates (legacy behaviour for --text/--stdin)
        if target is None:
            target = "candidates"

    # Load brief if provided
    brief = None
    if args.brief:
        brief = Path(args.brief).read_text(encoding="utf-8").strip()

    # For target=jobs: parse the CV first (requires step_1 cv_parser)
    cv_structured = None
    if target == "jobs":
        if not args.file:
            print("Error: target=jobs requires a CV file path "
                  "(--text/--stdin not supported for jobs target)",
                  file=sys.stderr)
            sys.exit(1)
        from candidate_screener.core.cv_parser import parse_cv
        cv_structured = parse_cv(args.file)

    print(f"Generating boolean search (target={target})...\n")

    result = generate_boolean_search(
        target=target,
        source_text=source_text,
        cv_structured=cv_structured,
        brief=brief,
        additional_context=args.context,
        candidate_or_client=candidate_or_client,
        vacancy_key=vacancy_key,
        model=args.model,
    )

    # Print rich output (operator copies Ready-to-run from here)
    print(result)

    # Save ONLY the boolean string to file (compatible with discover.py / run_jobs.py)
    if output_path:
        boolean_only = extract_boolean(result)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(boolean_only, encoding="utf-8")
        print(f"\nSaved boolean string to {output_path}")


if __name__ == "__main__":
    main()
