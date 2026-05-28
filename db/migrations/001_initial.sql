-- Migration 001_initial — full v1 schema (Postgres).
--
-- Identical DDL to db/schema.sql except for the _migrations table itself
-- (created by schema.sql at init time). Applied to existing DBs that predate
-- the migration mechanism, or as the baseline migration. All statements use
-- IF NOT EXISTS so re-running is harmless.
--
-- v1 has no Notion (result = .md file) and no LLM agent — schema reflects that:
-- no *_database_id / notion_page_* columns, no agent_invocations table.

-- Whitelisted Telegram users.
-- telegram_user_id is a natural key (Telegram's own user id), not a surrogate.
CREATE TABLE IF NOT EXISTS users (
  telegram_user_id BIGINT PRIMARY KEY,
  display_name     TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);

-- A session = one pipeline interaction, walked through a state machine.
CREATE TABLE IF NOT EXISTS sessions (
  id                    BIGSERIAL PRIMARY KEY,
  user_id               BIGINT NOT NULL REFERENCES users(telegram_user_id),
  pipeline_type         TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  step                  TEXT NOT NULL CHECK (step IN ('waiting_input', 'waiting_boolean_confirm', 'running', 'done', 'error', 'cancelled')),
  input_text            TEXT,
  brief_text            TEXT,
  boolean_text          TEXT,
  boolean_text_original TEXT,
  report_path           TEXT,
  error_text            TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user      ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_step ON sessions(user_id, step);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);

-- One execution of a pipeline within a session.
CREATE TABLE IF NOT EXISTS runs (
  id             BIGSERIAL PRIMARY KEY,
  session_id     BIGINT NOT NULL REFERENCES sessions(id),
  user_id        BIGINT NOT NULL REFERENCES users(telegram_user_id),
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

-- Results of the vacancy_to_candidates pipeline.
CREATE TABLE IF NOT EXISTS candidates_found (
  id               BIGSERIAL PRIMARY KEY,
  run_id           BIGINT NOT NULL REFERENCES runs(id),
  user_id          BIGINT NOT NULL REFERENCES users(telegram_user_id),
  linkedin_url     TEXT NOT NULL,
  name             TEXT,
  ai_status        TEXT CHECK (ai_status IN ('pass', 'fail', 'uncertain') OR ai_status IS NULL),
  ai_score         BIGINT,
  ai_comment       TEXT,
  raw_profile_json TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_candidates_run           ON candidates_found(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_user          ON candidates_found(user_id);
CREATE INDEX IF NOT EXISTS idx_candidates_user_linkedin ON candidates_found(user_id, linkedin_url);
CREATE INDEX IF NOT EXISTS idx_candidates_user_status   ON candidates_found(user_id, ai_status);

-- Results of the cv_to_jobs pipeline.
CREATE TABLE IF NOT EXISTS vacancies_found (
  id                BIGSERIAL PRIMARY KEY,
  run_id            BIGINT NOT NULL REFERENCES runs(id),
  user_id           BIGINT NOT NULL REFERENCES users(telegram_user_id),
  linkedin_url      TEXT NOT NULL,
  title             TEXT,
  company           TEXT,
  location          TEXT,
  ai_score          BIGINT,
  ai_recommendation TEXT,
  raw_job_json      TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vacancies_run           ON vacancies_found(run_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_user          ON vacancies_found(user_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_user_linkedin ON vacancies_found(user_id, linkedin_url);
