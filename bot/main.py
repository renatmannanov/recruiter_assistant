"""Bot entry point.

Loads env, opens the DB, wires handlers, runs long-polling. This is an
entry point — env is loaded here (not in library modules), per core/utils/env.

Run from the repo root:  python -m bot.main
"""

import logging
import os
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import handlers
from core.utils.env import load_project_env
from db.client import DB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("bot")


async def _schema_ready(db: DB) -> bool:
    """True if core tables exist (PG database may be empty on a fresh install)."""
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='sessions'"
        )
    return row is not None


async def _post_init(app: Application):
    """Connect to Postgres, init schema if empty, drop stale sessions."""
    db = await DB.connect()
    if not await _schema_ready(db):
        log.info("initializing DB schema (no 'sessions' table yet)")
        await db.initialize_from_schema()
    stale = await db.cleanup_stale_sessions()
    if stale:
        log.info("cleaned up %d stale session(s)", stale)
    app.bot_data["db"] = db


async def _post_shutdown(app: Application):
    db = app.bot_data.get("db")
    if db is not None:
        await db.close()


def _build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # Commands.
    app.add_handler(CommandHandler(["start", "help"], handlers.cmd_start))
    app.add_handler(CommandHandler("refind_vacancy", handlers.cmd_refind_vacancy))
    app.add_handler(CommandHandler("refind_candidate", handlers.cmd_refind_candidate))
    app.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    # Any other /command.
    app.add_handler(MessageHandler(filters.COMMAND, handlers.cmd_unknown))
    # Documents and plain text.
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))

    return app


def main():
    load_project_env()
    app = _build_application()
    log.info("recruiter_assistant bot starting (long polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
