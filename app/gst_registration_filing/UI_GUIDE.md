# GST Registration Filing — UI & Integration Guide

This document describes **only** the `app/gst_registration_filing` package: what the backend does, which APIs to call, and what product screens should support. It is aimed at **frontend / UX** and **API consumers**.

**Package layout**

| File | Role |
|------|------|
| `schemas.py` | Pydantic request/response validation (strict: unknown fields rejected, strings trimmed). |
| `gst_registation_filing.py` | GST filing CRUD, list filter, activate/deactivate, **return status** updates. |
| `gst_filing_document.py` | Documents linked to a filing (URL-only; no file upload in this API). |
| `gst_filing_config.py` | Read-only listing of GST filing configuration rows from DB. |

**Auth**

- All endpoints use `require_permission("EMPLOYEE", "READ")` or `"WRITE"` as noted per route.
- JWT should expose `emp_id` or `sub`, and `role` (used for **row visibility** on list endpoints — see below).

---

## 1. Domain model (what exists in DB)

### 1.1 `gst_filings` (main filing header)

- One row per **customer + period + GST identity** (for active filings), with workflow fields: `status`, `filing_category`, `filing_frequency`, `taxpayer_type`, `turnover_details`, `state`, RM/OP, portal `username` / `password`, `email_id`, `rent`, `rule14a`, `is_active`, `is_auto_enabled`, etc.
- **Passwords must never be shown in list/detail responses** — API masks `password` to `null` where it returns filing rows.

### 1.2 `gst_filing_return_details` (return lines + due dates)

- **Multiple rows per `gst_filing_id`** (the backend uses a fixed pattern):
  - **REGULAR**: typically **two** rows — one for **periodic** returns (GSTR-1 / GSTR-3B with due dates), one for **annual** (GSTR-9; GSTR-9C when turnover &gt; 5CR).
  - **COMPOSITION**: **two** rows — CMP-08 (quarterly-style due) and GSTR-4 (annual).
- Each row has statuses (`FILED` / `NOT_FILED`), due dates per return, `is_active`, `is_auto_generated`, `next_auto_generate_at`, etc.
- **Triggers** on this table can update parent filing status (DB-side).

### 1.3 `gst_filings_documents`

- Stores **external links** only (`document_url`): Excel / CSV / Google Sheets URL — **no binary upload** in this module.
- Tied to `gst_filing_id`; supports `verified`, `verified_by`, soft `is_active`, audit via `versions`.

### 1.4 `customer_services`

- On **filing create**, a `customer_services` row is upserted (`ON CONFLICT DO NOTHING`) for the filing’s `service_id`.
- **Deactivate filing** sets linked `customer_services.status = 'INACTIVE'` where `entity_type = 'GST_FILING'` and `entity_id = filing_id`.
- **Activate filing** sets `status = 'ACTIVE'` for matching rows.

---

## 2. API surface (full paths)

Prefixes are as registered on each router.

### 2.1 GST filings — `prefix: /api/v1/gst-filings`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/api/v1/gst-filings/gst-filings/filter` | READ | Search/list filings (joins return details; supports rich filters). |
| POST | `/api/v1/gst-filings/gst-filings` | WRITE | Create filing (+ seed return-detail rows + customer_service). |
| PATCH | `/api/v1/gst-filings/gst-filings/{filing_id}` | WRITE | Partial update; may **rebuild** `gst_filing_return_details` when “recalc” fields change. |
| DELETE | `/api/v1/gst-filings/gst-filings/{filing_id}/deactivate` | WRITE | Soft-deactivate filing, documents, return details; sync customer_services. |
| POST | `/api/v1/gst-filings/gst-filings/{filing_id}/activate` | WRITE | Reverse deactivate (filing, documents, return details, customer_services). |
| PATCH | `/api/v1/gst-filings/gst-filings/{filing_id}/returns/status` | WRITE | Update return **FILED/NOT_FILED** and optional `is_active` on **one return-detail row**. |

**Critical UI note — `returns/status` path parameter**

- Here `{filing_id}` is **`gst_filing_return_details.id`** (primary key of a return-detail **row**), **not** `gst_filings.id`.
- The UI should take this id from the return-detail row returned with the filing (e.g. from filter response joined data), not from the parent filing id.

### 2.2 GST filing documents — `prefix: /api/v1/gst-filings-docs`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| POST | `/api/v1/gst-filings-docs` | WRITE | Create document (URL link). |
| PATCH | `/api/v1/gst-filings-docs/{document_id}` | WRITE | Partial update document. |
| GET | `/api/v1/gst-filings-docs/gst-filing-documents/filter` | READ | List documents with filters + total count. |
| DELETE | `/api/v1/gst-filings-docs/gst-filing-documents/{document_id}/deactivate` | WRITE | Soft-deactivate document. |
| POST | `/api/v1/gst-filings-docs/gst-filing-documents/{document_id}/activate` | WRITE | Reactivate document. |

### 2.3 GST filing config — `prefix: /api/v1/gst-filing-config`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/api/v1/gst-filing-config/gst-filing-config` | READ | Filter config rows (reference data for UI or admin). |

---

## 3. Create filing (`POST …/gst-filings`)

### 3.1 Payload (`GSTFilingIn`)

- **Required**: `customer_id`, `filing_category`, and **exactly one** of `gst_registration_id` **or** `gstin` (validated in schema).
- **Mode**: API **only allows `MANUAL`** for first-time create (`mode` must be `MANUAL`). Sending `AUTO` fails validation / business check.
- **GSTIN**: 15-char format enforced by regex (normalized to uppercase).
- **filing_category / filing_frequency**:
  - `ANNUAL` ⇒ must be `YEARLY`.
  - `RETURN` ⇒ cannot be `YEARLY`.
- **taxpayer_type**:
  - `COMPOSITION` cannot use `MORE_THAN_5CR`; cannot be `MONTHLY` on **edit** schema; create path follows service rules in code.
  - `REGULAR` with `MORE_THAN_5CR` cannot use `QUARTERLY`.
- **YEARLY** requires `turnover_details`.
- **filing_period** (optional):
  - If omitted → server sets **previous** period from “now” (IST) based on `filing_frequency` (month / quarter / FY string).
  - If provided → must match frequency-specific format (see §5).

### 3.2 Server-side behavior (summary)

1. Resolves `gstin` from registration when `gst_registration_id` is sent; may copy portal credentials from registration if not provided.
2. **Duplicate check** (active only): same `customer_id`, same `gst_registration_id` / `gstin` (NULL-safe), same `filing_period` → **does not insert again**.
3. **Duplicate response**: HTTP **200** with body `{ "message": "<user-facing text>", "request_id": "…" }` — **not** 409. UI should treat as “already exists” info state.
4. Inserts `gst_filings` with `status = DATA_PENDING`, `is_auto_enabled = true`, `service_id` map: **MONTHLY → 4, QUARTERLY → 5, YEARLY → 6**.
5. Inserts **return detail row(s)** and due dates using **state lists** (e.g. Group-2 states change GSTR-3B due day for quarterly REGULAR).
6. Inserts `customer_services` row (`PENDING`) for the customer/service/filing entity.
7. Writes `versions` audit (`CREATE`).

**Response (success)**

- `201` with `data` (filing row, `password` nulled), `message`, `request_id`.

**RM/OP auto-assignment**

- If JWT `role` is `RM` and `rm_id` omitted → set to current `emp_id`.
- If role is `OP` and `op_id` omitted → set to current `emp_id`.

---

## 4. Update filing (`PATCH …/gst-filings/{filing_id}`)

- `{filing_id}` is **`gst_filings.id`**.
- **Partial update**: only sent fields change.
- After merge, **either** `gst_registration_id` **or** `gstin` must remain valid (not both missing).
- If any of these change: `filing_category`, `filing_frequency`, `taxpayer_type`, `turnover_details`, `state`, `filing_period` → backend **deletes** all `gst_filing_return_details` for that filing and **re-inserts** rows from scratch (status reset to model defaults for new rows).
- **taxpayer_type** for that rebuild must be **REGULAR** or **COMPOSITION**; otherwise 400.
- Duplicate unique constraint → 409.

UI should warn before saving changes that trigger **recalculation** (loss of prior per-return row state unless persisted elsewhere).

---

## 5. Filing period formats (UI must enforce)

Aligned with `GSTFilingIn` validation:

| `filing_frequency` | Format | Examples |
|--------------------|--------|----------|
| MONTHLY | `MMM-YYYY` (3-letter English month, uppercase) | `JAN-2025`, `APR-2026` |
| QUARTERLY | `Q[1-4]-YYYY` | `Q1-2024`, `Q3-2025` |
| YEARLY | `YYYY-YY` (financial year style) | `2024-25`, `2025-26` |

Regex reference:

- Monthly: `^[A-Z]{3}-\d{4}$`
- Quarterly: `^Q[1-4]-\d{4}$`
- Yearly: `^\d{4}-\d{2}$`

**Parsing note (quarters):** The backend maps `Qn-YYYY` to **calendar** quarter start months for due-date math (Q1→Jan, Q2→Apr, …). Your in-app labels should match what ops expect; if you need strict Indian FY quarter labels, confirm with product — the **string pattern** is still `Q[1-4]-YYYY`.

---

## 6. List / filter filings (`GET …/gst-filings/filter`)

- Returns joined data from `gst_filings` **LEFT JOIN** `gst_filing_return_details` (so **multiple rows** per filing if multiple detail rows exist — UI often needs **grouping by filing id**).
- Query params include: ids, customer, registration, GSTIN, service, category, period, frequency, taxpayer, turnover, state, status(es), RM/OP, username/email, rent range, rule14a, **due date range**, created/data_received ranges, active/inactive, overdue/upcoming flags, auto flags, pagination.
- **`include_inactive`**: default behavior excludes inactive filings unless overridden.
- **Visibility**: `build_gst_filing_visibility(role, emp_id, …)` restricts rows for non-admin roles (same pattern as documents filter).

**Response**

- `{ "data": [...], "count": <rows in page>, "limit", "offset", "request_id" }`  
  Note: `count` here is **page size**, not total universe — check code if you need total count (current API returns `len(data)` for count).

---

## 7. Deactivate / activate filing

**Deactivate** (`DELETE …/deactivate`)

- Fails if filing missing, already inactive, or **`status == FILED`**.
- Customer must exist and be **active**.
- Sets filing inactive; deactivates documents and return details; sets customer_services inactive; audit `DELETE`.

**Activate** (`POST …/activate`)

- Fails if missing, already active, customer missing/inactive.
- Optimistic locking style: if update returns no row → **409** “refresh and retry”.
- Reactivates documents + return details; sets customer_services active where applicable; audit `ACTIVATE`.

---

## 8. Return statuses (`PATCH …/returns/status`)

**Body (`GSTReturnStatusUpdateIn`)**

- Optional fields: `gstr1_status`, `gstr3b_status`, `gstr9_status`, `gstr9c_status`, `cmp08_status`, `gstr4_status` — each `FILED` | `NOT_FILED`.
- Optional `is_active` on that **return-detail row**.
- **At least one** of the above must be present (schema).

**Rules**

- Server loads **all** detail rows with the given **return-detail id** (today that is a single PK row; structure allows extension).
- For each status field in the request, at least one loaded row must have that column **non-null** (“applicable”). Otherwise **400** with a message listing invalid fields.
- Updates only columns that are non-null on DB for that row; uses `varchar` cast for Postgres.

**Response**

- Full list of rows for that id after update, `updated_fields`, active/total counts, `message`, `request_id`.

---

## 9. Documents module

### 9.1 Create (`POST /api/v1/gst-filings-docs`)

- Requires active `gst_filing`.
- `document_url`: **http/https**, and must look like **Excel/CSV/Sheets** (`.xlsx`, `.xls`, `.csv`, or `docs.google.com/spreadsheets` in URL) — see `GSTFilingDocumentIn`.
- Duplicate active doc type per filing may return **409** (unique constraint).

### 9.2 Filter (`GET …/gst-filing-documents/filter`)

- Joins filing + employees for RM/OP/verifier names.
- Respects visibility rules.
- Returns `count` = **total** matching rows (separate from paginated `data`).

### 9.3 Patch / deactivate / activate

- Standard soft-delete and audit patterns; verified documents may log a warning on deactivate.

---

## 10. User-facing errors (filings router)

Filings endpoints return **`detail`** as a **string** (FastAPI default) using centralized copy in **`GstFilingApiMessages`** inside `gst_registation_filing.py`. Use these strings for toasts; optionally map substrings or future `error_code` if you add them later.

Document endpoints use **their own** string messages (not the same class).

**422** responses come from **Pydantic** validation (`detail` is often a list of `{loc, msg, type}`) — show field errors next to inputs.

---

## 11. What the UI should build (checklist)

1. **Filing list** — filter screen using query params from §6; **group** joined rows by `gst_filings.id`; show overdue/upcoming from return columns.
2. **Filing create** — wizard with category/frequency/taxpayer/turnover/state, GST link, optional period (§5), RM/OP; handle **200 duplicate** as success-with-info.
3. **Filing detail / edit** — PATCH partial fields; **confirm** when recalc fields change.
4. **Return workspace** — for each **`gst_filing_return_details` row**, show due dates and FILED/NOT_FILED toggles; call **returns/status** with **`gst_filing_return_details.id`**.
5. **Deactivate / activate filing** — with guards (e.g. cannot deactivate if `status === FILED`).
6. **Documents** — paste link only (no upload); verify toggle; list/filter; activate/deactivate.
7. **Security** — never display `password`; use masked/null from API.
8. **Config** (optional screen) — read-only table from filing-config GET for reference.

---

## 12. Related code (for deeper reading)

- Due-date offsets: `_LEAD_DAYS_MONTHLY`, `_LEAD_DAYS_QUARTERLY`, `_LEAD_DAYS_YEARLY_ANNUAL` and `_compute_next_auto_generate_at` in `gst_registation_filing.py`.
- Recalc trigger fields: `update_gst_filing` `recalc_required` block.
- DB triggers: not in this package — see SQL migrations / `fn_update_parent_filing_status` etc.

---

*Generated from the `app/gst_registration_filing` codebase. When behavior and this guide disagree, trust the code and update this file.*
