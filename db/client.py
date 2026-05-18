"""SQLite client for recruiter_assistant.

Plain sqlite3 stdlib — no ORM. Rows are returned as dicts.

Concurrency: the bot is async and serves multiple users, so the connection
is opened with WAL journal mode (concurrent reads + one writer) and
check_same_thread=False. Every write goes through a threading.Lock — simple
and sufficient for v1's load.

CLI:
    python -m db.client --init       # create DB from schema.sql
    python -m db.client --migrate    # apply pending migrations
"""

import os
import sqlite3
import threading
from pathlib import Path

_DB_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = _DB_DIR / "schema.sql"
_MIGRATIONS_DIR = _DB_DIR / "migrations"

# Sessions that never reach a terminal step (process killed mid-run, etc.).
_TERMINAL_STEPS = ("done", "error", "cancelled")


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """sqlite3 row_factory: map a row to a {column: value} dict."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class DB:
    """SQLite-backed store for users, sessions, runs and pipeline results."""

    def __init__(self, path: str):
        self.path = str(path)
        # Ensure the parent directory exists (e.g. ./data/).
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = _row_to_dict
        self._lock = threading.Lock()

        # WAL: concurrent readers + a single writer without "database is locked".
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.commit()

    # ----------------------------------------------------------------- internals

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Run a write statement under the lock and commit."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchone()

    def _query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    def close(self):
        with self._lock:
            self._conn.close()

    # --------------------------------------------------------------- schema/init

    def initialize_from_schema(self):
        """Create all tables from schema.sql (fresh install).

        Records every migration file as already applied, so a later
        --migrate is a no-op on a DB built from the current schema.
        """
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(schema_sql)
            for name in self._migration_files():
                self._conn.execute(
                    "INSERT OR IGNORE INTO _migrations(name) VALUES (?)", (name,)
                )
            self._conn.commit()

    def apply_migrations(self) -> list[str]:
        """Apply migration files not yet recorded in _migrations.

        Returns the list of migration names applied this call.
        """
        with self._lock:
            # _migrations may not exist on a pre-migration-mechanism DB.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL UNIQUE, "
                "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            applied = {
                r["name"]
                for r in self._conn.execute("SELECT name FROM _migrations")
            }
            done = []
            for name in self._migration_files():
                if name in applied:
                    continue
                sql = (_MIGRATIONS_DIR / name).read_text(encoding="utf-8")
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO _migrations(name) VALUES (?)", (name,)
                )
                done.append(name)
            self._conn.commit()
            return done

    @staticmethod
    def _migration_files() -> list[str]:
        """Migration filenames sorted by their numeric prefix."""
        if not _MIGRATIONS_DIR.exists():
            return []
        return sorted(p.name for p in _MIGRATIONS_DIR.glob("*.sql"))

    # ----------------------------------------------------------------------- users

    def get_user(self, telegram_user_id: int) -> dict | None:
        return self._query_one(
            "SELECT * FROM users WHERE telegram_user_id = ?", (telegram_user_id,)
        )

    def upsert_user(self, telegram_user_id: int, display_name: str = None):
        """Insert the user, or update display_name if already present."""
        self._execute(
            "INSERT INTO users(telegram_user_id, display_name) VALUES (?, ?) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET "
            "display_name = COALESCE(excluded.display_name, users.display_name)",
            (telegram_user_id, display_name),
        )

    # -------------------------------------------------------------------- sessions

    def create_session(self, user_id: int, pipeline_type: str) -> int:
        """Create a session in the initial 'waiting_input' step. Returns its id."""
        cur = self._execute(
            "INSERT INTO sessions(user_id, pipeline_type, step) "
            "VALUES (?, ?, 'waiting_input')",
            (user_id, pipeline_type),
        )
        return cur.lastrowid

    def get_session(self, session_id: int) -> dict | None:
        return self._query_one(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )

    def get_active_session(
        self, user_id: int, pipeline_type: str = None
    ) -> dict | None:
        """Most recent non-terminal session for a user, optionally by pipeline."""
        sql = (
            "SELECT * FROM sessions "
            "WHERE user_id = ? AND step NOT IN ('done', 'error', 'cancelled')"
        )
        params: list = [user_id]
        if pipeline_type is not None:
            sql += " AND pipeline_type = ?"
            params.append(pipeline_type)
        sql += " ORDER BY created_at DESC, id DESC LIMIT 1"
        return self._query_one(sql, tuple(params))

    def update_session(self, session_id: int, **fields):
        """Update arbitrary session columns; always bumps updated_at."""
        if not fields:
            return
        self._guard_columns("sessions", fields)
        cols = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [session_id]
        self._execute(
            f"UPDATE sessions SET {cols}, updated_at = datetime('now') "
            f"WHERE id = ?",
            tuple(params),
        )

    def complete_session(self, session_id: int, report_path: str):
        self.update_session(
            session_id, step="done", report_path=report_path
        )

    def fail_session(self, session_id: int, error_text: str):
        self.update_session(
            session_id, step="error", error_text=error_text
        )

    def cleanup_stale_sessions(self, older_than_minutes: int = 30) -> int:
        """Mark long-running sessions as errored (process restarted/stalled).

        Returns the number of sessions affected.
        """
        cur = self._execute(
            "UPDATE sessions SET step = 'error', "
            "error_text = 'restarted_or_stalled', "
            "updated_at = datetime('now') "
            "WHERE step = 'running' "
            "AND updated_at < datetime('now', ?)",
            (f"-{int(older_than_minutes)} minutes",),
        )
        return cur.rowcount

    # ------------------------------------------------------------------------ runs

    def create_run(
        self, session_id: int, user_id: int, pipeline_type: str
    ) -> int:
        """Create a run in 'running' status. Returns its id."""
        cur = self._execute(
            "INSERT INTO runs(session_id, user_id, pipeline_type, status) "
            "VALUES (?, ?, ?, 'running')",
            (session_id, user_id, pipeline_type),
        )
        return cur.lastrowid

    def get_run(self, run_id: int) -> dict | None:
        return self._query_one("SELECT * FROM runs WHERE id = ?", (run_id,))

    def update_run(self, run_id: int, **fields):
        if not fields:
            return
        self._guard_columns("runs", fields)
        cols = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [run_id]
        self._execute(f"UPDATE runs SET {cols} WHERE id = ?", tuple(params))

    def complete_run(
        self,
        run_id: int,
        found_count: int,
        screened_count: int,
        passed_count: int,
        cost_usd: float,
        duration_sec: float,
    ):
        self.update_run(
            run_id,
            status="done",
            found_count=found_count,
            screened_count=screened_count,
            passed_count=passed_count,
            cost_usd=cost_usd,
            duration_sec=duration_sec,
        )

    def fail_run(self, run_id: int, error_text: str):
        self.update_run(run_id, status="failed", error_text=error_text)

    # ------------------------------------------------------- candidates / vacancies

    def insert_candidates(
        self, run_id: int, user_id: int, candidates: list[dict]
    ):
        """Bulk-insert screened candidates for a run.

        Each dict may contain: linkedin_url (required), name, ai_status,
        ai_score, ai_comment, raw_profile_json.
        """
        rows = [
            (
                run_id,
                user_id,
                c["linkedin_url"],
                c.get("name"),
                c.get("ai_status"),
                c.get("ai_score"),
                c.get("ai_comment"),
                c.get("raw_profile_json"),
            )
            for c in candidates
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO candidates_found("
                "run_id, user_id, linkedin_url, name, ai_status, "
                "ai_score, ai_comment, raw_profile_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def insert_vacancies(
        self, run_id: int, user_id: int, vacancies: list[dict]
    ):
        """Bulk-insert scored vacancies for a run.

        Each dict may contain: linkedin_url (required), title, company,
        location, ai_score, ai_recommendation, raw_job_json.
        """
        rows = [
            (
                run_id,
                user_id,
                v["linkedin_url"],
                v.get("title"),
                v.get("company"),
                v.get("location"),
                v.get("ai_score"),
                v.get("ai_recommendation"),
                v.get("raw_job_json"),
            )
            for v in vacancies
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO vacancies_found("
                "run_id, user_id, linkedin_url, title, company, "
                "location, ai_score, ai_recommendation, raw_job_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def is_candidate_known(self, user_id: int, linkedin_url: str) -> bool:
        """True if this LinkedIn URL was already found for this user."""
        row = self._query_one(
            "SELECT 1 FROM candidates_found "
            "WHERE user_id = ? AND linkedin_url = ? LIMIT 1",
            (user_id, linkedin_url),
        )
        return row is not None

    def is_vacancy_known(self, user_id: int, linkedin_url: str) -> bool:
        row = self._query_one(
            "SELECT 1 FROM vacancies_found "
            "WHERE user_id = ? AND linkedin_url = ? LIMIT 1",
            (user_id, linkedin_url),
        )
        return row is not None

    # ----------------------------------------------------------------- guardrails

    # Column allow-lists: **fields kwargs build SQL, so reject unknown names
    # rather than emit a broken UPDATE or risk identifier injection.
    _COLUMNS = {
        "sessions": {
            "user_id", "pipeline_type", "step", "input_text", "brief_text",
            "boolean_text", "boolean_text_original", "report_path",
            "error_text",
        },
        "runs": {
            "session_id", "user_id", "pipeline_type", "status",
            "raw_apify_path", "screening_json", "report_md", "found_count",
            "screened_count", "passed_count", "cost_usd", "duration_sec",
            "error_text",
        },
    }

    @classmethod
    def _guard_columns(cls, table: str, fields: dict):
        unknown = set(fields) - cls._COLUMNS[table]
        if unknown:
            raise ValueError(
                f"unknown {table} column(s): {', '.join(sorted(unknown))}"
            )


def _main():
    import argparse

    parser = argparse.ArgumentParser(description="recruiter_assistant DB tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--init", action="store_true",
        help="create the DB from schema.sql",
    )
    group.add_argument(
        "--migrate", action="store_true",
        help="apply pending migrations",
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("DB_PATH", "./data/recruiter_assistant.db"),
        help="path to the SQLite file (default: $DB_PATH or ./data/...)",
    )
    args = parser.parse_args()

    db = DB(args.db_path)
    try:
        if args.init:
            db.initialize_from_schema()
            print(f"Initialized DB at {args.db_path}")
        elif args.migrate:
            applied = db.apply_migrations()
            if applied:
                print(f"Applied migrations: {', '.join(applied)}")
            else:
                print("No pending migrations.")
    finally:
        db.close()


if __name__ == "__main__":
    _main()
