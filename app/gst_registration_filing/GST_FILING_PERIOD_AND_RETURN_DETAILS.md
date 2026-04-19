# GST filings: `filing_period`, create, PATCH, return details, scheduler

This document is the **single overview** for how **`gst_filings.filing_period`**, **`gst_filing_return_details`**, **`POST /api/v1/gst-filings`** (create), **`PATCH /api/v1/gst-filings/{id}`**, and **`app/schedular/schedular.py`** work together.

---

## 1. Concepts

### 1.1 One parent row vs many child rows

| Store | Role |
|-------|------|
| **`gst_filings`** | One row per **filing instance**: customer + GST link + **`filing_period`** (e.g. `MAR-2026`, `Q1-2026`, `2024-25`) + category, frequency, turnover, **`service_id`** (derived from `filing_frequency`), etc. |
| **`gst_filing_return_details`** | One or more **child** rows per `gst_filing_id`: due dates, return-type statuses (GSTR-1/3B/9/9C/CMP-08/4), **`next_auto_generate_at`** for forward chaining, **`is_active`**. |

**Important:** Default “previous month” **create** does **not** create two **`gst_filings`** rows (monthly + yearly). It creates **one** `gst_filings` row whose `filing_period` is the **computed previous** period, and under it **two active detail rows** when the “full” template applies (periodic + annual companion for REGULAR RETURN, etc.).

### 1.2 Another historical period = new filing (create), not PATCH

To record work for a **different** period (e.g. another past month/quarter), add **another** row in **`gst_filings`** with that **`filing_period`** via **`POST /gst-filings`** (create). The duplicate check blocks the same customer + GST + **`filing_period`** twice.

**Do not** rely on PATCH to “move” a filing to a different period unless you intentionally change that filing’s business meaning; for **backfills**, **create** is the right API.

### 1.3 Shared seeding logic (`gst_return_details_rebuild.py`)

**`rebuild_return_details_for_filing`** is used by **both**:

- **`POST /gst-filings`** (create) — after inserting `gst_filings`, seeds children with the same rules as historically inlined logic.
- **`PATCH /gst-filings/{id}`** — when `recalc_required`, soft-deactivates prior active children, then seeds again from the **merged** parent row.

Helpers **`count_active_return_details`** and **`infer_explicit_template_from_prior_row_count`** are used on **PATCH** only (to infer “explicit-style” template from prior row count). **`validate_merged_filing_business_rules`** runs on PATCH when rule-related fields are sent.

---

## 2. Create (`POST /gst-filings`)

### 2.1 `filing_period` **omitted** or empty (`null` / not sent)

1. **`gst_filings.filing_period`** is set to **`generate_previous_period(filing_frequency)`**  
   (e.g. previous calendar month for **MONTHLY**, previous quarter for **QUARTERLY**, FY-style string for **YEARLY** where applicable).

2. **`explicit_filing_period`** = **`false`**.

3. **`service_id`** on the parent row is set from **`filing_frequency`**:  
   `MONTHLY → 4`, `QUARTERLY → 5`, `YEARLY → 6` (same mapping as PATCH).

4. **`rebuild_return_details_for_filing`** inserts **active** children with the **full** template:

   | Parent shape | Active `gst_filing_return_details` |
   |--------------|-------------------------------------|
   | **RETURN** + **REGULAR** + **MONTHLY** / **QUARTERLY** | (1) Periodic row (GSTR-1 + GSTR-3B).<br>(2) **Companion YEARLY** row (GSTR-9; GSTR-9C when **`turnover_details` = `MORE_THAN_5CR`**). |
   | **RETURN** + **COMPOSITION** | (1) CMP-08 style row.<br>(2) Companion **GSTR-4** YEARLY row. |
   | **ANNUAL** + **YEARLY** | Single annual row (GSTR-9/9C or GSTR-4 by taxpayer type). |

Create does **not** soft-deactivate anything: there is no prior filing yet.

### 2.2 `filing_period` **explicitly** sent (non-empty)

1. That string is stored on **`gst_filings.filing_period`** (must match **§ 2.3** format rules for the chosen `filing_frequency`).

2. **`explicit_filing_period`** = **`true`**.

3. Children are **only** what matches that explicit regime (e.g. REGULAR RETURN monthly/quarterly → **periodic row only**, **no** extra YEARLY companion on the same filing).

Use explicit period for **targeted** one-period filings (e.g. manual backfill) where you do **not** want the annual companion row on the same `gst_filing_id`.

### 2.3 `filing_period` string formats (create & PATCH)

Validation expects **ASCII hyphen `-`**, not underscore `_`.

| `filing_frequency` | Required pattern | Valid example | Invalid example |
|--------------------|------------------|-----------------|-----------------|
| **MONTHLY** | `MMM-YYYY` (3-letter month + year) | `MAR-2026` | `MAR_2026` |
| **QUARTERLY** | `Q[1-4]-YYYY` | `Q1-2026` | `Q1_2026` |
| **YEARLY** (annual) | `YYYY-YY` | `2024-25` | — |

State and other enums are typically stored **uppercase** after normalization (e.g. `ANDHRA_PRADESH`).

---

## 3. Edit (`PATCH /api/v1/gst-filings/{id}`)

### 3.1 `gst_filings.filing_period` — **unchanged unless you send a real value**

**`gst_registration_id`** is **not** accepted on PATCH (it stays whatever is already on the filing). **`gstin`** may still be sent if you allow correcting GSTIN on edit.

The PATCH body uses **`exclude_unset=True`**: only keys present in the JSON are written to **`gst_filings`**.

- If you **omit** **`filing_period`**, the DB column **stays** as before.
- If you send **`"filing_period": null`**, the API treats that as **omit** (the key is dropped so the DB value is **not** cleared and rebuild does not receive `None` as the period string).
- If you send a **non-empty** string, it replaces the column after validation (**§ 2.3**).

Merged rebuild uses:  
`filing_period = update_data.get("filing_period", old["filing_period"])`  
(after the null-omit step above).

So: **turnover**, **frequency**, **state**, etc. can change **without** touching **`filing_period`** — the filing stays on the **same** period anchor unless you intentionally patch it.

### 3.2 `filing_frequency` and `service_id` on PATCH

If the patch includes **`filing_frequency`**, the handler sets **`service_id`** on the parent row using the same map as create:  
**`MONTHLY → 4`, `QUARTERLY → 5`, `YEARLY → 6`**.

### 3.3 What happens when you PATCH turnover / frequency / state (typical case)

1. **`gst_filings`** is **UPDATE**d for fields you sent. **`filing_period`** unchanged if omitted (or null-as-omit).

2. If any **recalc** trigger is present in the patch  
   (`filing_category`, `filing_frequency`, `taxpayer_type`, `turnover_details`, `state`, `filing_period`), then **`rebuild_return_details_for_filing`** runs:

   - All **currently active** children for that `gst_filing_id` are **soft-deactivated**:  
     `is_active = FALSE`, `next_auto_generate_at = NULL`.
   - **New active** seed child row(s) are **INSERT**ed from the **merged** parent (`filing_period`, `filing_frequency`, `turnover_details`, `state`, …).

3. **Scheduler** then only sees **active** rows; forward chaining and **`_sync_gstr9c_with_parent_turnover`** use **current** **`gst_filings`** columns.

### 3.4 Explicit-template inference on PATCH (row count)

Before rebuild, the API counts **active** detail rows. If there was **exactly one** active row and the filing matches the “single-template” pattern, rebuild uses **`explicit_filing_period = true`** so a backfill-style filing does not suddenly grow a YEARLY companion. Otherwise it uses the **full** template like default create.

### 3.5 Merged validation

If the patch touches `filing_category`, `filing_frequency`, `taxpayer_type`, `turnover_details`, or `filing_period`, **`validate_merged_filing_business_rules`** runs on the **merged** parent (old + patch) before save (same cross-field ideas as **`GSTFilingIn`** for create).

### 3.6 API errors (400 vs 500)

Validation and rebuild raise **`HTTPException`** with **4xx** messages (e.g. bad **`filing_period`** format). Those are returned to the client as **400** (or other 4xx), **not** masked as a generic **500**.

A **500** with the generic “Something unexpected…” message indicates an **unhandled** server error (log stack trace). Fix the underlying bug or correct the request (e.g. **`MAR-2026`** not **`MAR_2026`**).

---

## 4. Scheduler (`app/schedular/schedular.py`)

- Only **`gst_filing_return_details` with `is_active = TRUE`** participate in auto-generation and overdue stamping (as in your SQL).
- **`gst_filings`** is joined for **`filing_frequency`**, **`turnover_details`**, etc.

Jobs relevant here:

1. **`_sync_gstr9c_with_parent_turnover`** — YEARLY rows: add/clear **GSTR-9C** from parent **`turnover_details`** on active rows.
2. **`_run_gst_filing_auto_generation`** — when **`next_auto_generate_at`** is due on an **active** row, inserts the **next** chained detail row; turnover can add **9C** on the shifted row when parent is **`MORE_THAN_5CR`**.

Inactive (superseded) detail rows are **never** picked — they keep history only.

---

## 5. Quick reference tables

### 5.1 Create

| `filing_period` in request | Stored `gst_filings.filing_period` | Companion YEARLY (REGULAR RETURN) |
|----------------------------|-----------------------------------|-------------------------------------|
| Omitted / empty | **Auto = previous** month/quarter/year | **Yes** (full template) |
| Provided (valid format) | **As sent** | **No** (explicit single-regime template) |

### 5.2 PATCH (same filing `id`)

| `filing_period` in JSON | Effect on DB `filing_period` |
|-------------------------|------------------------------|
| Omitted | **Unchanged** |
| `null` | **Unchanged** (treated as omit) |
| Non-empty string | **Replaced** (must match **§ 2.3**) |

| Recalc runs? | Active children |
|--------------|-----------------|
| Yes | Prior actives → **`is_active = FALSE`**, `next_auto_generate_at` cleared; **new** active seeds inserted from merged parent. |
| No | No rebuild of children. |

### 5.3 New period vs same period

| Goal | API |
|------|-----|
| Same filing, new turnover/frequency/state, **same** period anchor | **PATCH** (omit `filing_period` or send `null` to mean omit) |
| **Different** period as its own filing | **POST create** (new `gst_filings` row) |

---

## 6. Code map

| Concern | Location |
|--------|----------|
| Create: default vs explicit `filing_period`, `service_id` map | `gst_registration_filing.py` → `create_gst_filing` (`_FILING_FREQUENCY_TO_SERVICE_ID`) |
| Soft supersede + seed children | `gst_return_details_rebuild.py` → `rebuild_return_details_for_filing`, `count_active_return_details`, `infer_explicit_template_from_prior_row_count`, `validate_merged_filing_business_rules` |
| PATCH: merge, null `filing_period`, `service_id`, validation, recalc | `gst_registration_filing.py` → `update_gst_filing` |
| Scheduler: turnover 9C + auto chain | `app/schedular/schedular.py` |

---

## 7. Short answers to common questions

**Q: If I PATCH only `turnover_details`, does `filing_period` change?**  
**A:** No — omit `filing_period` or send `null` (omit). Only a non-empty string replaces it.

**Q: Where does “previous month / quarter” come from if I omit period on create?**  
**A:** From **`generate_previous_period`** in **`create_gst_filing`**, stored on **`gst_filings.filing_period`**, then children are seeded from that string.

**Q: Should I use create for “another previous period”?**  
**A:** Yes — **new `gst_filings` row** with that **`filing_period`** via **create**; PATCH is for **the same** filing record.

**Q: Are old return-detail rows deleted on PATCH recalc?**  
**A:** No — they are **soft-deactivated** (`is_active = FALSE`, `next_auto_generate_at` cleared); new active rows are inserted.

**Q: Why did I get 400 on filing period?**  
**A:** Use **`MAR-2026`** not **`MAR_2026`**, and match the table in **§ 2.3** for your frequency.
