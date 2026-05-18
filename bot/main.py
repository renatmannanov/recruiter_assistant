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


def _schema_ready(db: DB) -> bool:
    """True if core tables exist (the file may exist but be empty)."""
    rows = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchall()
    return len(rows) == 1


def _build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    db_path = os.environ.get("DB_PATH", "./data/recruiter_assistant.db")
    db_existed = os.path.exists(db_path)
    db = DB(db_path)
    # First run (or an empty file) -> create the schema so the bot is
    # self-sufficient and does not need a separate `db.client --init`.
    if not db_existed or not _schema_ready(db):
        log.info("initializing DB schema at %s", db_path)
        db.initialize_from_schema()
    # Stale sessions from a previous crashed run -> mark errored on startup.
    stale = db.cleanup_stale_sessions()
    if stale:
        log.info("cleaned up %d stale session(s)", stale)

    app = Application.builder().token(token).build()
    app.bot_data["db"] = db

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
