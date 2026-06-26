"""Tests for the read-only listing commands: /vacancies, /vacancy, /runs.

These exercise handler logic against a per-test PG schema (the `db` fixture
from conftest) with Telegram Update/Context mocked via the same fakes as
test_handlers.py. Focus: correct content, ownership isolation (a vacancy or
run owned by another user must not leak), and empty-state replies.
"""

import json

import pytest

from bot import auth, handlers, replies


@pytest.fixture
def whitelisted(tmp_path, monkeypatch):
    """Whitelist two users so ownership-isolation can be tested."""
    path = tmp_path / "whitelist.json"
    path.write_text(json.dumps({
        "users": [
            {"telegram_user_id": 423915315, "display_name": "Renat"},
            {"telegram_user_id": 999000, "display_name": "Other"},
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("WHITELIST_PATH", str(path))
    auth.reload_whitelist()
    yield 423915315
    auth.reload_whitelist()


_OTHER_UID = 999000


# ----------------------------------------------------------- Telegram mocks

class FakeMessage:
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


# --------------------------------------------------------------- helpers

async def _make_vacancy_with_screenings(
    db, user_id, *, name="vacancy_1", statuses=("pass", "uncertain", "fail"),
):
    """Build a full vacancy → search → session → run → screenings chain.

    Returns the vacancy_id. One candidate is created per status, each linked
    to the vacancy via candidate_screenings under a single run.
    """
    vacancy_id = await db.create_vacancy(
        source="manual", name=name, jd_text="Senior Python role",
        brief_text=None, created_by_user_id=user_id,
    )
    search_id = await db.create_search(
        vacancy_id=vacancy_id, boolean_text="(Python)",
        created_by_user_id=user_id,
    )
    session_id = await db.create_session(user_id, "vacancy_to_candidates")
    await db.update_session(session_id, vacancy_id=vacancy_id, search_id=search_id)
    run_id = await db.create_run(session_id, user_id, "vacancy_to_candidates")
    for i, status in enumerate(statuses):
        cand_id = await db.upsert_candidate(
            {"linkedinUrl": f"https://linkedin.com/in/{name}-{i}"}
        )
        await db.create_screening(
            candidate_id=cand_id, vacancy_id=vacancy_id, run_id=run_id,
            user_id=user_id, ai_status=status, ai_score=50, ai_comment="x",
        )
    return vacancy_id


# ------------------------------------------------------------ /vacancies

async def test_vacancies_empty(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_vacancies(update, FakeContext(db))
    assert _last_reply(update) == replies.VACANCIES_EMPTY


async def test_vacancies_lists_only_my(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    await db.upsert_user(_OTHER_UID, "Other")
    await db.create_vacancy(
        source="manual", name="mine", jd_text="JD",
        brief_text=None, created_by_user_id=whitelisted,
    )
    await db.create_vacancy(
        source="manual", name="theirs", jd_text="JD",
        brief_text=None, created_by_user_id=_OTHER_UID,
    )
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_vacancies(update, FakeContext(db))
    reply = _last_reply(update)
    assert "mine" in reply
    assert "theirs" not in reply


# -------------------------------------------------------------- /vacancy

async def test_vacancy_card_shows_stats(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    vid = await _make_vacancy_with_screenings(
        db, whitelisted, statuses=("pass", "uncertain", "uncertain", "fail"),
    )
    update = FakeUpdate(uid=whitelisted, text=f"/vacancy {vid}")
    await handlers.cmd_vacancy(update, FakeContext(db))
    reply = _last_reply(update)
    assert f"Вакансия #{vid}" in reply
    assert "GO: 1" in reply
    assert "MAYBE: 2" in reply
    assert "SKIP: 1" in reply
    assert "Searches (boolean'ы): 1" in reply
    assert "Runs: 1" in reply


async def test_vacancy_usage_on_bad_arg(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted, text="/vacancy")
    await handlers.cmd_vacancy(update, FakeContext(db))
    assert _last_reply(update) == replies.VACANCY_USAGE


async def test_vacancy_not_found(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted, text="/vacancy 9999")
    await handlers.cmd_vacancy(update, FakeContext(db))
    assert _last_reply(update) == replies.VACANCY_NOT_FOUND.format(id=9999)


async def test_vacancy_access_denied_for_other_user(db, whitelisted):
    """A vacancy owned by someone else reads as not-found (same-as-404)."""
    await db.upsert_user(whitelisted, "Renat")
    await db.upsert_user(_OTHER_UID, "Other")
    vid = await db.create_vacancy(
        source="manual", name="theirs", jd_text="JD",
        brief_text=None, created_by_user_id=_OTHER_UID,
    )
    update = FakeUpdate(uid=whitelisted, text=f"/vacancy {vid}")
    await handlers.cmd_vacancy(update, FakeContext(db))
    assert _last_reply(update) == replies.VACANCY_NOT_FOUND.format(id=vid)


# ----------------------------------------------------------------- /runs

async def test_runs_empty(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_runs(update, FakeContext(db))
    assert _last_reply(update) == replies.RUNS_EMPTY


async def test_runs_lists_only_my(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    await db.upsert_user(_OTHER_UID, "Other")
    my_sess = await db.create_session(whitelisted, "vacancy_to_candidates")
    my_run = await db.create_run(my_sess, whitelisted, "vacancy_to_candidates")
    other_sess = await db.create_session(_OTHER_UID, "vacancy_to_candidates")
    await db.create_run(other_sess, _OTHER_UID, "vacancy_to_candidates")

    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_runs(update, FakeContext(db))
    reply = _last_reply(update)
    assert f"#{my_run} session #{my_sess}" in reply
    # The other user's run id must not appear.
    assert f"session #{other_sess}" not in reply


async def test_runs_limit_is_10(db, whitelisted):
    await db.upsert_user(whitelisted, "Renat")
    created = []
    for _ in range(12):
        sid = await db.create_session(whitelisted, "vacancy_to_candidates")
        rid = await db.create_run(sid, whitelisted, "vacancy_to_candidates")
        created.append(rid)
    update = FakeUpdate(uid=whitelisted)
    await handlers.cmd_runs(update, FakeContext(db))
    reply = _last_reply(update)
    # 10 newest shown (header + 10 lines); oldest two omitted.
    assert reply.count("session #") == 10
    assert f"#{created[0]} " not in reply
    assert f"#{created[-1]} " in reply
