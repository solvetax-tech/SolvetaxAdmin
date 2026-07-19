-- ============================================================================
-- employee_tasks -- personal upcoming tasks / day calendar for staff
--
-- An employee schedules their own tasks at a time, optionally with a follow-up.
-- emp_id is taken from the JWT (owner), never client-sent. Tasks are PERSONAL:
-- the API scopes every read/write to emp_id = the caller (admins see their own
-- too; widen later if a "team calendar" is ever needed).
--
-- SLOTS (Google-Calendar style): time is handled in fixed 15-minute slots. A
-- task may block ONE OR MORE such slots for a single piece of work -- the exact
-- slot start-times it occupies are stored in time_slots (timestamptz[]).
-- scheduled_at mirrors the earliest slot (kept for day-window filtering + the
-- (emp_id, scheduled_at) index). The "available slots" endpoint walks a
-- working-day window in 15-min steps and marks a slot taken if it appears in any
-- of the caller's active tasks' time_slots. Reschedule just PATCHes time_slots.
--
-- NOTIFICATIONS are handled in the frontend (mirrors useFollowupReminders): a
-- 60s poll fires 10 min before scheduled_at and at followup_at. No DB flags are
-- needed -- the client de-dupes via sessionStorage, same as follow-ups.
--
-- VOCAB lives in code (status_constants.py), no CHECK constraints -- same
-- decision as the 2026-07-16 status-CHECK drop.
--   status: PENDING | IN_PROGRESS | DONE | CANCELLED   (default PENDING)
-- ============================================================================

BEGIN;

CREATE TABLE solvetax.employee_tasks (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Owner. From the JWT; the whole feature is scoped to this.
    emp_id            bigint NOT NULL
        REFERENCES solvetax.employees (emp_id),

    title             character varying(200) NOT NULL,
    description       text,

    -- Earliest booked slot (mirrors min(time_slots)); used for day filtering + index.
    scheduled_at      timestamp with time zone NOT NULL,
    -- The 15-min slot start-times this task blocks. One or more, all on one day.
    time_slots        timestamp with time zone[] NOT NULL,

    -- Validated in code (status_constants.py); no CHECK here, by convention.
    status            character varying(20) NOT NULL DEFAULT 'PENDING',

    -- Optional follow-up reminder (the second notification fires at this time).
    followup_at       timestamp with time zone,
    followup_note     text,

    -- Soft delete + timestamps, matching customer_services / issue_reports.
    is_active         boolean NOT NULL DEFAULT true,
    created_at        timestamp with time zone NOT NULL DEFAULT now(),
    updated_at        timestamp with time zone NOT NULL DEFAULT now()
);

-- The day-view list and the free-slot computation both scan (emp_id, day) by time.
CREATE INDEX idx_employee_tasks_emp_sched ON solvetax.employee_tasks (emp_id, scheduled_at);
-- The reminder poll scans upcoming follow-ups.
CREATE INDEX idx_employee_tasks_followup  ON solvetax.employee_tasks (followup_at)
    WHERE followup_at IS NOT NULL;

COMMIT;

-- ROLLBACK:
--   BEGIN;
--   DROP TABLE IF EXISTS solvetax.employee_tasks;
--   COMMIT;
