"""Project .env discovery.

Walks up from this file to find the project root and loads `.env`.
Used only by entry points (CLI scripts, bot/main.py) — library modules
should read `os.environ` directly, never call load_dotenv themselves.
"""
from pathlib import Path

from dotenv import load_dotenv

_ROOT_MARKERS = (".git", "pyproject.toml", "requirements.txt")
_MAX_PARENTS = 6


def load_project_env():
    """Find .env at project root by walking up from this file.

    Returns the Path to the loaded .env, or None if no .env was found
    before hitting a project-root marker.
    """
    here = Path(__file__).resolve()
    for i, parent in enumerate(here.parents):
        if i > _MAX_PARENTS:
            break
        env = parent / ".env"
        if env.exists():
            load_dotenv(env)
            return env
        if any((parent / marker).exists() for marker in _ROOT_MARKERS):
            return None
    return None
