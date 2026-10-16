-- Postseason round of a game (e.g. "wild-card", "round-1", "cfp-semifinal",
-- "bowl"); NULL for regular-season games. Set by the importers.
-- Safe to run more than once.
ALTER TABLE games ADD COLUMN IF NOT EXISTS postseason_round text;
CREATE INDEX IF NOT EXISTS games_postseason_round_idx ON games (postseason_round);
