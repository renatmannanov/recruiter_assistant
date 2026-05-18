"""Tests for bot.extractors — text/file extraction into (input, brief)."""

import pytest

from bot.extractors import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    ExtractionError,
    FileInput,
    extract_from_files,
    extract_from_text,
    validate_file,
)


def _file(name: str, content: str = "x") -> FileInput:
    return FileInput(filename=name, content=content, size=len(content))


# ----------------------------------------------------------------------- text

def test_extract_from_text():
    text, brief = extract_from_text("  a job description  ")
    assert text == "a job description"
    assert brief is None


def test_extract_from_text_empty_raises():
    with pytest.raises(ExtractionError):
        extract_from_text("   ")


# ------------------------------------------------------------- file validation

@pytest.mark.parametrize("ext", sorted(ALLOWED_EXTENSIONS))
def test_allowed_extensions_pass(ext):
    validate_file(_file(f"vacancy{ext}"))  # must not raise


@pytest.mark.parametrize("name", ["resume.pdf", "jd.docx", "data.json", "noext"])
def test_unsupported_extensions_rejected(name):
    with pytest.raises(ExtractionError, match="unsupported file type"):
        validate_file(_file(name))


def test_oversized_file_rejected():
    big = FileInput(filename="vacancy.md", content="x", size=MAX_FILE_SIZE + 1)
    with pytest.raises(ExtractionError, match="too big"):
        validate_file(big)


# -------------------------------------------------------------- single file

def test_one_file_no_brief():
    text, brief = extract_from_files([_file("vacancy.md", "the JD")])
    assert text == "the JD"
    assert brief is None


def test_empty_file_rejected():
    with pytest.raises(ExtractionError, match="empty"):
        extract_from_files([_file("vacancy.md", "   ")])


# --------------------------------------------------------------- two files

def test_two_files_second_is_brief_by_order():
    files = [_file("a.md", "the JD"), _file("b.md", "the brief")]
    text, brief = extract_from_files(files)
    assert text == "the JD"
    assert brief == "the brief"


def test_two_files_brief_detected_by_name_first():
    """A 'brief'-named file is the brief even when sent first."""
    files = [_file("brief.md", "the brief"), _file("vacancy.md", "the JD")]
    text, brief = extract_from_files(files)
    assert text == "the JD"
    assert brief == "the brief"


def test_two_files_brief_detected_by_name_case_insensitive():
    files = [_file("vacancy.md", "the JD"), _file("My_BRIEF.txt", "the brief")]
    text, brief = extract_from_files(files)
    assert text == "the JD"
    assert brief == "the brief"


def test_three_files_rejected():
    files = [_file("a.md"), _file("b.md"), _file("c.md")]
    with pytest.raises(ExtractionError, match="too many"):
        extract_from_files(files)


def test_no_files_rejected():
    with pytest.raises(ExtractionError, match="no files"):
        extract_from_files([])


def test_unsupported_file_among_two_rejected():
    files = [_file("vacancy.md", "JD"), _file("brief.pdf", "brief")]
    with pytest.raises(ExtractionError, match="unsupported"):
        extract_from_files(files)
