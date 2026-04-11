# CRM UI integration guide (`app/crm`)

End-to-end reference for building a client (web/mobile) against the CRM leads API: **authentication**, **permissions**, **row visibility**, **config endpoints**, **list/filter endpoints**, **mutations**, **validation rules**, and **how backend automation interacts with the UI**.

**Last updated:** 2026-04-11 (sync with [`app/crm/crm_leads.py`](../app/crm/crm_leads.py)).  
**Source code:** [`app/crm/crm_leads.py`](../app/crm/crm_leads.py), [`app/crm/schemas.py`](../app/crm/schemas.py).  
**Router prefix:** `/api/v1/crm/leads` (included from [`app/main.py`](../app/main.py)).  
**Companion spec (conceptual):** [`docs/60-gst-registration-crm-automation-spec.md`](60-gst-registration-crm-automation-spec.md) — if anything disagrees with this guide, **prefer this document and the code**.

---

## 1. Pin: what you are building

The CRM module lets **RM / OP / managers** work **only on leads they are allowed to see**, while **ADMIN** can override (direct edit). The UI should:

1. Load **reference data** once (or on refresh): **pipeline stages** (`/stages`), **UI mappings** (`/ui-mappings` — stage → pitch type → allowed call statuses).
2. List leads (`/filter`), optionally list **activities across visible leads** (`/activities/filter`), open a lead, show **per-lead timeline** (`/{lead_id}/activities`).
3. Record **calls** (`call-update`) with the correct **pitch type** and **status** for the lead’s **current stage**.
4. Manage **follow-up state** (`followup-status`) and optional **follow-up time**.
5. Rely on **GST registration** and **payment** triggers for some stage moves (UI does not always own the stage).

---

## 2. Database prerequisites (run in order)

Apply these on the **`solvetax`** schema (or your `DB_SCHEMA` equivalent) before expecting full behaviour:

| Order | File | Purpose |
|------:|------|--------|
| Earlier | CRM core tables (see [`docs/60-gst-registration-crm-automation-spec.md`](60-gst-registration-crm-automation-spec.md)) | `crm_leads`, `crm_activities`, `crm_call_types`, `crm_call_statuses`, etc. |
| As needed | [`docs/62-crm-leads-last-connected-at.sql`](62-crm-leads-last-connected-at.sql) | `last_connected_at` on leads |
| As needed | [`docs/63-crm-leads-followup-status-migration.sql`](63-crm-leads-followup-status-migration.sql) | Follow-up columns + check + trigger timestamps |
| 1 | [`docs/64-crm-ui-mappings.sql`](64-crm-ui-mappings.sql) | `crm_ui_mappings` + `SEND_DOCS` status |
| 2 | [`docs/65-crm-lead-stages.sql`](65-crm-lead-stages.sql) | `crm_lead_stages` catalogue (`id` PK, `code` unique) |
| 2b | [`docs/67-crm-lead-stages-add-id.sql`](67-crm-lead-stages-add-id.sql) | **Only if** you already created `crm_lead_stages` with `code` as PK (adds `id`) |
| 3 | [`docs/66-crm-followup-drop-cancelled.sql`](66-crm-followup-drop-cancelled.sql) | Remove `CANCELLED` from `follow_up_status` check |

**Server config:** the app uses `DB_SCHEMA` from [`app/utils.py`](../app/utils.py) (typically `solvetax`). All CRM SQL in the app is parameterized with that schema.

---

## 3. Authentication and permissions (system)

Every endpoint uses FastAPI **`Depends(require_permission(...))`**. The client must send a **valid JWT** (or whatever your auth stack uses) that satisfies:

| Permission pattern | Used on |
|--------------------|--------|
| `("EMPLOYEE", "READ")` | `GET /filter`, `GET /activities/filter`, `GET /ui-mappings`, `GET /stages`, `GET /{lead_id}`, `GET /{lead_id}/activities` |
| `("EMPLOYEE", "WRITE")` | `POST /{lead_id}/followup-status`, `POST /{lead_id}/call-update` |
| `("EMPLOYEE", "CRM")` | *(none in current `crm_leads` — reads were aligned to `READ`)* |
| `("EMPLOYEE", "DELETE")` | `POST /{lead_id}/edit` (ADMIN-only in handler) |

**RBAC implementation:** [`app/security/rbac.py`](../app/security/rbac.py) — ensure your token’s **permissions** and **role** match what ops expect.

---

## 4. Row-level visibility (critical for UI)

Logic lives in **`_build_crm_visibility`** and **`_fetch_crm_lead_visible`** in [`crm_leads.py`](../app/crm/crm_leads.py).

| Role | Sees leads where |
|------|------------------|
| **ADMIN** | All (no extra `WHERE` clause). |
| **RM** | `crm_leads.rm_id = token emp_id` |
| **OP** | `crm_leads.op_id = token emp_id` |
| **SALES_MANAGER** / **OP_MANAGER** | `rm_id` or `op_id` is in a **team** managed by `manager_emp_id = token emp_id` (`team_members` + `team_managers`). |
| **Any other role** | **No rows** (SQL `FALSE` — empty list / 404 on single-lead). |

**Employee context:** for **RM / OP / managers**, the token must resolve to a **positive numeric `emp_id`** (`emp_id` or `sub` in JWT). Otherwise the API returns **403** with *“Valid employee context is required for CRM lead access.”*

**Privacy:** for a lead the user cannot see, **GET by id**, **`GET /{lead_id}/activities`**, **call-update**, and **followup-status** return **404** (not 403), to avoid leaking lead existence.

**`GET /activities/filter`:** does **not** return 404 for “no permission” globally — it returns **`items: []`** with **`total: 0`** when there are no matching activities on **visible** leads. Individual lead endpoints still use **404** when probing a specific `lead_id` you cannot see.

**ADMIN** `call-update` / **followup-status**: may act on any lead; **`performed_by`** in `crm_activities` is set to **`NULL`** if the token has no positive `emp_id` (avoids FK `0`).

---

## 5. Reference APIs (load first for UI)

### 5.1 `GET /api/v1/crm/leads/stages`

- **Permission:** `EMPLOYEE` + `READ`
- **Source table:** `crm_lead_stages` ([`docs/65-crm-lead-stages.sql`](65-crm-lead-stages.sql))
- **Response model:** `CRMLeadStagesOut`

```json
{
  "stages": [
    { "id": 1, "code": "FRESH_LEAD", "name": "Fresh lead", "sort_order": 10 }
  ]
}
```

**UI use:** stage filters, badges, pipeline ordering. Use **`id`** for stable list keys; **`code`** is what appears on **`crm_leads.stage`** and in **`GET /filter?stage=`**.

**If the table is missing:** **500** — run migration `65`.

---

### 5.2 `GET /api/v1/crm/leads/ui-mappings`

- **Permission:** `EMPLOYEE` + `READ`
- **Source table:** `crm_ui_mappings` ([`docs/64-crm-ui-mappings.sql`](64-crm-ui-mappings.sql))
- **Response model:** `CRMUIMappingsOut`

```json
{
  "stage_to_pitch": [
    { "stage": "FRESH_LEAD", "pitch_type_code": "FIRST_PITCH_CALL", "sort_order": 10 }
  ],
  "pitch_to_statuses": {
    "FIRST_PITCH_CALL": [
      { "call_status_code": "CALL_NOT_ANSWERED", "sort_order": 10 }
    ],
    "FINAL_PITCH_CALL": [
      { "call_status_code": "SCHEDULED_PAYMENT", "sort_order": 50 }
    ]
  }
}
```

**UI algorithm for the call screen:**

1. Read lead’s **`stage`** (from detail or list).
2. Find the row in **`stage_to_pitch`** where `stage` matches → **`pitch_type_code`**.
3. Show **call status** dropdown from **`pitch_to_statuses[pitch_type_code]`**, sorted by **`sort_order`**.
4. Submit **`POST .../call-update`** with that **`call_type_code`** (= pitch) and chosen **`call_status_code`**.

**If `stage` has no mapping** (e.g. `PENDING_REGISTRATION_DATA`): the server rejects **call-update** — do not show the call form for that stage, or show read-only state.

**If the table is missing:** **500** — run migration `64`.

---

## 6. Lead list and detail

### 6.1 `GET /api/v1/crm/leads/filter`

- **Permission:** `EMPLOYEE` + `READ`
- **Query params:**  
  `stage`, `follow_up_status`, `mobile` (10 digits), `rm_id`, `op_id`, `is_active`, `limit` (1–200), `offset`
- **Response:** `{ "items": [ /* lead rows */ ], "total": number, "limit": number, "offset": number }`

**Stage validation:** if `stage` is passed, it must be an **active** code in **`crm_lead_stages`** (when the table has rows); otherwise the app falls back to the in-code union of funnel stages.

**Follow-up filter:** allowed values: **`PENDING`**, **`COMPLETED`**, **`MISSED`** only (`CANCELLED` removed).

---

### 6.1b `GET /api/v1/crm/leads/activities/filter`

- **Permission:** `EMPLOYEE` + `READ`
- **Purpose:** Same visibility model as **`GET /filter`** (join `crm_activities` → `crm_leads`, apply **`_build_crm_visibility`** on the lead).
- **Response:** `{ "items": [ /* activity rows: columns from crm_activities a.* */ ], "total", "limit", "offset" }` — same shape as lead **`/filter`** for easy table reuse in the UI.
- **Query (all optional):**

| Param | Meaning |
|--------|--------|
| `lead_id` | `a.lead_id` |
| `activity_type` | `a.activity_type` (normalized, max 40 chars) |
| `call_type_code` | `a.call_type_code` |
| `call_status_code` | `a.call_status_code` |
| `old_stage` / `new_stage` | `a.old_stage` / `a.new_stage` (validated like lead stage when `crm_lead_stages` is populated) |
| `performed_by` | `a.performed_by` (employee id) |
| `performed_at_from` / `performed_at_to` | `a.performed_at` range (inclusive) |
| `mobile` | `l.mobile` (10 digits) |
| `lead_stage` | current `l.stage` on the lead |
| `lead_is_active` | `l.is_active` |
| `limit` / `offset` | Pagination (default limit 50, max 200) |

Sort: **`performed_at DESC`**, **`id DESC`**.

**Example (global activity feed for visible leads, calls only, last 7 days):**

`GET /api/v1/crm/leads/activities/filter?activity_type=CALL&performed_at_from=2026-04-04T00:00:00%2B05:30&limit=100&offset=0`

**Stage filters:** `old_stage`, `new_stage`, and `lead_stage` are validated against **`crm_lead_stages`** when that table has active rows; otherwise the app falls back to the same in-code stage union used for **`GET /filter`**.

---

### 6.2 `GET /api/v1/crm/leads/{lead_id}`

- **Permission:** `EMPLOYEE` + `READ`
- **Response:** lead row as JSON (column names match DB).

Use for **detail drawer / page**. Combine with **ui-mappings** to decide **call UI**.

---

### 6.3 `GET /api/v1/crm/leads/{lead_id}/activities`

- **Permission:** `EMPLOYEE` + `READ`
- **Query:** `limit`, `offset`
- **Response:** `{ "items": [ /* activity rows */ ], "limit", "offset" }`

**Visibility:** same as lead detail — **404** if lead not visible.

Activity rows may include **`activity_type`** (`CALL`, `FOLLOWUP_STATUS_UPDATE`, `SYSTEM`, …), **`call_type_code`**, **`call_status_code`**, **`old_stage`**, **`new_stage`**, **`performed_by`**, etc.

---

## 7. Mutations

### 7.1 `POST /api/v1/crm/leads/{lead_id}/call-update`

- **Permission:** `EMPLOYEE` + `WRITE`
- **Body:** `CRMCallUpdateIn`

```json
{
  "call_type_code": "FIRST_PITCH_CALL",
  "call_status_code": "CALL_BACK",
  "followup_at": "2026-04-15T10:00:00+05:30",
  "remarks": "optional"
}
```

**Rules:**

- **`call_type_code` / `call_status_code`:** must exist and be **active** in `crm_call_types` / `crm_call_statuses`.
- **Mappings:** if `crm_ui_mappings` has data, **stage ↔ pitch** and **pitch ↔ status** must match; otherwise in-code fallbacks apply.
- **`followup_at`:** must be **strictly in the future** (Asia/Kolkata aware in server).
- **Required `followup_at` when status is `CALL_BACK` or `SCHEDULED_PAYMENT`** (first and final pitch respectively for those statuses).
- **Inactive** or **closed** leads (`SUBSCRIBED`, `NOT_INTERESTED`): rejected.

**Stage transitions (server `_transition_stage`):** examples:

| Pitch | Status | New stage (if any) |
|-------|--------|--------------------|
| FIRST | `SEND_DOCS` | `PENDING_REGISTRATION_DATA` |
| FIRST | `CALL_BUSY` / `CALL_BACK` | `FOLLOW_UP` |
| FIRST | `CONNECTED_AND_SCHEDULED` | `INTERESTED` |
| FIRST | `NOT_INTERESTED` | `NOT_INTERESTED` |
| FIRST | `CALL_NOT_ANSWERED` / `CALL_NOT_CONNECTED` | unchanged |
| FINAL | `SCHEDULED_PAYMENT` | `SCHEDULED_PAYMENTS` |
| FINAL | other allowed non-terminal statuses | unchanged |

**Counters:** **`call_attempted_count`** always increments. **`call_connected_count`** and **`last_connected_at`** increment when status is in:

- **First pitch:** `CONNECTED_AND_SCHEDULED`, `CALL_BACK`
- **Final pitch:** `SCHEDULED_PAYMENT`, `CALL_BACK`

**RM/OP:** token role **`RM`** sets **`rm_id`**; **`OP`** sets **`op_id`** on the lead on each call-update.

**Success response:** includes updated counters, **`new_stage`**, **`follow_up_status`**, **`activity_id`**, etc.

---

### 7.2 `POST /api/v1/crm/leads/{lead_id}/followup-status`

- **Permission:** `EMPLOYEE` + `WRITE`
- **Body:** `CRMFollowupStatusUpdateIn`

```json
{
  "follow_up_status": "PENDING",
  "followup_at": "2026-04-12T15:00:00+05:30",
  "remarks": "optional"
}
```

**Allowed `follow_up_status`:** **`PENDING`**, **`COMPLETED`**, **`MISSED`** only.

**Rules:**  
- Setting **`PENDING`** requires **`followup_at`** if the lead has no existing **`followup_at`**.  
- **`followup_at`** when sent must be in the **future**.  
- DB trigger ([`docs/63-...`](63-crm-leads-followup-status-migration.sql)) maintains **`completed_at`** / **`missed_at`** on the row.

---

### 7.3 `POST /api/v1/crm/leads/{lead_id}/edit`

- **Permission:** `EMPLOYEE` + `DELETE` (naming is historical; check RBAC)
- **Who:** **`ADMIN` only** — others get **403**.
- **Body:** `CRMLeadEditIn` — at least one of: `stage`, `followup_at`, `rm_id`, `op_id`, `remarks`.

Closed leads: **stage cannot be changed** if already **`SUBSCRIBED`** or **`NOT_INTERESTED`**.

Use for **manual corrections**; normal funnel should use **call-update** + **system triggers**.

---

## 8. System automation (UI must not fight it)

These run in **PostgreSQL**, not in `app/crm`:

### 8.1 GST registration → CRM lead (`fn_sync_crm_lead_from_gst_registration`)

- On **`gst_registration`** changes: upserts/links **`crm_leads`**, and when **`registration_status = 'APPROVED'`** sets stage toward **`GST_REGISTRATION_DONE`** (unless lead is in a preserved closed stage).
- **Recommendation:** preserve **`SCHEDULED_PAYMENTS`** in the trigger `CASE` so later registration row edits do not **pull the lead backward** from scheduled payment — confirm with your DBA.

### 8.2 Payment PAID → `SUBSCRIBED` (`fn_sync_payment_paid_to_crm`)

- When **`payments.payment_status`** becomes **`PAID`** for **`entity_type = 'GST_REGISTRATION'`**, the linked active lead moves to **`SUBSCRIBED`** only if current stage is **`GST_REGISTRATION_DONE`** or **`SCHEDULED_PAYMENTS`**.

**UI implication:** do not assume **stage** only changes from **call-update**; **refresh** lead after GST/payment events (polling, websocket, or revisit detail).

---

## 9. Error contract (for forms)

**Validation (400)** — many endpoints:

```json
{
  "detail": {
    "error": {
      "type": "validation_error",
      "message": "Human-readable summary",
      "fields": { "field_name": "Specific hint" }
    }
  }
}
```

**403:** missing/invalid employee context for RM/OP/manager, or non-ADMIN on **edit**.

**404:** lead not found **or** not visible.

**500:** DB / missing config tables (`ui-mappings`, `stages`).

---

## 10. Ping: recommended UI bootstrap sequence

1. **Authenticate** → store token; ensure JWT includes **`emp_id`** (or numeric **`sub`**) for RM/OP/managers (**403** otherwise on CRM reads).
2. **Parallel (cache with TTL, e.g. 5–15 minutes):**  
   - `GET /api/v1/crm/leads/stages` — pipeline labels + stable **`id`** for list keys.  
   - `GET /api/v1/crm/leads/ui-mappings` — call form: stage → pitch → statuses.
3. **Lead inbox:** `GET /api/v1/crm/leads/filter?...` — use **`stage`** / **`follow_up_status`** / **`mobile`** / **`rm_id`** / **`op_id`** / **`is_active`** as needed.
4. **Optional dashboard / audit stream:** `GET /api/v1/crm/leads/activities/filter?...` — same visibility as step 3; use for cross-lead timelines (filter by `activity_type`, date range, `lead_id`, etc.).
5. **Open lead:** `GET /api/v1/crm/leads/{id}` + `GET /api/v1/crm/leads/{id}/activities?limit=&offset=`.
6. **Call UI:** derive **pitch** from **ui-mappings** + **lead.stage**; require **future `followup_at`** when status is **`CALL_BACK`** or **`SCHEDULED_PAYMENT`**.
7. **Follow-up panel:** only **PENDING / COMPLETED / MISSED** (no **CANCELLED** — DB check after [`docs/66-crm-followup-drop-cancelled.sql`](66-crm-followup-drop-cancelled.sql)).
8. After mutations, **re-fetch** lead (and optionally refresh **activities** list); **stage** may change from **GST/payment triggers**, not only from **call-update**.

---

## 11. FastAPI route order (why static paths matter)

Routes are registered in [`crm_leads.py`](../app/crm/crm_leads.py) so that **fixed segments** are declared **before** `/{lead_id:int}`:

- `GET /ui-mappings`
- `GET /filter`
- `GET /activities/filter`
- `GET /stages`
- then `GET /{lead_id}`, `GET /{lead_id}/activities`, posts, etc.

That way paths like `.../leads/stages` or `.../leads/activities/filter` are **not** interpreted as a numeric `lead_id`. If you add new static paths under this router, keep the same pattern.

---

## 12. Quick route table

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/crm/leads/ui-mappings` | READ |
| GET | `/api/v1/crm/leads/filter` | READ |
| GET | `/api/v1/crm/leads/activities/filter` | READ |
| GET | `/api/v1/crm/leads/stages` | READ |
| GET | `/api/v1/crm/leads/{lead_id}` | READ |
| GET | `/api/v1/crm/leads/{lead_id}/activities` | READ |
| POST | `/api/v1/crm/leads/{lead_id}/edit` | DELETE (ADMIN) |
| POST | `/api/v1/crm/leads/{lead_id}/followup-status` | WRITE |
| POST | `/api/v1/crm/leads/{lead_id}/call-update` | WRITE |

---

## 13. Related documentation

- [`docs/60-gst-registration-crm-automation-spec.md`](60-gst-registration-crm-automation-spec.md) — original CRM data model and DDL snippets; updated with pointers to current behaviour where it diverged.
- SQL migrations: [`64-crm-ui-mappings.sql`](64-crm-ui-mappings.sql), [`65-crm-lead-stages.sql`](65-crm-lead-stages.sql), [`66-crm-followup-drop-cancelled.sql`](66-crm-followup-drop-cancelled.sql), [`67-crm-lead-stages-add-id.sql`](67-crm-lead-stages-add-id.sql) (upgrade only).

When the spec and this guide differ, **prefer this guide + current `crm_leads.py`** for API behaviour.
