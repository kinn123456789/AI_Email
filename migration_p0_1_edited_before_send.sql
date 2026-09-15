-- P0-1: edited_before_send / is_unedited_ai_reply tracking columns.
--
-- PREPARED ONLY - NOT YET APPLIED. Do not run this against the database
-- until it has been reviewed and a deploy of the matching application code
-- (main.py / database.py / vector_search.py) is going out at the same time
-- - the code writes/reads these columns unconditionally once deployed.
--
-- messages.edited_before_send:
--   NULL  = unknown / pre-migration (row predates this column, or was never
--           sent through the human-reply path)
--   FALSE = the AI draft was sent unchanged
--   TRUE  = the AI draft was edited before sending
--
-- historical_emails.is_unedited_ai_reply:
--   FALSE = trusted historical reply (default - existing rows backfill to
--           this automatically, since they are all either pre-AI human
--           replies or Sent Mail imports)
--   TRUE  = an AI-generated reply sent unchanged; excluded from trusted
--           style-example retrieval by vector_search.search_similar_emails()

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS edited_before_send boolean;

ALTER TABLE public.historical_emails
  ADD COLUMN IF NOT EXISTS is_unedited_ai_reply boolean NOT NULL DEFAULT FALSE;
