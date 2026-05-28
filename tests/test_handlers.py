"""Tests for bot.handlers — command routing against mocked Telegram objects.

These cover /cancel, /status, the unknown-command and no-session replies,
and that a running pipeline does not block other handlers (async check).
A live polling test in Telegram complements this; here we mock python-
telegram-bot's Update/Context so the logic is exercised without a network.

The `db` fixture comes from conftest.py and points at a per-test PG schema.
"""

import asyncio
import json

import pytest

from bot import auth, handlers, replies
from bot.state_machine import SessionStep


@pytest.fixture
def whitelisted(tmp_path, monkeypatch):
    """Whitelist user 423915315 for the duration of a test."""
    path = tmp_path / "whitelist.json"
    path.write_text(json.dumps({
        "users": [{"telegram_user_id": 423915315, "display_name": "Renat"}]
    }), encoding="utf-8")
    monkeypatch.setenv("WHITELIST_PATH", str(path))
    auth.reload_whitelist()
    yield 423915315
    auth.reload_whitelist()


# ----------------------------------------------------------- Telegram mocks

class FakeMessage:
    """Captures reply_text calls instead of hitting Telegram."""

    def __init__(self, text=None):
        self.text = text
        self.media_group_id = None
        self.document = None
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUser:
    def __init__(self, uid, name="Renat"):
        self.id = uid
        self.full_name = name


class FakeChat:
    def __init__(self, cid):
        self.id = cid


class FakeUpdate:
    def __init__(self, uid, text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.effective_message = FakeMessage(text)


class FakeApp:
    def __init__(self, db):
        self.bot_data = {"db": db}


class FakeContext:
    def __init__(self, db):
        self.application = FakeApp(db)


def _last_reply(update: FakeUpdate) -> str:
    return update.effective_message.replies[-1]


# --------------------------------------------------------------------- auth

async def test_unauthorized_user_blocked(db, whitelisted):
    update = FakeUpdate(uid=111111)  # not whitelisted
    await handlers.cmd_start(update, FakeContext(db))
    assert _last_reply(update) == replies.UNAUTHORIZED


async def test_start_creates_user(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_start(update, FakeContext(db))
    assert await db.get_user(whitelisted) is not None
    assert _last_reply(update) == replies.WELCOME


# ------------------------------------------------------------------ /status

async def test_status_no_session(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_status(update, FakeContext(db))
    assert _last_reply(update) == replies.STATUS_NO_SESSION


async def test_status_with_active_session(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    sid = await db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_status(update, FakeContext(db))
    reply = _last_reply(update)
    assert str(sid) in reply
    assert "vacancy_to_candidates" in reply


# ------------------------------------------------------------------ /cancel

async def test_cancel_nothing_to_cancel(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_cancel(update, FakeContext(db))
    assert _last_reply(update) == replies.NOTHING_TO_CANCEL


async def test_cancel_active_session(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    sid = await db.create_session(whitelisted, "cv_to_jobs")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_cancel(update, FakeContext(db))
    assert _last_reply(update) == replies.SESSION_CANCELLED
    assert (await db.get_session(sid))["step"] == SessionStep.CANCELLED.value
    # The cancelled session is no longer "active".
    assert await db.get_active_session(whitelisted) is None


async def test_refind_cancels_previous_session(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    old = await db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_refind_candidate(update, FakeContext(db))
    assert (await db.get_session(old))["step"] == SessionStep.CANCELLED.value
    new = await db.get_active_session(whitelisted)
    assert new["pipeline_type"] == "cv_to_jobs"


# ------------------------------------------------------------- unknown / text

async def test_unknown_command(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_unknown(update, FakeContext(db))
    assert _last_reply(update) == replies.UNKNOWN_COMMAND


async def test_text_without_session(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted, text="some random text")
    await handlers.on_text(update, FakeContext(db))
    assert _last_reply(update) == replies.NO_SESSION


async def test_text_in_waiting_input_creates_vacancy_and_pending_boolean(
    db, whitelisted, monkeypatch
):
    """JD text in WAITING_INPUT must create a manual vacancy, store the
    LLM-generated boolean in sessions.pending_boolean, and link the session
    to the vacancy."""
    await db.upsert_user(whitelisted, "Renat")
    sid = await db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted, text="Senior Python role")

    async def fake_generate_boolean(input_text, brief_text, pipeline_type):
        return "(\"Python\") AND (\"Senior\")"
    monkeypatch.setattr(handlers.pipelines, "generate_boolean", fake_generate_boolean)

    await handlers.on_text(update, FakeContext(db))

    session = await db.get_session(sid)
    assert session["step"] == SessionStep.WAITING_BOOLEAN_CONFIRM.value
    assert session["vacancy_id"] is not None
    assert session["search_id"] is None  # not yet — created on confirm
    assert session["pending_boolean"] == "(\"Python\") AND (\"Senior\")"

    vacancy = await db.get_vacancy(session["vacancy_id"])
    assert vacancy["source"] == "manual"
    assert vacancy["jd_text"] == "Senior Python role"
    assert vacancy["created_by_user_id"] == whitelisted


async def test_confirm_word_creates_search_unchanged(
    db, whitelisted, monkeypatch
):
    """`ок` after boolean generation must create a search row with the
    pending boolean and clear pending_boolean. original_boolean is NULL
    because the user did not edit."""
    await db.upsert_user(whitelisted, "Renat")
    sid = await db.create_session(whitelisted, "vacancy_to_candidates")

    async def fake_gen(*a, **k):
        return "(Python)"
    monkeypatch.setattr(handlers.pipelines, "generate_boolean", fake_gen)
    # Block the background pipeline kick-off so it doesn't run for real.
    monkeypatch.setattr(handlers, "_kick_off_pipeline", lambda *a, **k: None)

    # Step 1: arrive at WAITING_BOOLEAN_CONFIRM.
    await handlers.on_text(
        FakeUpdate(uid=whitelisted, text="JD here"), FakeContext(db),
    )
    # Step 2: user confirms.
    await handlers.on_text(
        FakeUpdate(uid=whitelisted, text="ок"), FakeContext(db),
    )

    session = await db.get_session(sid)
    assert session["step"] == SessionStep.RUNNING.value
    assert session["pending_boolean"] is None
    assert session["search_id"] is not None
    search = await db.get_search(session["search_id"])
    assert search["boolean_text"] == "(Python)"
    assert search["original_boolean"] is None
    assert search["vacancy_id"] == session["vacancy_id"]


async def test_edited_boolean_creates_search_with_original(
    db, whitelisted, monkeypatch
):
    """A non-confirm reply is the user's edited boolean; the LLM's text
    moves into searches.original_boolean for audit."""
    await db.upsert_user(whitelisted, "Renat")
    await db.create_session(whitelisted, "vacancy_to_candidates")

    async def fake_gen(*a, **k):
        return "(Python)"
    monkeypatch.setattr(handlers.pipelines, "generate_boolean", fake_gen)
    monkeypatch.setattr(handlers, "_kick_off_pipeline", lambda *a, **k: None)

    await handlers.on_text(FakeUpdate(uid=whitelisted, text="JD"), FakeContext(db))
    await handlers.on_text(
        FakeUpdate(uid=whitelisted, text="(Python) AND (async)"),
        FakeContext(db),
    )

    session = await db.get_active_session(whitelisted)
    # RUNNING is not "active" in get_active_session's filter — fetch by id.
    sessions = await db._query_all(
        "SELECT * FROM sessions WHERE user_id = $1 ORDER BY id DESC LIMIT 1",
        whitelisted,
    )
    s = sessions[0]
    search = await db.get_search(s["search_id"])
    assert search["boolean_text"] == "(Python) AND (async)"
    assert search["original_boolean"] == "(Python)"


# ---------------------------------------------------------- async non-blocking

async def test_status_responds_while_pipeline_running(db, whitelisted, monkeypatch):
    """A long pipeline must not block /status — the run handler is a task."""
    await db.upsert_user(whitelisted, "Renat")
    sid = await db.create_session(whitelisted, "vacancy_to_candidates")
    await db.update_session(sid, step=SessionStep.RUNNING.value)

    # Simulate a slow background pipeline.
    async def slow_pipeline():
        await asyncio.sleep(1.0)

    pipeline_task = asyncio.create_task(slow_pipeline())

    # /status must return immediately, well before the pipeline finishes.
    update = FakeUpdate(uid=whitelisted)
    await asyncio.wait_for(
        handlers.cmd_status(update, FakeContext(db)), timeout=0.3
    )
    assert not pipeline_task.done()  # pipeline still running
    await pipeline_task

    reply = _last_reply(update)
    assert str(sid) in reply
