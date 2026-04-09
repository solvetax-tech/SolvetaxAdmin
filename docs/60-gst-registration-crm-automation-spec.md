# GST Registration CRM Automation Spec (End-to-End)

Owner: Engineering Team  
Last Verified On: 2026-04-08

This document is the implementation blueprint for GST CRM automation:
- static deal stages,
- dynamic call statuses and call types,
- automatic stage movement from call updates,
- automatic movement to `GST_REGISTRATION_DONE` from registration approval,
- strict tracking of `call_attempted` and `call_connected`,
- full activity audit (who did what, when).

---

## 1) Scope and objective

### Objective
Build a deterministic CRM workflow where callers update call outcomes and the system:
1. increments counters,
2. moves stage based on strict rules,
3. records complete activity history,
4. avoids invalid transitions.

### In scope
- GST registration lead lifecycle only.
- Two pitch types: first and final.
- Dynamic call statuses (config table).
- Static stage list (fixed).

### Out of scope
- Dynamic stage creation/edit UI.
- Generic multi-pipeline engine.

---

## 2) Canonical stage model (static)

Use these exact stage codes:

1. `FRESH_LEAD`
2. `PENDING_REGISTRATION_DATA`
3. `FOLLOW_UP`
4. `INTERESTED`
5. `GST_REGISTRATION_DONE`
6. `SCHEDULED_PAYMENTS`
7. `SUBSCRIBED` (closed won)
8. `NOT_INTERESTED` (closed lost, first pitch only)

Rules:
- `SUBSCRIBED` and `NOT_INTERESTED` are final closed stages.
- `NOT_INTERESTED` is allowed only in first pitch flow.

---

## 3) Pitch types (dynamic config)

Required call type codes:
- `FIRST_PITCH_CALL`
- `FINAL_PITCH_CALL`

These remain configurable rows but logic references these code values.

---

## 4) Call statuses (dynamic config)

Recommended status codes:
- `CALL_NOT_ANSWERED`
- `CALL_NOT_CONNECTED`
- `CALL_BUSY`
- `CALL_BACK`
- `CONNECTED_AND_SCHEDULED`
- `SCHEDULED_PAYMENT`
- `SUBSCRIBED_COMPLETED`
- `NOT_INTERESTED`

For `FIRST_PITCH_CALL`, allowed call statuses are:
- `CALL_NOT_ANSWERED`
- `CALL_NOT_CONNECTED`
- `CALL_BUSY`
- `CALL_BACK`
- `CONNECTED_AND_SCHEDULED`
- `NOT_INTERESTED`

Keep dynamic in DB (`is_active`) but never break code-level meaning of these canonical codes.

---

## 5) Counter semantics (critical)

On every call-status update event:
- `call_attempted_count = call_attempted_count + 1`
- `last_dailed_at = NOW()`

`call_connected_count` increments only when status qualifies:

### First pitch connected statuses
- `CONNECTED_AND_SCHEDULED`
- `CALL_BACK`

### Final pitch connected statuses
- `SCHEDULED_PAYMENT`
- `SUBSCRIBED_COMPLETED`

---

## 6) Stage movement rules (source of truth)

## 6.1 First pitch flow

Allowed current stages:
- `FRESH_LEAD`
- `PENDING_REGISTRATION_DATA`
- `FOLLOW_UP`
- `INTERESTED`

Not allowed current stages:
- `GST_REGISTRATION_DONE`
- `SCHEDULED_PAYMENTS`
- `SUBSCRIBED`
- `NOT_INTERESTED`

Status to stage mapping:
- `CALL_NOT_ANSWERED` -> no stage change
- `CALL_NOT_CONNECTED` -> no stage change
- `CALL_BUSY` -> `FOLLOW_UP` (remain if already `FOLLOW_UP`)
- `CALL_BACK` -> `FOLLOW_UP` (follow-up datetime required)
- `CONNECTED_AND_SCHEDULED` -> `INTERESTED`
- `NOT_INTERESTED` -> `NOT_INTERESTED` (close)
- `SUBSCRIBED_COMPLETED` -> reject (invalid in first pitch)
- `SCHEDULED_PAYMENT` -> reject (invalid in first pitch)

Extra validation:
- For `CALL_BACK`, `followup_at` is mandatory and must be in the future.

## 6.2 Move to GST registration done

Not call-driven. System/ops-driven:
- Triggered when `gst_registration.registration_status` becomes `APPROVED`.
- Deal stage becomes `GST_REGISTRATION_DONE`.
- Activity is logged as system event.

## 6.3 Final pitch flow

Allowed current stages:
- `GST_REGISTRATION_DONE`
- `SCHEDULED_PAYMENTS` (for follow-up progression)

Status to stage mapping:
- `SCHEDULED_PAYMENT`:
  - `GST_REGISTRATION_DONE` -> `SCHEDULED_PAYMENTS`
  - `SCHEDULED_PAYMENTS` -> remain `SCHEDULED_PAYMENTS` 
  - `followup_at` required and must be in the future
- `SUBSCRIBED_COMPLETED`:
  - `GST_REGISTRATION_DONE` -> `SUBSCRIBED`
  - `SCHEDULED_PAYMENTS` -> `SUBSCRIBED`
- `NOT_INTERESTED` -> reject (not allowed in final pitch)
- `CALL_NOT_ANSWERED`/`CALL_NOT_CONNECTED`/`CALL_BUSY`/`CALL_BACK`/`CONNECTED_AND_SCHEDULED`:
  - optional: allow as no-stage-change events
  - recommended: keep allowed but no transition unless business explicitly blocks

## 6.4 Final stage protection

If stage is `SUBSCRIBED` or `NOT_INTERESTED`:
- reject all stage-changing updates,
- optionally allow note-only activities without call-status update.

---

## 7) Database model (DDL)

```sql
CREATE TABLE solvetax.crm_leads (
  id BIGSERIAL PRIMARY KEY,
  mobile VARCHAR(20) NOT NULL,
  gst_registration_id BIGINT NULL,
  stage VARCHAR(40) NOT NULL,
  call_attempted_count INT NOT NULL DEFAULT 0,
  call_connected_count INT NOT NULL DEFAULT 0,
  last_dailed_at TIMESTAMPTZ NULL,
  followup_at TIMESTAMPTZ NULL,
  rm_id BIGINT NULL,
  op_id BIGINT NULL,
  remarks TEXT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_crm_stage CHECK (
    stage IN (
      'FRESH_LEAD',
      'PENDING_REGISTRATION_DATA',
      'FOLLOW_UP',
      'INTERESTED',
      'GST_REGISTRATION_DONE',
      'SCHEDULED_PAYMENTS',
      'SUBSCRIBED',
      'NOT_INTERESTED'
    )
  ),
  CONSTRAINT fk_crm_leads_gst_registration FOREIGN KEY (gst_registration_id)
    REFERENCES solvetax.gst_registration(id) ON DELETE SET NULL,
  CONSTRAINT fk_crm_leads_rm FOREIGN KEY (rm_id)
    REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL,
  CONSTRAINT fk_crm_leads_op FOREIGN KEY (op_id)
    REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL
);

CREATE INDEX idx_crm_leads_stage_active
  ON solvetax.crm_leads(stage, is_active);
CREATE INDEX idx_crm_leads_followup
  ON solvetax.crm_leads(followup_at)
  WHERE is_active = TRUE;
CREATE INDEX idx_crm_leads_mobile
  ON solvetax.crm_leads(mobile);
```

```sql
CREATE TABLE solvetax.crm_call_types (
  id BIGSERIAL PRIMARY KEY,
  code VARCHAR(40) UNIQUE NOT NULL,
  name VARCHAR(80) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO solvetax.crm_call_types(code, name) VALUES
('FIRST_PITCH_CALL', 'First Pitch Call'),
('FINAL_PITCH_CALL', 'Final Pitch Call');
```

```sql
CREATE TABLE solvetax.crm_call_statuses (
  id BIGSERIAL PRIMARY KEY,
  code VARCHAR(50) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO solvetax.crm_call_statuses(code, name) VALUES
('CALL_NOT_ANSWERED', 'Call Not Answered'),
('CALL_NOT_CONNECTED', 'Call Not Connected'),
('CALL_BUSY', 'Call Busy'),
('CALL_BACK', 'Call Back'),
('CONNECTED_AND_SCHEDULED', 'Connected and Scheduled'),
('SCHEDULED_PAYMENT', 'Scheduled Payment'),
('SUBSCRIBED_COMPLETED', 'Subscribed/Completed'),
('NOT_INTERESTED', 'Not Interested');
```

```sql
CREATE TABLE solvetax.crm_activities (
  id BIGSERIAL PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES solvetax.crm_leads(id) ON DELETE CASCADE,
  activity_type VARCHAR(30) NOT NULL DEFAULT 'CALL', -- CALL, NOTE, SYSTEM
  call_type_code VARCHAR(40) NULL REFERENCES solvetax.crm_call_types(code),
  call_status_code VARCHAR(50) NULL REFERENCES solvetax.crm_call_statuses(code),
  old_stage VARCHAR(40) NULL,
  new_stage VARCHAR(40) NULL,
  followup_at TIMESTAMPTZ NULL,
  remarks TEXT NULL,
  performed_by BIGINT NULL REFERENCES solvetax.employees(emp_id), -- null for system jobs
  performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_crm_activities_deal_time
  ON solvetax.crm_activities(lead_id, performed_at DESC);
CREATE INDEX idx_crm_activities_actor_time
  ON solvetax.crm_activities(performed_by, performed_at DESC);
```

Optional helper table if you want config-driven mapping:

```sql
CREATE TABLE solvetax.crm_stage_transition_rules (
  id BIGSERIAL PRIMARY KEY,
  call_type_code VARCHAR(40) NOT NULL,
  call_status_code VARCHAR(50) NOT NULL,
  from_stage VARCHAR(40) NOT NULL,
  to_stage VARCHAR(40) NULL, -- null means no stage change
  requires_followup BOOLEAN NOT NULL DEFAULT FALSE,
  is_allowed BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(call_type_code, call_status_code, from_stage)
);
```

---

## 8) API contract

## 8.1 Update call result endpoint

`POST /api/v1/crm/leads/{lead_id}/call-update`

Request:
```json
{
  "call_type_code": "FIRST_PITCH_CALL",
  "call_status_code": "CALL_BACK",
  "followup_at": "2026-04-10T11:30:00+05:30",
  "remarks": "Asked to call after lunch"
}
```

Response:
```json
{
  "message": "Call update applied",
  "lead_id": 123,
  "old_stage": "PENDING_REGISTRATION_DATA",
  "new_stage": "FOLLOW_UP",
  "call_attempted_count": 7,
  "call_connected_count": 3,
  "last_dailed_at": "2026-04-08T14:10:12.123+05:30",
  "followup_at": "2026-04-10T11:30:00+05:30",
  "activity_id": 9981
}
```

Validation failures:
- invalid `call_type_code` or inactive config
- invalid `call_status_code` or inactive config
- stage/call-type mismatch
- forbidden status in flow (for example `NOT_INTERESTED` in final pitch)
- missing future `followup_at` when required
- closed-stage protection hit

## 8.2 Read deal timeline endpoint

`GET /api/v1/crm/leads/{lead_id}/activities?limit=50&offset=0`

Returns complete history ordered by time.

---

## 9) Service-layer algorithm (required)

1. Begin transaction.
2. `SELECT ... FOR UPDATE` on lead row.
3. Resolve call type/status rows by code (`is_active=true`).
4. Apply final-stage protection.
5. Validate call-type allowed for current stage.
6. Compute stage transition using rules.
7. Enforce follow-up requirement if applicable.
8. Compute counters:
   - attempted always +1
   - connected +1 only for connected statuses.
9. Update `crm_leads` (`stage`, counters, last_dailed_at, followup_at, updated_at).
10. Insert `crm_activities` with old/new stage and actor.
11. Commit.

---

## 10) Event automation from GST registration approval

When `solvetax.gst_registration.registration_status` changes to `APPROVED`:

1. Find active CRM lead linked by `gst_registration_id` (or create if missing as per business).
2. If lead stage not closed:
   - set `stage='GST_REGISTRATION_DONE'`
   - `updated_at=NOW()`
3. Insert `crm_activities`:
   - `activity_type='SYSTEM'`
   - old/new stage
   - remark like `Auto moved on GST approval`

Implementation options:
- application event handler after registration update API success (preferred),
- or DB trigger if all updates happen in DB and you can control side effects safely.

---

## 11) Security and permissions

- Caller update endpoint: `EMPLOYEE:WRITE` (or your CRM feature flag).
- Timeline view: `EMPLOYEE:READ`.
- Visibility filter must follow RM/OP/team logic already used in your project.
- Keep actor identity (`performed_by`) from JWT subject.

---

## 12) Migration plan

1. Create new CRM tables.
2. Seed call types and call statuses.
3. Seed optional transition rules table.
4. Backfill `crm_leads` from existing leads/customers if needed.
5. Deploy call-update API.
6. Deploy approval automation hook.
7. Roll out in shadow mode for 2-3 days (log-only stage decisions).
8. Enable strict mode (apply transitions).

---

## 13) UAT checklist

1. First pitch + `CALL_BACK` moves to `FOLLOW_UP`, attempted increments, connected increments, followup required.
2. First pitch + `SUBSCRIBED_COMPLETED` rejected.
3. Final pitch + `NOT_INTERESTED` rejected.
4. `GST_REGISTRATION_DONE -> SCHEDULED_PAYMENTS -> SUBSCRIBED` works.
5. Closed stage blocks further transitions.
6. Approval event auto-moves stage to `GST_REGISTRATION_DONE`.
7. Every call update writes one activity row with correct actor and timestamp.

---

## 14) Recommended next files in your backend

- New module: `app/crm/deals.py`
- New schemas: `app/crm/schemas.py`
- Reuse permissions helpers from `app/security/rbac.py`
- Reuse visibility builders from `app/utils.py`
- Include router in `app/main.py`

