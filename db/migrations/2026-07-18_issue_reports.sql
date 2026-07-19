-- ============================================================================
-- issue_reports -- in-app issue / bug reporting
--
-- Staff raise an issue (bug, blocker, request) with a priority and optional
-- photos. reporter_emp_id is taken from the JWT, never sent by the client, so a
-- reporter can't file under someone else's id.
--
-- VISIBILITY is enforced in the API, NOT here (a table can't see the JWT):
--   ADMIN     -> every row
--   MANAGER   -> own rows + rows raised by their reports
--                (employees.manager_emp_id = the manager's emp_id)
--   EMPLOYEE  -> only their own rows
-- The reporter index below backs both the "my issues" and manager fan-out.
--
-- VOCAB lives in code, not CHECK constraints -- same decision as the 2026-07-16
-- drop of the 26 status value CHECKs (status_constants.py is the single guard).
-- Add these before shipping:
--   ISSUE_PRIORITIES = LOW | MEDIUM | HIGH | URGENT   (column default MEDIUM)
--   ISSUE_STATUSES   = OPEN | IN_PROGRESS | RESOLVED  (column default OPEN)
-- ============================================================================

BEGIN;

CREATE TABLE solvetax.issue_reports (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Who raised it. From the JWT (auto-captured), FK to employees.
    reporter_emp_id    bigint NOT NULL
        REFERENCES solvetax.employees (emp_id),

    title              character varying(200) NOT NULL,
    description        text NOT NULL,

    -- Validated in code (status_constants.py); no CHECK here, by convention.
    priority           character varying(20) NOT NULL DEFAULT 'MEDIUM',
    status             character varying(20) NOT NULL DEFAULT 'OPEN',

    -- Azure Blob URLs, uploaded the same way as business_image_url / gst docs.
    -- text[] keeps a handful of photos inline; move to a child table only if you
    -- later need per-photo metadata (caption, uploaded_at, ...).
    photo_urls         text[] NOT NULL DEFAULT ARRAY[]::text[],

    -- Resolution trail, filled when status moves to RESOLVED.
    resolved_by_emp_id bigint
        REFERENCES solvetax.employees (emp_id),
    resolved_at        timestamp with time zone,
    resolution_note    text,

    -- Soft delete, matching customer_services etc.
    is_active          boolean NOT NULL DEFAULT true,
    created_at         timestamp with time zone NOT NULL DEFAULT now(),
    updated_at         timestamp with time zone NOT NULL DEFAULT now()
);

-- "My issues" + the manager fan-out both filter by reporter.
CREATE INDEX idx_issue_reports_reporter   ON solvetax.issue_reports (reporter_emp_id);
-- Common list filters / ordering.
CREATE INDEX idx_issue_reports_status     ON solvetax.issue_reports (status);
CREATE INDEX idx_issue_reports_priority   ON solvetax.issue_reports (priority);
CREATE INDEX idx_issue_reports_created_at ON solvetax.issue_reports (created_at DESC);

COMMIT;

-- ROLLBACK (keep alongside, per repo habit -- e.g. the drop_status_value_checks pair):
--   BEGIN;
--   DROP TABLE IF EXISTS solvetax.issue_reports;
--   COMMIT;
