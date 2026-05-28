-- recruiter_assistant — full Postgres schema (v2, relational model, step_5.5).
--
-- This file is the snapshot of "what a fresh DB should look like right now".
-- Applied as-is for fresh installs by db/client.py.initialize_from_schema().
-- For existing DBs the client compares against db/migrations/ and applies
-- whatever's missing.
--
-- Source-of-truth convention: when a new migration NNN_xxx.sql is added, this
-- file MUST be updated to reflect the resulting schema. Otherwise tests
-- (which load this file) diverge from production (which got there via
-- migrations). Caught in step_7 — see progress.md.

-- Tracks which migration files have been applied (see db/client.py).
CREATE TABLE IF NOT EXISTS _migrations (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- ENUM types

-- Native PG ENUMs (replaced CHECK-based string columns in migration 002).
-- Adding values later requires ALTER TYPE — accepted trade-off vs. free text.
DO $$ BEGIN
  CREATE TYPE ai_status AS ENUM ('pass', 'uncertain', 'fail');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE vacancy_source AS ENUM ('manual', 'apify_job_search');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- --------------------------------------------------------------------- users

-- Whitelisted Telegram users.
-- telegram_user_id is a natural key (Telegram's own user id), not a surrogate.
CREATE TABLE IF NOT EXISTS users (
  telegram_user_id BIGINT PRIMARY KEY,
  display_name     TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);

-- ----------------------------------------------------------------- companies

CREATE TABLE IF NOT EXISTS companies (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  notes      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- vacancies

CREATE TABLE IF NOT EXISTS vacancies (
  id                   BIGSERIAL PRIMARY KEY,
  company_id           BIGINT REFERENCES companies(id),
  name                 TEXT,                    -- short UI label ("Sonia ASR")
  jd_text              TEXT,                    -- source=manual: pasted JD
  brief_text           TEXT,                    -- optional internal brief
  linkedin_url         TEXT,                    -- source=apify_job_search: posting URL
  source               vacancy_source NOT NULL,
  title                TEXT,                    -- apify-source: parsed title
  location             TEXT,
  seniority            TEXT,
  created_by_user_id   BIGINT REFERENCES users(telegram_user_id),
  discovered_in_run_id BIGINT,                  -- FK added after runs is defined (see ALTER below)
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vacancies_company    ON vacancies(company_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_created_by ON vacancies(created_by_user_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_source     ON vacancies(source);

-- One LinkedIn job URL = one global vacancy row (mirrors candidates.linkedin_url
-- UNIQUE). Partial — manual vacancies have NULL linkedin_url.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vacancies_linkedin_url_unique
  ON vacancies(linkedin_url)
  WHERE source = 'apify_job_search';

-- ---------------------------------------------------------------- candidates

-- Global registry: one LinkedIn profile = one row, even after multiple
-- screenings across vacancies. linkedin_url is the natural key.
CREATE TABLE IF NOT EXISTS candidates (
  id               BIGSERIAL PRIMARY KEY,
  linkedin_url     TEXT NOT NULL UNIQUE,
  name             TEXT,
  headline         TEXT,
  location         TEXT,
  about            TEXT,
  raw_profile_json JSONB,
  first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_last_seen ON candidates(last_seen_at DESC);

-- ------------------------------------------------------------------ sessions

-- Thin state-machine row. Heavy text (JD, brief, boolean) lives in the entities
-- it points to: vacancies (jd_text/brief_text) and searches (boolean_text).
CREATE TABLE IF NOT EXISTS sessions (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(telegram_user_id),
  pipeline_type TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  step          TEXT NOT NULL CHECK (step IN ('waiting_input', 'waiting_boolean_confirm', 'running', 'done', 'error', 'cancelled')),
  vacancy_id    BIGINT REFERENCES vacancies(id),
  search_id     BIGINT,                  -- FK added after searches is defined (see ALTER below)
  report_path   TEXT,                    -- path to the .md report on disk (data/sessions/<id>/report.md)
  error_text    TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user      ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_step ON sessions(user_id, step);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_vacancy   ON sessions(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_sessions_search    ON sessions(search_id);

-- ---------------------------------------------------------------------- runs

-- One execution of a pipeline within a session.
CREATE TABLE IF NOT EXISTS runs (
  id             BIGSERIAL PRIMARY KEY,
  session_id     BIGINT NOT NULL REFERENCES sessions(id),
  user_id        BIGINT NOT NULL REFERENCES users(telegram_user_id),  -- denormalized
  pipeline_type  TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  status         TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
  raw_apify_path TEXT,
  screening_json TEXT,
  report_md      TEXT,
  found_count    BIGINT,
  screened_count BIGINT,
  passed_count   BIGINT,
  cost_usd       DOUBLE PRECISION,
  duration_sec   DOUBLE PRECISION,
  error_text     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runs_session       ON runs(session_id);
CREATE INDEX IF NOT EXISTS idx_runs_user          ON runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_user_pipeline ON runs(user_id, pipeline_type);
CREATE INDEX IF NOT EXISTS idx_runs_created       ON runs(created_at);

-- Late-bind FKs that reference tables defined further down.
DO $$ BEGIN
  ALTER TABLE vacancies
    ADD CONSTRAINT vacancies_discovered_in_run_id_fkey
    FOREIGN KEY (discovered_in_run_id) REFERENCES runs(id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ------------------------------------------------------------------ searches

-- Each apify run for a vacancy = one row. Keeps a history of boolean iterations.
-- boolean_text:     query that actually went to Apify (always set).
-- original_boolean: what the LLM produced before user edits. NULL when the
--                   user didn't edit.
CREATE TABLE IF NOT EXISTS searches (
  id                 BIGSERIAL PRIMARY KEY,
  vacancy_id         BIGINT NOT NULL REFERENCES vacancies(id),
  boolean_text       TEXT NOT NULL,
  original_boolean   TEXT,
  created_by_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_searches_vacancy ON searches(vacancy_id);

-- Late-bind FK on sessions.search_id (searches defined after sessions above).
DO $$ BEGIN
  ALTER TABLE sessions
    ADD CONSTRAINT sessions_search_id_fkey
    FOREIGN KEY (search_id) REFERENCES searches(id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- -------------------------------------------------------- candidate_screenings

-- The join table: which candidate was screened against which vacancy in which
-- run, and what the LLM decided.
--
-- UNIQUE (candidate_id, vacancy_id, run_id) — a single run never screens the
-- same person against the same vacancy twice. Cross-vacancy or re-run is fine.
CREATE TABLE IF NOT EXISTS candidate_screenings (
  id           BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT NOT NULL REFERENCES candidates(id),
  vacancy_id   BIGINT NOT NULL REFERENCES vacancies(id),
  run_id       BIGINT NOT NULL REFERENCES runs(id),
  user_id      BIGINT NOT NULL REFERENCES users(telegram_user_id),
  ai_status    ai_status,
  ai_score     INTEGER,
  ai_comment   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (candidate_id, vacancy_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_screenings_candidate ON candidate_screenings(candidate_id);
CREATE INDEX IF NOT EXISTS idx_screenings_vacancy   ON candidate_screenings(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_screenings_run       ON candidate_screenings(run_id);
CREATE INDEX IF NOT EXISTS idx_screenings_user      ON candidate_screenings(user_id);
