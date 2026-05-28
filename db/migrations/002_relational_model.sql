-- 002_relational_model.sql
--
-- Phase 2 of step_5.5: lift the data model from "per-run blobs" to a relational
-- one. Introduces global candidates, vacancies-as-entities with a history of
-- boolean searches, and screenings linking candidates × vacancies × runs.
--
-- This migration is destructive: it drops candidates_found and vacancies_found
-- and removes denormalized text columns from sessions. TRUNCATE of all data
-- tables (users/sessions/runs/candidates_found/vacancies_found) was performed
-- before this migration is applied — see progress.md step_7.

-- ---------------------------------------------------------------- ENUM types

-- Native PG ENUMs replace the CHECK-based string columns from the v1 schema.
-- Adding values later requires a separate ALTER TYPE migration — accepted
-- trade-off vs. free-form text.
CREATE TYPE ai_status AS ENUM ('pass', 'uncertain', 'fail');
CREATE TYPE vacancy_source AS ENUM ('manual', 'apify_job_search');

-- ------------------------------------------------------------------ companies

CREATE TABLE companies (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  notes      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ vacancies

CREATE TABLE vacancies (
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
  discovered_in_run_id BIGINT REFERENCES runs(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vacancies_company    ON vacancies(company_id);
CREATE INDEX idx_vacancies_created_by ON vacancies(created_by_user_id);
CREATE INDEX idx_vacancies_source     ON vacancies(source);

-- One LinkedIn job URL = one global vacancy row (mirrors candidates.linkedin_url
-- UNIQUE). Partial — manual vacancies have NULL linkedin_url and shouldn't
-- conflict with each other.
CREATE UNIQUE INDEX idx_vacancies_linkedin_url_unique
  ON vacancies(linkedin_url)
  WHERE source = 'apify_job_search';

-- ------------------------------------------------------------------ candidates

-- Global registry: one LinkedIn profile = one row, even after multiple
-- screenings across vacancies. linkedin_url is the natural key.
CREATE TABLE candidates (
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

CREATE INDEX idx_candidates_last_seen ON candidates(last_seen_at DESC);

-- -------------------------------------------------------------------- searches

-- Each apify run for a vacancy = one row. Keeps a history of boolean iterations
-- per vacancy (re-tune the boolean -> new search -> new candidates).
--
-- boolean_text:     the query that actually went to Apify (always set).
-- original_boolean: what the LLM produced before user edits. NULL when the user
--                   didn't edit (no value in storing a duplicate).
CREATE TABLE searches (
  id                 BIGSERIAL PRIMARY KEY,
  vacancy_id         BIGINT NOT NULL REFERENCES vacancies(id),
  boolean_text       TEXT NOT NULL,
  original_boolean   TEXT,
  created_by_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_searches_vacancy ON searches(vacancy_id);

-- -------------------------------------------------------- candidate_screenings

-- The join table: which candidate was screened against which vacancy in which
-- run, and what the LLM decided.
--
-- UNIQUE (candidate_id, vacancy_id, run_id) — a single run never screens the
-- same person against the same vacancy twice. Cross-vacancy or re-run is fine.
CREATE TABLE candidate_screenings (
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

CREATE INDEX idx_screenings_candidate ON candidate_screenings(candidate_id);
CREATE INDEX idx_screenings_vacancy   ON candidate_screenings(vacancy_id);
CREATE INDEX idx_screenings_run       ON candidate_screenings(run_id);
CREATE INDEX idx_screenings_user      ON candidate_screenings(user_id);

-- ---------------------------------------------------------- sessions: ALTER

-- Denormalized text moves to vacancies (jd_text/brief_text) and searches
-- (boolean_text/original_boolean). sessions becomes a thin state-machine row
-- linked to the entities it created.
ALTER TABLE sessions DROP COLUMN input_text;
ALTER TABLE sessions DROP COLUMN brief_text;
ALTER TABLE sessions DROP COLUMN boolean_text;
ALTER TABLE sessions DROP COLUMN boolean_text_original;

ALTER TABLE sessions ADD COLUMN vacancy_id BIGINT REFERENCES vacancies(id);
ALTER TABLE sessions ADD COLUMN search_id  BIGINT REFERENCES searches(id);

CREATE INDEX idx_sessions_vacancy ON sessions(vacancy_id);
CREATE INDEX idx_sessions_search  ON sessions(search_id);

-- ----------------------------------------------------- drop legacy v1 tables

-- candidates_found -> candidates + candidate_screenings (step_9 wires writes).
-- vacancies_found  -> vacancies (with source='apify_job_search') + a future
--                     job_screenings table when cv_to_jobs leaves stub status.
DROP TABLE IF EXISTS candidates_found CASCADE;
DROP TABLE IF EXISTS vacancies_found  CASCADE;
