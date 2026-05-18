-- recruiter_assistant — full SQLite schema (v1)
--
-- Applied as-is for fresh installs. For existing DBs the client checks the
-- _migrations table and applies missing files from db/migrations/.
--
-- v1 has no Notion (result = .md file) and no LLM agent — schema reflects that:
-- no *_database_id / notion_page_* columns, no agent_invocations table.

PRAGMA foreign_keys = ON;

-- Tracks which migration files have been applied (see db/client.py).
CREATE TABLE IF NOT EXISTS _migrations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Whitelisted Telegram users.
CREATE TABLE IF NOT EXISTS users (
  telegram_user_id INTEGER PRIMARY KEY,
  display_name     TEXT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);

-- A session = one pipeline interaction, walked through a state machine.
CREATE TABLE IF NOT EXISTS sessions (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id               INTEGER NOT NULL REFERENCES users(telegram_user_id),
  pipeline_type         TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  step                  TEXT NOT NULL CHECK (step IN ('waiting_input', 'waiting_boolean_confirm', 'running', 'done', 'error', 'cancelled')),
  input_text            TEXT,   -- the JD or CV itself
  brief_text            TEXT,   -- optional brief (sent as a 2nd file), NULL if none
  boolean_text          TEXT,   -- final boolean (after user edits)
  boolean_text_original TEXT,   -- originally generated boolean (if edited)
  report_path           TEXT,   -- path to the .md report on disk (data/sessions/<id>/report.md)
  error_text            TEXT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_user      ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_step ON sessions(user_id, step);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);

-- One execution of a pipeline within a session.
CREATE TABLE IF NOT EXISTS runs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id     INTEGER NOT NULL REFERENCES sessions(id),
  user_id        INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- denormalized
  pipeline_type  TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  status         TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
  raw_apify_path TEXT,    -- path to the raw Apify dump on disk
  screening_json TEXT,    -- screening results (compact, ~10KB — ok in DB)
  report_md      TEXT,    -- final markdown report (mirror of the file, for quick SQL access)
  found_count    INTEGER,
  screened_count INTEGER,
  passed_count   INTEGER,
  cost_usd       REAL,
  duration_sec   REAL,
  error_text     TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_runs_session       ON runs(session_id);
CREATE INDEX IF NOT EXISTS idx_runs_user          ON runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_user_pipeline ON runs(user_id, pipeline_type);
CREATE INDEX IF NOT EXISTS idx_runs_created       ON runs(created_at);

-- Results of the vacancy_to_candidates pipeline.
CREATE TABLE IF NOT EXISTS candidates_found (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id           INTEGER NOT NULL REFERENCES runs(id),
  user_id          INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- denormalized
  linkedin_url     TEXT NOT NULL,
  name             TEXT,
  ai_status        TEXT CHECK (ai_status IN ('pass', 'fail', 'uncertain') OR ai_status IS NULL),
  ai_score         INTEGER,
  ai_comment       TEXT,
  raw_profile_json TEXT,    -- profile from Apify (compact — ok in DB)
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_candidates_run           ON candidates_found(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_user          ON candidates_found(user_id);
CREATE INDEX IF NOT EXISTS idx_candidates_user_linkedin ON candidates_found(user_id, linkedin_url);  -- for dedup
CREATE INDEX IF NOT EXISTS idx_candidates_user_status   ON candidates_found(user_id, ai_status);

-- Results of the cv_to_jobs pipeline.
CREATE TABLE IF NOT EXISTS vacancies_found (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id            INTEGER NOT NULL REFERENCES runs(id),
  user_id           INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- denormalized
  linkedin_url      TEXT NOT NULL,
  title             TEXT,
  company           TEXT,
  location          TEXT,
  ai_score          INTEGER,
  ai_recommendation TEXT,
  raw_job_json      TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vacancies_run           ON vacancies_found(run_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_user          ON vacancies_found(user_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_user_linkedin ON vacancies_found(user_id, linkedin_url);
