-- ============================================================================
-- employee_tasks -- duration_minutes -> time_slots
--
-- Tasks used to store a single start (scheduled_at) + a duration_minutes span.
-- They now block a SET of discrete 15-min slots for one piece of work, stored in
-- time_slots (timestamptz[]). This adds the column, backfills it by expanding
-- each old (scheduled_at, duration_minutes) span into its 15-min slots, then
-- drops duration_minutes.
--
-- Guarded on duration_minutes still existing, so it is a safe no-op on any DB
-- that was created fresh from the updated 2026-07-19_employee_tasks.sql (which
-- already ships time_slots and has no duration_minutes column).
-- ============================================================================

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'solvetax'
          AND table_name = 'employee_tasks'
          AND column_name = 'duration_minutes'
    ) THEN
        ALTER TABLE solvetax.employee_tasks
            ADD COLUMN IF NOT EXISTS time_slots timestamptz[];

        -- Expand each old span into its discrete 15-min slot start-times.
        UPDATE solvetax.employee_tasks t
        SET time_slots = ARRAY(
            SELECT t.scheduled_at + make_interval(mins => 15 * gs)
            FROM generate_series(0, GREATEST(t.duration_minutes / 15, 1) - 1) AS gs
        )
        WHERE time_slots IS NULL OR cardinality(time_slots) = 0;

        ALTER TABLE solvetax.employee_tasks
            ALTER COLUMN time_slots SET NOT NULL;

        ALTER TABLE solvetax.employee_tasks
            DROP COLUMN duration_minutes;
    END IF;
END $$;

COMMIT;

-- ROLLBACK:
--   BEGIN;
--   ALTER TABLE solvetax.employee_tasks
--       ADD COLUMN duration_minutes integer NOT NULL DEFAULT 15;
--   -- (time_slots length * 15 was the old duration; recompute if needed, then:)
--   ALTER TABLE solvetax.employee_tasks DROP COLUMN time_slots;
--   COMMIT;
