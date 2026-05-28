"""Tests for bot.handlers — command routing against mocked Telegram objects.

These cover /cancel, /status, the unknown-command and no-session replies,
and that a running pipeline does not block other handlers (async check).
A live polling test in Telegram complements this; here we mock python-
telegram-bot's Update/Context so the logic is exercised without a network.
"""

import asyncio
import json

import pytest

from bot import auth, handlers, replies
from bot.state_machine import SessionStep
from db.client import DB


@pytest.fixture
def db(tmp_path):
    d = DB(str(tmp_path / "test.db"))
    d.initialize_from_schema()
    yield d
    d.close()


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

def test_unauthorized_user_blocked(db, whitelisted):
    update = FakeUpdate(uid=111111)  # not whitelisted
    ctx = FakeContext(db)
    asyncio.run(handlers.cmd_start(update, ctx))
    assert _last_reply(update) == replies.UNAUTHORIZED


def test_start_creates_user(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_start(update, FakeContext(db)))
    assert db.get_user(whitelisted) is not None
    assert _last_reply(update) == replies.WELCOME


# ------------------------------------------------------------------ /status

def test_status_no_session(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_status(update, FakeContext(db)))
    assert _last_reply(update) == replies.STATUS_NO_SESSION


def test_status_with_active_session(db, whitelisted):
    db.upsert_user(whitelisted, "Renat")
    sid = db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_status(update, FakeContext(db)))
    reply = _last_reply(update)
    assert str(sid) in reply
    assert "vacancy_to_candidates" in reply


# ------------------------------------------------------------------ /cancel

def test_cancel_nothing_to_cancel(db, whitelisted):
    db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_cancel(update, FakeContext(db)))
    assert _last_reply(update) == replies.NOTHING_TO_CANCEL


def test_cancel_active_session(db, whitelisted):
    db.upsert_user(whitelisted, "Renat")
    sid = db.create_session(whitelisted, "cv_to_jobs")
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_cancel(update, FakeContext(db)))
    assert _last_reply(update) == replies.SESSION_CANCELLED
    assert db.get_session(sid)["step"] == SessionStep.CANCELLED.value
    # The cancelled session is no longer "active".
    assert db.get_active_session(whitelisted) is None


def test_refind_cancels_previous_session(db, whitelisted):
    db.upsert_user(whitelisted, "Renat")
    old = db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_refind_candidate(update, FakeContext(db)))
    assert db.get_session(old)["step"] == SessionStep.CANCELLED.value
    new = db.get_active_session(whitelisted)
    assert new["pipeline_type"] == "cv_to_jobs"


# ------------------------------------------------------------- unknown / text

def test_unknown_command(db, whitelisted):
    update = FakeUpdate(uid=whitelisted)
    asyncio.run(handlers.cmd_unknown(update, FakeContext(db)))
    assert _last_reply(update) == replies.UNKNOWN_COMMAND


def test_text_without_session(db, whitelisted):
    db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted, text="some random text")
    asyncio.run(handlers.on_text(update, FakeContext(db)))
    assert _last_reply(update) == replies.NO_SESSION


def test_text_in_waiting_input_generates_boolean(db, whitelisted, monkeypatch):
    db.upsert_user(whitelisted, "Renat")
    sid = db.create_session(whitelisted, "vacancy_to_candidates")
    update = FakeUpdate(uid=whitelisted, text="Senior Python role")

    # generate_boolean now calls OpenAI — replace it with a deterministic stub
    # for the handler test (the real call is covered in step_5 e2e).
    async def fake_generate_boolean(input_text, brief_text, pipeline_type):
        return "(\"Python\") AND (\"Senior\")"
    monkeypatch.setattr(handlers.pipelines, "generate_boolean", fake_generate_boolean)

    asyncio.run(handlers.on_text(update, FakeContext(db)))
    session = db.get_session(sid)
    assert session["step"] == SessionStep.WAITING_BOOLEAN_CONFIRM.value
    assert session["input_text"] == "Senior Python role"
    assert session["boolean_text_original"]  # boolean stored


# ---------------------------------------------------------- async non-blocking

def test_status_responds_while_pipeline_running(db, whitelisted, monkeypatch):
    """A long pipeline must not block /status — the run handler is a task."""
    db.upsert_user(whitelisted, "Renat")
    sid = db.create_session(whitelisted, "vacancy_to_candidates")
    db.update_session(sid, step=SessionStep.RUNNING.value)

    async def scenario():
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
        return _last_reply(update)

    reply = asyncio.run(scenario())
    assert str(sid) in reply
