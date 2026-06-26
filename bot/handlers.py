"""Telegram handlers — the deterministic message router.

No LLM anywhere here. Every update is matched against the current session
step via the state machine; anything that does not fit gets a "не понял"
reply. Pipelines run as background asyncio tasks so the bot stays responsive.

Wiring:
- commands  -> cmd_* handlers
- documents -> on_document  (media groups debounced via job_queue)
- plain text-> on_text
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import auth, extractors, pipelines, replies
from bot.extractors import ExtractionError, FileInput
from bot.state_machine import Event, SessionStep, is_confirm_word
from db.client import DB

log = logging.getLogger(__name__)

# Pipeline label per command.
_PIPELINE_VACANCY = "vacancy_to_candidates"
_PIPELINE_CV = "cv_to_jobs"

# How long to wait for the rest of a media group before processing it.
_MEDIA_GROUP_DEBOUNCE_SEC = 1.5


# --------------------------------------------------------------------- helpers

def _db(context: ContextTypes.DEFAULT_TYPE) -> DB:
    """The shared DB instance, stashed in bot_data by main.py."""
    return context.application.bot_data["db"]


async def _reply(update: Update, text: str, **kwargs):
    await update.effective_message.reply_text(text, **kwargs)


async def _ensure_user(db: DB, update: Update) -> bool:
    """Authorize the sender and make sure they exist in the users table.

    Returns False (and sends the unauthorized reply) if not whitelisted.
    """
    user = update.effective_user
    if not auth.is_authorized(user.id):
        await _reply(update, replies.UNAUTHORIZED)
        return False
    if await db.get_user(user.id) is None:
        cfg = auth.get_user_config(user.id) or {}
        await db.upsert_user(user.id, cfg.get("display_name") or user.full_name)
    return True


# ---------------------------------------------------------------- command flow

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start and /help — show the welcome text."""
    if not await _ensure_user(_db(context), update):
        return
    await _reply(update, replies.WELCOME)


async def _start_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    pipeline_type: str, ask_text: str,
):
    """Shared body of /refind_vacancy and /refind_candidate.

    Cancels any active session for this user, then opens a fresh one.
    """
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    user_id = update.effective_user.id

    active = await db.get_active_session(user_id)
    if active is not None:
        await db.update_session(
            active["id"],
            step=SessionStep.CANCELLED.value,
            pending_boolean=None,
        )

    await db.create_session(user_id, pipeline_type)
    await _reply(update, ask_text)


async def cmd_refind_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _start_session(
        update, context, _PIPELINE_VACANCY, replies.ASK_FOR_VACANCY_INPUT
    )


async def cmd_refind_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _start_session(
        update, context, _PIPELINE_CV, replies.ASK_FOR_CV_INPUT
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — cancel the active session, if any."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    active = await db.get_active_session(update.effective_user.id)
    if active is None:
        await _reply(update, replies.NOTHING_TO_CANCEL)
        return
    await db.update_session(
        active["id"],
        step=SessionStep.CANCELLED.value,
        pending_boolean=None,
    )
    await _reply(update, replies.SESSION_CANCELLED)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — report the active session, if any."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    active = await db.get_active_session(update.effective_user.id)
    if active is None:
        await _reply(update, replies.STATUS_NO_SESSION)
        return
    await _reply(update, replies.STATUS_ACTIVE.format(
        session_id=active["id"],
        pipeline_type=active["pipeline_type"],
        step=active["step"],
    ))


async def cmd_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vacancies — list the user's vacancies, newest first."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    vacancies = await db.list_vacancies_by_user(update.effective_user.id)
    if not vacancies:
        await _reply(update, replies.VACANCIES_EMPTY)
        return
    lines = [replies.VACANCIES_LIST_HEADER]
    for v in vacancies:
        lines.append(replies.VACANCIES_LIST_ITEM.format(
            id=v["id"], name=v["name"] or "(no name)",
            source=v["source"], created_at=v["created_at"],
        ))
    await _reply(update, "\n".join(lines))


async def cmd_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vacancy <id> — one vacancy's card: JD, searches, runs, screening stats.

    Access control: a vacancy owned by another user reads as "not found"
    (same-as-404), so the command never leaks the existence of others' data.
    """
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    parts = (update.effective_message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lstrip("#") if len(parts) > 1 else ""
    if not arg.isdigit():
        await _reply(update, replies.VACANCY_USAGE)
        return
    vid = int(arg)

    v = await db.get_vacancy(vid)
    if v is None or v["created_by_user_id"] != update.effective_user.id:
        await _reply(update, replies.VACANCY_NOT_FOUND.format(id=vid))
        return

    searches = await db.list_searches_by_vacancy(vid)
    screenings = await db.list_screenings_by_vacancy(vid)
    go = sum(1 for s in screenings if s["ai_status"] == "pass")
    maybe = sum(1 for s in screenings if s["ai_status"] == "uncertain")
    skip = sum(1 for s in screenings if s["ai_status"] == "fail")
    runs_count = len({s["run_id"] for s in screenings})
    jd = v["jd_text"] or ""
    jd_preview = jd[:300] + ("..." if len(jd) > 300 else "")

    await _reply(update, replies.VACANCY_CARD.format(
        id=v["id"], name=v["name"] or "(no name)", source=v["source"],
        created_at=v["created_at"], searches_count=len(searches),
        runs_count=runs_count, screenings_count=len(screenings),
        go=go, maybe=maybe, skip=skip, jd_preview=jd_preview,
    ))


async def cmd_runs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/runs — the user's most recent runs (newest first)."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    rows = await db.list_recent_runs_by_user(update.effective_user.id)
    if not rows:
        await _reply(update, replies.RUNS_EMPTY)
        return
    lines = [replies.RUNS_LIST_HEADER]
    for r in rows:
        lines.append(replies.RUNS_LIST_ITEM.format(
            id=r["id"], session_id=r["session_id"],
            pipeline_type=r["pipeline_type"], status=r["status"],
            found=r["found_count"] or 0, passed=r["passed_count"] or 0,
            created_at=r["created_at"],
        ))
    await _reply(update, "\n".join(lines))


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any command not explicitly registered."""
    if not await _ensure_user(_db(context), update):
        return
    await _reply(update, replies.UNKNOWN_COMMAND)


# ------------------------------------------------------------- input handling

async def _generate_boolean_and_advance(
    db: DB, session: dict, user_id: int,
    input_text: str, brief_text: str | None, say,
):
    """Common path once JD/CV text is extracted.

    1. Create a manual `vacancies` row with the JD + brief.
    2. Generate the boolean via the LLM.
    3. Store boolean in sessions.pending_boolean (held until the user confirms;
       at that point it'll move into a fresh `searches` row).
    4. Link the session to the vacancy and advance to WAITING_BOOLEAN_CONFIRM.
    """
    session_id = session["id"]
    vacancy_id = await db.create_vacancy(
        source="manual",
        name=f"vacancy_{session_id}",
        jd_text=input_text,
        brief_text=brief_text,
        created_by_user_id=user_id,
    )
    boolean = await pipelines.generate_boolean(
        input_text, brief_text, session["pipeline_type"]
    )
    await db.update_session(
        session_id,
        vacancy_id=vacancy_id,
        pending_boolean=boolean,
        step=SessionStep.WAITING_BOOLEAN_CONFIRM.value,
    )
    await say(
        replies.BOOLEAN_GENERATED.format(boolean=boolean),
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text message — routed by the active session's step."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    user_id = update.effective_user.id
    text = update.effective_message.text or ""

    session = await db.get_active_session(user_id)
    if session is None:
        await _reply(update, replies.NO_SESSION)
        return

    step = SessionStep(session["step"])

    if step == SessionStep.WAITING_INPUT:
        try:
            input_text, brief_text = extractors.extract_from_text(text)
        except ExtractionError:
            await _reply(update, replies.EMPTY_INPUT)
            return

        async def say(t, **kw):
            await update.effective_message.reply_text(t, **kw)

        await _generate_boolean_and_advance(
            db, session, user_id, input_text, brief_text, say
        )

    elif step == SessionStep.WAITING_BOOLEAN_CONFIRM:
        # Confirm -> use pending_boolean as-is; any other text -> the user's edit.
        pending = session["pending_boolean"]
        if is_confirm_word(text):
            boolean = pending
            original = None
        else:
            boolean = text.strip()
            original = pending if pending != boolean else None
        search_id = await db.create_search(
            vacancy_id=session["vacancy_id"],
            boolean_text=boolean,
            original_boolean=original,
            created_by_user_id=user_id,
        )
        await db.update_session(
            session["id"],
            search_id=search_id,
            pending_boolean=None,
            step=SessionStep.RUNNING.value,
        )
        await _reply(update, replies.PIPELINE_STARTED)
        _kick_off_pipeline(context, session["id"], user_id,
                           session["pipeline_type"])

    elif step == SessionStep.RUNNING:
        await _reply(update, replies.PIPELINE_IN_PROGRESS)

    else:  # terminal — should not happen (get_active_session excludes them)
        await _reply(update, replies.SESSION_FINISHED)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A document arrived. Single files process immediately; media groups
    are debounced via job_queue so both files are collected first."""
    db = _db(context)
    if not await _ensure_user(db, update):
        return
    msg = update.effective_message

    if msg.media_group_id is None:
        await _process_files(update, context, [msg.document])
        return

    # Media group: stash this doc, (re)arm a short debounce job.
    key = f"mg:{update.effective_user.id}:{msg.media_group_id}"
    bucket = context.application.bot_data.setdefault(key, [])
    bucket.append(msg.document)

    jobs = context.job_queue.get_jobs_by_name(key)
    for j in jobs:
        j.schedule_removal()
    context.job_queue.run_once(
        _flush_media_group, _MEDIA_GROUP_DEBOUNCE_SEC, name=key,
        data={"key": key, "chat_id": update.effective_chat.id,
              "user_id": update.effective_user.id},
    )


async def _flush_media_group(context: ContextTypes.DEFAULT_TYPE):
    """Debounce callback: process the accumulated media group as one input."""
    data = context.job.data
    key = data["key"]
    docs = context.application.bot_data.pop(key, [])
    if not docs:
        return
    await _process_files(
        None, context, docs,
        chat_id=data["chat_id"], user_id=data["user_id"],
    )


async def _process_files(
    update: Update | None, context: ContextTypes.DEFAULT_TYPE,
    documents: list, chat_id: int | None = None, user_id: int | None = None,
):
    """Download docs, extract (input_text, brief_text), advance the session.

    Works both for a live update (single file) and for a debounced media
    group (update is None — chat_id/user_id passed explicitly).
    """
    db = _db(context)
    if update is not None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

    async def say(text: str, **kwargs):
        if update is not None:
            await update.effective_message.reply_text(text, **kwargs)
        else:
            await context.bot.send_message(chat_id, text, **kwargs)

    session = await db.get_active_session(user_id)
    if session is None:
        await say(replies.NO_SESSION)
        return
    if SessionStep(session["step"]) != SessionStep.WAITING_INPUT:
        # Files only make sense while awaiting input.
        await say(replies.PIPELINE_IN_PROGRESS
                  if SessionStep(session["step"]) == SessionStep.RUNNING
                  else replies.NOT_UNDERSTOOD)
        return

    if len(documents) > 2:
        await say(replies.TOO_MANY_FILES)
        return

    files: list[FileInput] = []
    for doc in documents:
        ext = extractors._ext(doc.file_name)
        if ext not in extractors.ALLOWED_EXTENSIONS:
            await say(replies.UNSUPPORTED_FILE.format(ext=ext or "(без расширения)"))
            return
        if doc.file_size and doc.file_size > extractors.MAX_FILE_SIZE:
            await say(replies.FILE_TOO_BIG)
            return
        tg_file = await context.bot.get_file(doc.file_id)
        raw = await tg_file.download_as_bytearray()
        files.append(FileInput(
            filename=doc.file_name,
            content=bytes(raw).decode("utf-8", errors="replace"),
            size=len(raw),
        ))

    try:
        input_text, brief_text = extractors.extract_from_files(files)
    except ExtractionError as e:
        await say(f"{replies.EMPTY_INPUT} ({e})")
        return

    await _generate_boolean_and_advance(db, session, user_id, input_text, brief_text, say)


# ------------------------------------------------------------- background run

def _kick_off_pipeline(
    context: ContextTypes.DEFAULT_TYPE,
    session_id: int, user_id: int, pipeline_type: str,
):
    """Schedule the pipeline as a background task — the bot stays responsive."""
    chat_id = user_id  # private chat: chat_id == user_id
    asyncio.create_task(
        _run_pipeline_task(context, session_id, chat_id, pipeline_type)
    )


async def _run_pipeline_task(
    context: ContextTypes.DEFAULT_TYPE,
    session_id: int, chat_id: int, pipeline_type: str,
):
    """Run the pipeline, persist the run, deliver the report (or the error)."""
    db = _db(context)
    user_id = chat_id
    run_id = await db.create_run(session_id, user_id, pipeline_type)
    try:
        result = await pipelines.run_pipeline(
            session_id, pipeline_type, run_id=run_id, db=db,
        )
        await db.complete_run(
            run_id,
            found_count=result["found"],
            screened_count=result["screened"],
            passed_count=result["passed"],
            cost_usd=result["cost_usd"],
            duration_sec=result["duration_sec"],
        )
        await db.complete_session(session_id, result["report_path"])
        total_found = result.get("total_found")
        await context.bot.send_message(
            chat_id,
            replies.PIPELINE_DONE.format(
                session_id=session_id,
                total_found=total_found if total_found is not None else "?",
                found=result["found"],
                screened=result["screened"],
                go=result.get("go", 0),
                maybe=result.get("maybe", 0),
                skip=result.get("skip", 0),
                already_seen=result.get("already_seen", 0),
            ),
        )
        with open(result["report_path"], "rb") as fh:
            await context.bot.send_document(chat_id, fh, filename="report.md")
    except Exception as e:  # noqa: BLE001 — surface any failure to the user
        log.exception("pipeline failed for session %s", session_id)
        await db.fail_run(run_id, str(e))
        await db.fail_session(session_id, str(e))
        await context.bot.send_message(
            chat_id,
            replies.PIPELINE_FAILED.format(
                session_id=session_id, error_text=str(e)
            ),
        )
