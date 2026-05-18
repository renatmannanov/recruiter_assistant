"""Parse structured fields from AI screening response text."""


def parse_score(response_text: str) -> int:
    """Extract score from AI response."""
    for line in response_text.split("\n"):
        if line.strip().startswith("SCORE:"):
            try:
                return int(line.split(":")[1].strip().split("/")[0].strip())
            except (ValueError, IndexError):
                pass
    return 0


def parse_recommendation(response_text: str) -> str:
    """Extract recommendation from AI response."""
    for line in response_text.split("\n"):
        if line.strip().startswith("RECOMMENDATION:"):
            rec = line.split(":")[1].strip().upper()
            if "GO" in rec and "MAYBE" not in rec:
                return "GO"
            elif "MAYBE" in rec:
                return "MAYBE"
            elif "SKIP" in rec:
                return "SKIP"
    return "?"
