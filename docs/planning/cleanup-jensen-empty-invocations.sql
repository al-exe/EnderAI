-- Cleanup: nuke empty-prompt Jensen invocations from /tf testing.
--
-- Context: before TF-201 (PR #95, merged 2026-05-25), record_document_consulted
-- never wrote a `prompt` field to the metrics_event payload, so live /tf calls
-- showed "" in the Recent Invocations table on each Agent specialist's profile.
-- Demo prep testing left a pile of these on Jensen's profile. After TF-201
-- deploys, new /tf calls store the prompt correctly; this script removes the
-- pre-fix noise so Jensen's profile reads clean on tape.
--
-- Run on Render Shell for the EnderAI-backend service:
--   psql $DATABASE_URL -f cleanup-jensen-empty-invocations.sql
--
-- Safe to re-run — it only deletes consult events with NO prompt text,
-- scoped to Alex's user, scoped to Jensen, scoped to the last 6 hours.
-- The BEGIN/COMMIT wrapper lets you ROLLBACK if the preview surprises you.

BEGIN;

-- 1. Preview: show what's about to be deleted.
SELECT
    occurred_at,
    payload->>'specialist_slug' AS specialist,
    payload->>'session_id'      AS session,
    COALESCE(NULLIF(payload->>'prompt', ''), '(empty)') AS prompt_preview
FROM metrics_event
WHERE kind = 'document.consulted'
  AND user_id = (SELECT id FROM "user" WHERE email = 'alexlee4190@gmail.com')
  AND payload->>'specialist_slug' = 'jensen'
  AND (payload->>'prompt' IS NULL OR payload->>'prompt' = '')
  AND occurred_at > now() - interval '6 hours'
ORDER BY occurred_at DESC;

-- 2. If the preview looks right, run the delete.
--    (To abort instead, type ROLLBACK; at the psql prompt before COMMIT.)
DELETE FROM metrics_event
WHERE kind = 'document.consulted'
  AND user_id = (SELECT id FROM "user" WHERE email = 'alexlee4190@gmail.com')
  AND payload->>'specialist_slug' = 'jensen'
  AND (payload->>'prompt' IS NULL OR payload->>'prompt' = '')
  AND occurred_at > now() - interval '6 hours';

COMMIT;
