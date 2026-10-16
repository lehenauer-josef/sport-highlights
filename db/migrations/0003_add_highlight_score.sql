-- Scorer score (importer/highlight_scorer.py) of the auto-picked highlight in
-- video_id. NULL when no video was picked, for games imported before this
-- column existed, and for videos chosen by hand in the review queue.
-- Safe to run more than once.
ALTER TABLE games ADD COLUMN IF NOT EXISTS highlight_score integer;
