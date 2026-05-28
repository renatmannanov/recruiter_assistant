"""Shared pytest fixtures.

`db` fixture creates a fresh PG schema namespace per test and tears it
down — full isolation without docker/testcontainers. Tests hit the real
Postgres (same `recruiter_assistant_dev` instance the bot uses), so
asyncpg behaviour, types, and SQL-level constraints are exercised end-to-end.
"""

import os
import uuid

import asyncpg
import pytest_asyncio
from dotenv import load_dotenv

from db.client import DB, _build_dsn

# Load .env once at collection time so PG_* env vars are available.
load_dotenv()


@pytest_asyncio.fixture
async def db():
    """A fresh DB backed by a per-test Postgres schema namespace."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    dsn = _build_dsn()

    # Create the schema using a one-shot connection (not the pool).
    admin = await asyncpg.connect(dsn=dsn)
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        await admin.close()

    # Pool whose every connection is pinned to this schema.
    # `server_settings` is applied at connection startup and survives the
    # implicit RESET asyncpg runs on release — unlike an `init` callback,
    # which only runs once when the connection is first created.
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3,
        server_settings={"search_path": schema},
    )
    d = DB(pool)
    try:
        await d.initialize_from_schema()
        yield d
    finally:
        await d.close()
        admin = await asyncpg.connect(dsn=dsn)
        try:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            await admin.close()
