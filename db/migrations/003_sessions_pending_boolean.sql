-- 003_sessions_pending_boolean.sql
--
-- Add a transient column to hold the LLM-generated boolean between
-- WAITING_INPUT and WAITING_BOOLEAN_CONFIRM, before the user confirms (or
-- edits) it. Once confirmed, the bot creates a searches row and clears
-- pending_boolean.
--
-- Why a column and not in-memory: the bot may restart between "boolean
-- generated" and "user confirmed" — an in-memory dict would lose state and
-- the user would have to /cancel and start over.
--
-- Why not a row in `searches` from the start: `searches` represents a
-- committed query that actually went to Apify. Pre-confirm drafts shouldn't
-- pollute that table (especially if the user /cancels).

ALTER TABLE sessions ADD COLUMN pending_boolean TEXT;
