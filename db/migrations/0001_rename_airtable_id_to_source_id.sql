-- Rename the legacy Airtable key column to source_id (teams + games).
-- Safe to run more than once: each step only runs if the old name still exists.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['teams', 'games'] LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = t AND column_name = 'airtable_id'
    ) THEN
      EXECUTE format('ALTER TABLE %I RENAME COLUMN airtable_id TO source_id', t);
    END IF;

    -- Renaming the unique constraint also renames its backing index.
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_airtable_id_unique') THEN
      EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I',
        t, t || '_airtable_id_unique', t || '_source_id_unique');
    END IF;

    -- PostgreSQL 18+ stores named NOT NULL constraints.
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_airtable_id_not_null') THEN
      EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I',
        t, t || '_airtable_id_not_null', t || '_source_id_not_null');
    END IF;
  END LOOP;
END $$;
