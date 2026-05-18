"""Extract input text from Telegram messages and attachments.

v1 accepts plain text, .txt and .md only. PDF/DOCX parsing is a v2 item.

Input shapes:
- 1 source           -> (input_text, None)
- 2 sources          -> (input_text, brief_text)

When two files arrive, the brief is whichever filename contains 'brief'
(case-insensitive); otherwise the second one is treated as the brief.
"""

from dataclasses import dataclass

ALLOWED_EXTENSIONS = frozenset({".txt", ".md"})
MAX_FILE_SIZE = 1_000_000  # 1 MB


class ExtractionError(Exception):
    """Raised when input cannot be turned into (input_text, brief_text)."""


@dataclass
class FileInput:
    """A file the user sent: its name, decoded text and byte size."""

    filename: str
    content: str
    size: int


def _ext(filename: str) -> str:
    """Lowercased extension of a filename, including the dot ('' if none)."""
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def validate_file(file: FileInput) -> None:
    """Raise ExtractionError if a file is too big or an unsupported type."""
    if file.size > MAX_FILE_SIZE:
        raise ExtractionError(
            "file too big (>1 MB)"
        )
    ext = _ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ExtractionError(f"unsupported file type: {ext or '(no extension)'}")


def _is_brief_name(filename: str) -> bool:
    return "brief" in (filename or "").lower()


def extract_from_text(text: str) -> tuple[str, None]:
    """Plain text message -> (input_text, None). No brief possible."""
    text = (text or "").strip()
    if not text:
        raise ExtractionError("empty text")
    return text, None


def extract_from_files(files: list[FileInput]) -> tuple[str, str | None]:
    """1-2 files -> (input_text, brief_text|None).

    Each file must already be validated/decoded. Raises ExtractionError for
    0 files, >2 files, empty content, or unsupported types.
    """
    if not files:
        raise ExtractionError("no files")
    if len(files) > 2:
        raise ExtractionError("too many files (max 2)")

    for f in files:
        validate_file(f)
        if not f.content.strip():
            raise ExtractionError(f"file is empty: {f.filename}")

    if len(files) == 1:
        return files[0].content.strip(), None

    first, second = files
    # Brief is the file whose name says 'brief'; otherwise the 2nd file.
    if _is_brief_name(first.filename) and not _is_brief_name(second.filename):
        input_file, brief_file = second, first
    else:
        input_file, brief_file = first, second

    return input_file.content.strip(), brief_file.content.strip()
