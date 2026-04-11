# GST Registration CRM Automation Spec (End-to-End)

Owner: Engineering Team  
Last Verified On: 2026-04-11

> **HTTP API & UI integration:** The live REST contract, RBAC, row-level visibility, config endpoints (`/stages`, `/ui-mappings`), list filters (`/filter`, `/activities/filter`), and request/response shapes are documented in **[`docs/70-crm-ui-integration-guide.md`](70-crm-ui-integration-guide.md)**. Implementation lives in **[`app/crm/crm_leads.py`](../app/crm/crm_leads.py)**. Where this spec disagrees with **70** or the code, treat **70 + code** as authoritative.

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
- Dynamic call statuses (config table) plus **`crm_ui_mappings`** for UI-driven allowed combinations ([`docs/64-crm-ui-mappings.sql`](64-crm-ui-mappings.sql)).
- Stage list: canonical rows in **`crm_lead_stages`** ([`docs/65-crm-lead-stages.sql`](65-crm-lead-stages.sql)) with surrogate **`id`** + unique **`code`**.

### Out of scope
- Dynamic stage creation/edit UI.
- Generic multi-pipeline engine.

---

## 2) Canonical stage model (static)

Use these exact stage codes (order for UI is defined in **`crm_lead_stages.sort_order`**):

1. `FRESH_LEAD`
2. `FOLLOW_UP`
3. `INTERESTED`
4. `PENDING_REGISTRATION_DATA`
5. `GST_REGISTRATION_DONE`
6. `SCHEDULED_PAYMENTS`
7. `SUBSCRIBED` (closed won — typically via **payment PAID** trigger, not call status)
8. `NOT_INTERESTED` (closed lost)

Rules:
- `SUBSCRIBED` and `NOT_INTERESTED` are final closed stages.
- First-pitch **call-update** is only for stages mapped to **`FIRST_PITCH_CALL`** in **`crm_ui_mappings`** (today: `FRESH_LEAD`, `FOLLOW_UP`, `INTERESTED`). Leads reach **`PENDING_REGISTRATION_DATA`** via first-pitch status **`SEND_DOCS`** (and GST/sync), not via a first-pitch mapping on that stage.

---

## 3) Pitch types (dynamic config)

Required call type codes:
- `FIRST_PITCH_CALL`
- `FINAL_PITCH_CALL`

These remain configurable rows but logic references these code values.

---

## 4) Call statuses (dynamic config)

Recommended status codes (see `crm_call_statuses`; seed/migrate adds **`SEND_DOCS`** for first pitch):
- `CALL_NOT_ANSWERED`
- `CALL_NOT_CONNECTED`
- `CALL_BUSY`
- `CALL_BACK`
- `CONNECTED_AND_SCHEDULED`
- `SCHEDULED_PAYMENT`
- `SEND_DOCS` (first pitch → move lead to **`PENDING_REGISTRATION_DATA`**)
- `NOT_INTERESTED`
- `SUBSCRIBED_COMPLETED` (may exist in DB for legacy; **final pitch call-update** in current app does not use it — closed won uses **payment** automation)

For `FIRST_PITCH_CALL`, allowed call statuses are driven by **`crm_ui_mappings`** (see **70**); they include **`SEND_DOCS`** and the standard outreach outcomes.

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

### Final pitch connected statuses (current `app/crm`)
- `SCHEDULED_PAYMENT`
- `CALL_BACK`

(Both increment **`call_connected_count`** and refresh **`last_connected_at`** when used on **`FINAL_PITCH_CALL`**.)

---

## 6) Stage movement rules (source of truth)

## 6.1 First pitch flow

**Allowed current stages for `FIRST_PITCH_CALL` call-update** (must match `crm_ui_mappings` `STAGE_TO_PITCH`):
- `FRESH_LEAD`
- `FOLLOW_UP`
- `INTERESTED`

**Not** allowed for first-pitch call-update (no mapping / server rejects):
- `PENDING_REGISTRATION_DATA` — RM works registration elsewhere; stage advances on GST approval / sync.
- `GST_REGISTRATION_DONE`, `SCHEDULED_PAYMENTS`, `SUBSCRIBED`, `NOT_INTERESTED`

Status to stage mapping (server `_transition_stage`):
- `SEND_DOCS` -> `PENDING_REGISTRATION_DATA`
- `CALL_NOT_ANSWERED` / `CALL_NOT_CONNECTED` -> no stage change
- `CALL_BUSY` / `CALL_BACK` -> `FOLLOW_UP`
- `CONNECTED_AND_SCHEDULED` -> `INTERESTED`
- `NOT_INTERESTED` -> `NOT_INTERESTED` (close)
- `SCHEDULED_PAYMENT` / final-only statuses -> rejected for first pitch (mapping + validation)

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
- `SCHEDULED_PAYMENTS`

Allowed call statuses (from **`crm_ui_mappings`** for `FINAL_PITCH_CALL`): typically outreach outcomes plus **`SCHEDULED_PAYMENT`**. **`NOT_INTERESTED`** is rejected on final pitch in code.

Status to stage mapping (current server):
- `SCHEDULED_PAYMENT` -> `SCHEDULED_PAYMENTS` (with **`followup_at`** required, future)
- `CALL_NOT_ANSWERED` / `CALL_NOT_CONNECTED` / `CALL_BUSY` / `CALL_BACK` -> no stage change
- **`SUBSCRIBED`**: not set via **`SUBSCRIBED_COMPLETED`** in call-update; use **`fn_sync_payment_paid_to_crm`** when **`payment_status = PAID`** for the GST registration entity (from **`GST_REGISTRATION_DONE`** or **`SCHEDULED_PAYMENTS`**).

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

Returns history for **one** lead, ordered by time (newest first in implementation). **Row-level visibility** applies — **404** if the lead is not visible to the caller.

### 8.2b Cross-lead activity search (visible leads only)

`GET /api/v1/crm/leads/activities/filter`

Same **RM/OP/manager/ADMIN** visibility as **`GET /api/v1/crm/leads/filter`**, with optional filters (`lead_id`, `activity_type`, `call_type_code`, `call_status_code`, `old_stage`, `new_stage`, `performed_by`, `performed_at_from` / `performed_at_to`, `mobile`, `lead_stage`, `lead_is_active`) and pagination. See **[`docs/70-crm-ui-integration-guide.md`](70-crm-ui-integration-guide.md) §6.1b**.

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

- **Call-update / followup-status:** `EMPLOYEE` + **`WRITE`**.
- **Lead list, stages, ui-mappings, single lead, activities (per-lead and `/activities/filter`):** `EMPLOYEE` + **`READ`**.
- **Admin direct edit:** `EMPLOYEE` + **`DELETE`** on route; handler allows **ADMIN** only.
- **Visibility:** enforced in [`app/crm/crm_leads.py`](../app/crm/crm_leads.py) (`_build_crm_visibility`, `_fetch_crm_lead_visible`); unknown roles see **no** leads.
- **Actor:** `performed_by` from JWT **`emp_id`** / **`sub`** when positive; otherwise **NULL** for ADMIN-style tokens without a numeric employee.

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
2. First pitch + `SEND_DOCS` moves to `PENDING_REGISTRATION_DATA` (no first-pitch call-update while already in that stage).
3. Final pitch + `NOT_INTERESTED` rejected.
4. `GST_REGISTRATION_DONE -> SCHEDULED_PAYMENTS` via final pitch `SCHEDULED_PAYMENT`; `SUBSCRIBED` via **payment PAID** trigger (not `SUBSCRIBED_COMPLETED` on call-update).
5. Closed stage blocks further call transitions.
6. Approval event auto-moves stage to `GST_REGISTRATION_DONE`.
7. Every call update writes one activity row with correct actor and timestamp.
8. `GET /activities/filter` returns only activities for **visible** leads; `GET /filter` and activities filter stay consistent for RM/OP/manager.

---

## 14) Backend module layout (as implemented)

- Router + handlers: [`app/crm/crm_leads.py`](../app/crm/crm_leads.py)
- Pydantic models: [`app/crm/schemas.py`](../app/crm/schemas.py)
- Permissions: [`app/security/rbac.py`](../app/security/rbac.py)
- DB schema constant: [`app/utils.py`](../app/utils.py) (`DB_SCHEMA`)
- App wiring: [`app/main.py`](../app/main.py) — `crm_leads_router`

