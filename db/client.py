"""Async Postgres client for recruiter_assistant.

asyncpg + connection pool. Rows are returned as dicts (asyncpg.Record acts
like a Mapping; we wrap it in `dict(...)` so callers see plain dicts and
don't depend on Record's quirks).

DSN: either `DATABASE_URL` env var, or assembled from
`PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE`.

CLI:
    python -m db.client --init       # create DB from schema.sql
    python -m db.client --migrate    # apply pending migrations
"""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

import asyncpg

from core.candidate_screener.core.profile_cleaner import clean_profile

_DB_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = _DB_DIR / "schema.sql"
_MIGRATIONS_DIR = _DB_DIR / "migrations"

# sessions columns that are JSONB — update_session must cast their bind param
# with ::jsonb (callers pass a json.dumps string, asyncpg won't coerce it).
_JSONB_SESSION_COLUMNS = {"pending_apify_params"}


def _build_dsn() -> str:
    """Return DATABASE_URL if set, else assemble one from PG_* env vars."""
    if dsn := os.environ.get("DATABASE_URL"):
        return dsn
    user = quote(os.environ["PG_USER"], safe="")
    password = quote(os.environ["PG_PASSWORD"], safe="")
    host = os.environ["PG_HOST"]
    port = os.environ.get("PG_PORT", "5432")
    database = os.environ["PG_DATABASE"]
    return f"postgres://{user}:{password}@{host}:{port}/{database}"


class DB:
    """Postgres-backed store for users, sessions, runs and pipeline results."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def connect(
        cls,
        dsn: str | None = None,
        *,
        min_size: int = 1,
        max_size: int = 5,
    ) -> "DB":
        pool = await asyncpg.create_pool(
            dsn=dsn or _build_dsn(),
            min_size=min_size,
            max_size=max_size,
        )
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def __aenter__(self) -> "DB":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ----------------------------------------------------------------- internals

    async def _execute(self, sql: str, *params) -> str:
        """Run a write statement; returns asyncpg's status string."""
        async with self._pool.acquire() as conn:
            return await conn.execute(sql, *params)

    async def _query_one(self, sql: str, *params) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        return dict(row) if row else None

    async def _query_all(self, sql: str, *params) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- schema/init

    async def initialize_from_schema(self):
        """Create all tables from schema.sql (fresh install).

        Records every migration file as already applied, so a later
        --migrate is a no-op on a DB built from the current schema.
        """
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(schema_sql)
                for name in self._migration_files():
                    await conn.execute(
                        "INSERT INTO _migrations(name) VALUES ($1) "
                        "ON CONFLICT (name) DO NOTHING",
                        name,
                    )

    async def apply_migrations(self) -> list[str]:
        """Apply migration files not yet recorded in _migrations.

        Returns the list of migration names applied this call.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # _migrations may not exist on a pre-migration-mechanism DB.
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS _migrations ("
                    "id BIGSERIAL PRIMARY KEY, "
                    "name TEXT NOT NULL UNIQUE, "
                    "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                applied = {
                    r["name"]
                    for r in await conn.fetch("SELECT name FROM _migrations")
                }
                done = []
                for name in self._migration_files():
                    if name in applied:
                        continue
                    sql = (_MIGRATIONS_DIR / name).read_text(encoding="utf-8")
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO _migrations(name) VALUES ($1)", name
                    )
                    done.append(name)
                return done

    @staticmethod
    def _migration_files() -> list[str]:
        """Migration filenames sorted by their numeric prefix."""
        if not _MIGRATIONS_DIR.exists():
            return []
        return sorted(p.name for p in _MIGRATIONS_DIR.glob("*.sql"))

    # ----------------------------------------------------------------------- users

    async def get_user(self, telegram_user_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM users WHERE telegram_user_id = $1", telegram_user_id
        )

    async def upsert_user(self, telegram_user_id: int, display_name: str = None):
        """Insert the user, or update display_name if already present."""
        await self._execute(
            "INSERT INTO users(telegram_user_id, display_name) VALUES ($1, $2) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET "
            "display_name = COALESCE(EXCLUDED.display_name, users.display_name)",
            telegram_user_id,
            display_name,
        )

    # -------------------------------------------------------------------- sessions

    async def create_session(self, user_id: int, pipeline_type: str) -> int:
        """Create a session in the initial 'waiting_input' step. Returns its id."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO sessions(user_id, pipeline_type, step) "
                "VALUES ($1, $2, 'waiting_input') RETURNING id",
                user_id,
                pipeline_type,
            )
        return row["id"]

    async def get_session(self, session_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM sessions WHERE id = $1", session_id
        )

    async def get_active_session(
        self, user_id: int, pipeline_type: str = None
    ) -> dict | None:
        """Most recent non-terminal session for a user, optionally by pipeline."""
        sql = (
            "SELECT * FROM sessions "
            "WHERE user_id = $1 AND step NOT IN ('done', 'error', 'cancelled')"
        )
        params: list = [user_id]
        if pipeline_type is not None:
            params.append(pipeline_type)
            sql += f" AND pipeline_type = ${len(params)}"
        sql += " ORDER BY created_at DESC, id DESC LIMIT 1"
        return await self._query_one(sql, *params)

    async def update_session(self, session_id: int, **fields):
        """Update arbitrary session columns; always bumps updated_at."""
        if not fields:
            return
        self._guard_columns("sessions", fields)
        # $1..$N for values, $(N+1) for session_id. JSONB columns need an
        # explicit ::jsonb cast — asyncpg won't coerce a JSON string into jsonb
        # on its own (callers pass json.dumps(...) for these).
        cols = ", ".join(
            f"{k} = ${i+1}::jsonb" if k in _JSONB_SESSION_COLUMNS
            else f"{k} = ${i+1}"
            for i, k in enumerate(fields)
        )
        params = list(fields.values()) + [session_id]
        await self._execute(
            f"UPDATE sessions SET {cols}, updated_at = now() "
            f"WHERE id = ${len(params)}",
            *params,
        )

    async def complete_session(self, session_id: int, report_path: str):
        await self.update_session(
            session_id, step="done", report_path=report_path
        )

    async def fail_session(self, session_id: int, error_text: str):
        await self.update_session(
            session_id, step="error", error_text=error_text
        )

    async def cleanup_stale_sessions(self, older_than_minutes: int = 30) -> int:
        """Mark long-running sessions as errored (process restarted/stalled).

        Returns the number of sessions affected.
        """
        # asyncpg.Connection.execute returns a status string like "UPDATE 3".
        status = await self._execute(
            "UPDATE sessions SET step = 'error', "
            "error_text = 'restarted_or_stalled', "
            "updated_at = now() "
            "WHERE step = 'running' "
            "AND updated_at < now() - make_interval(mins => $1)",
            int(older_than_minutes),
        )
        return int(status.rsplit(" ", 1)[-1])

    # ------------------------------------------------------------------------ runs

    async def create_run(
        self, session_id: int, user_id: int, pipeline_type: str
    ) -> int:
        """Create a run in 'running' status. Returns its id."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO runs(session_id, user_id, pipeline_type, status) "
                "VALUES ($1, $2, $3, 'running') RETURNING id",
                session_id,
                user_id,
                pipeline_type,
            )
        return row["id"]

    async def get_run(self, run_id: int) -> dict | None:
        return await self._query_one("SELECT * FROM runs WHERE id = $1", run_id)

    async def update_run(self, run_id: int, **fields):
        if not fields:
            return
        self._guard_columns("runs", fields)
        cols = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(fields))
        params = list(fields.values()) + [run_id]
        await self._execute(
            f"UPDATE runs SET {cols} WHERE id = ${len(params)}", *params
        )

    async def complete_run(
        self,
        run_id: int,
        found_count: int,
        screened_count: int,
        passed_count: int,
        cost_usd: float,
        duration_sec: float,
    ):
        await self.update_run(
            run_id,
            status="done",
            found_count=found_count,
            screened_count=screened_count,
            passed_count=passed_count,
            cost_usd=cost_usd,
            duration_sec=duration_sec,
        )

    async def fail_run(self, run_id: int, error_text: str):
        await self.update_run(run_id, status="failed", error_text=error_text)

    async def list_recent_runs_by_user(
        self, user_id: int, limit: int = 10
    ) -> list[dict]:
        """The user's most recent runs (newest first), for the /runs command."""
        return await self._query_all(
            "SELECT id, session_id, pipeline_type, status, "
            "found_count, passed_count, created_at "
            "FROM runs WHERE user_id = $1 "
            "ORDER BY created_at DESC, id DESC LIMIT $2",
            user_id, limit,
        )

    # ------------------------------------------------------------------ companies

    async def get_or_create_company(self, name: str) -> int:
        """Return id of the company with this name; insert if missing."""
        row = await self._query_one(
            "INSERT INTO companies(name) VALUES ($1) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            name,
        )
        return row["id"]

    async def get_company(self, company_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM companies WHERE id = $1", company_id
        )

    async def list_companies(self) -> list[dict]:
        return await self._query_all(
            "SELECT * FROM companies ORDER BY name"
        )

    # ------------------------------------------------------------------ vacancies

    async def create_vacancy(
        self,
        *,
        source: str,
        name: str | None = None,
        jd_text: str | None = None,
        brief_text: str | None = None,
        company_id: int | None = None,
        linkedin_url: str | None = None,
        title: str | None = None,
        location: str | None = None,
        seniority: str | None = None,
        created_by_user_id: int | None = None,
        discovered_in_run_id: int | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO vacancies("
                "source, name, jd_text, brief_text, company_id, linkedin_url, "
                "title, location, seniority, created_by_user_id, "
                "discovered_in_run_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
                "RETURNING id",
                source, name, jd_text, brief_text, company_id, linkedin_url,
                title, location, seniority, created_by_user_id,
                discovered_in_run_id,
            )
        return row["id"]

    async def get_vacancy(self, vacancy_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM vacancies WHERE id = $1", vacancy_id
        )

    async def list_vacancies_by_user(
        self, user_id: int, source: str | None = None
    ) -> list[dict]:
        sql = "SELECT * FROM vacancies WHERE created_by_user_id = $1"
        params: list = [user_id]
        if source is not None:
            params.append(source)
            sql += f" AND source = ${len(params)}"
        sql += " ORDER BY created_at DESC, id DESC"
        return await self._query_all(sql, *params)

    # ----------------------------------------------------------------- candidates

    async def upsert_candidate(self, raw_profile: dict) -> int:
        """Upsert by linkedin_url; refresh last_seen_at and raw_profile_json.

        Uses clean_profile() to extract the standard fields (name, headline,
        location, about) the same way the screening pipeline does. Raw JSON is
        stored verbatim in raw_profile_json (JSONB).
        """
        cleaned = clean_profile(raw_profile)
        url = cleaned["linkedin_url"]
        if not url:
            raise ValueError("raw_profile has no linkedinUrl")
        raw_json = json.dumps(raw_profile, ensure_ascii=False)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO candidates("
                "linkedin_url, name, headline, location, about, raw_profile_json) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb) "
                "ON CONFLICT (linkedin_url) DO UPDATE SET "
                "name             = EXCLUDED.name, "
                "headline         = EXCLUDED.headline, "
                "location         = EXCLUDED.location, "
                "about            = EXCLUDED.about, "
                "raw_profile_json = EXCLUDED.raw_profile_json, "
                "last_seen_at     = now(), "
                "updated_at       = now() "
                "RETURNING id",
                url, cleaned["name"], cleaned["headline"],
                cleaned["location"], cleaned["about"], raw_json,
            )
        return row["id"]

    async def get_candidate(self, candidate_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM candidates WHERE id = $1", candidate_id
        )

    async def get_candidate_by_url(self, linkedin_url: str) -> dict | None:
        return await self._query_one(
            "SELECT * FROM candidates WHERE linkedin_url = $1", linkedin_url
        )

    # ------------------------------------------------------------------- searches

    async def create_search(
        self,
        *,
        vacancy_id: int,
        boolean_text: str,
        created_by_user_id: int,
        original_boolean: str | None = None,
        apify_params: dict | None = None,
    ) -> int:
        # asyncpg doesn't serialize a dict into jsonb automatically — dump it
        # ourselves and cast with $5::jsonb (same pattern as upsert_candidate).
        params_json = (
            json.dumps(apify_params, ensure_ascii=False)
            if apify_params is not None else None
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO searches("
                "vacancy_id, boolean_text, original_boolean, apify_params, "
                "created_by_user_id) "
                "VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id",
                vacancy_id, boolean_text, original_boolean, params_json,
                created_by_user_id,
            )
        return row["id"]

    async def get_search(self, search_id: int) -> dict | None:
        return await self._query_one(
            "SELECT * FROM searches WHERE id = $1", search_id
        )

    async def list_searches_by_vacancy(self, vacancy_id: int) -> list[dict]:
        return await self._query_all(
            "SELECT * FROM searches WHERE vacancy_id = $1 "
            "ORDER BY created_at ASC, id ASC",
            vacancy_id,
        )

    # -------------------------------------------------------- candidate_screenings

    async def create_screening(
        self,
        *,
        candidate_id: int,
        vacancy_id: int,
        run_id: int,
        user_id: int,
        ai_status: str | None,
        ai_score: int | None,
        ai_comment: str | None,
    ) -> int:
        """Insert a screening row; return its id (existing on conflict).

        ON CONFLICT (candidate, vacancy, run) DO UPDATE ai_status = old value
        is a no-op write — the trick is that "UPDATE happened" makes
        RETURNING id work even on conflict. One query, always returns id.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO candidate_screenings("
                "candidate_id, vacancy_id, run_id, user_id, "
                "ai_status, ai_score, ai_comment) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                "ON CONFLICT (candidate_id, vacancy_id, run_id) DO UPDATE SET "
                "ai_status = candidate_screenings.ai_status "
                "RETURNING id",
                candidate_id, vacancy_id, run_id, user_id,
                ai_status, ai_score, ai_comment,
            )
        return row["id"]

    async def list_screenings_by_candidate(
        self, candidate_id: int
    ) -> list[dict]:
        return await self._query_all(
            "SELECT * FROM candidate_screenings "
            "WHERE candidate_id = $1 ORDER BY created_at DESC, id DESC",
            candidate_id,
        )

    async def list_screenings_by_vacancy(
        self, vacancy_id: int
    ) -> list[dict]:
        return await self._query_all(
            "SELECT * FROM candidate_screenings "
            "WHERE vacancy_id = $1 ORDER BY created_at DESC, id DESC",
            vacancy_id,
        )

    async def list_screenings_by_run(self, run_id: int) -> list[dict]:
        return await self._query_all(
            "SELECT * FROM candidate_screenings "
            "WHERE run_id = $1 ORDER BY id ASC",
            run_id,
        )

    async def is_candidate_known_to_user(
        self, user_id: int, linkedin_url: str
    ) -> bool:
        """True if this user has at least one screening of this LinkedIn URL.

        Used for the PIPELINE_DONE summary ("X of N you've already seen on
        other vacancies"). Not for dedup — for dedup use
        is_candidate_screened_for_vacancy.
        """
        row = await self._query_one(
            "SELECT 1 FROM candidates c "
            "JOIN candidate_screenings s ON s.candidate_id = c.id "
            "WHERE c.linkedin_url = $1 AND s.user_id = $2 LIMIT 1",
            linkedin_url, user_id,
        )
        return row is not None

    async def is_candidate_screened_for_vacancy(
        self, linkedin_url: str, vacancy_id: int
    ) -> bool:
        """True if this LinkedIn URL was already screened against this vacancy.

        Used for dedup in pipelines: a candidate already screened for this
        vacancy (in any run) shouldn't be sent to the LLM again. Cross-
        vacancy is fine — different requirements, different result.
        """
        row = await self._query_one(
            "SELECT 1 FROM candidates c "
            "JOIN candidate_screenings s ON s.candidate_id = c.id "
            "WHERE c.linkedin_url = $1 AND s.vacancy_id = $2 LIMIT 1",
            linkedin_url, vacancy_id,
        )
        return row is not None

    # ----------------------------------------------------------------- guardrails

    # Column allow-lists: **fields kwargs build SQL, so reject unknown names
    # rather than emit a broken UPDATE or risk identifier injection.
    _COLUMNS = {
        "sessions": {
            "user_id", "pipeline_type", "step", "vacancy_id", "search_id",
            "pending_boolean", "pending_apify_params", "report_path",
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


async def _amain():
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
    args = parser.parse_args()

    async with await DB.connect() as db:
        if args.init:
            await db.initialize_from_schema()
            print("Initialized DB from schema.sql")
        elif args.migrate:
            applied = await db.apply_migrations()
            if applied:
                print(f"Applied migrations: {', '.join(applied)}")
            else:
                print("No pending migrations.")


def _main():
    # dotenv is loaded by the entry point that imports DB (e.g. bot/main.py).
    # For CLI use, load it here too.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    asyncio.run(_amain())


if __name__ == "__main__":
    _main()
