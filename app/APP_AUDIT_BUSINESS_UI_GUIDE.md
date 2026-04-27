# Solvetax App Audit Guide (Business + UI)

## Scope

This document summarizes the current backend state in `app/` for:

- GST Registration
- GST Filing
- Income Tax
- CRM (GST + ITR + common)
- Payments (GST Registration, GST Filing, Income Tax)

It highlights:

- What is implemented
- How UI should integrate
- Verified gaps/missing pieces
- Priority fixes and test checklist

---

## 1) Current Module Map

### Core Routers (from `app/main.py`)

- Auth and account: signup/login/forgot-password/email-verification
- Team and employee
- Customer registration
- GST registration family:
  - `gst_registration`
  - `gst_people`
  - `gst_documents`
  - `gst_blob`
  - `gst_registration_config`
  - `document_config`
  - `city_config`
- GST filing family:
  - `gst_registration_filing`
  - `gst_filing_document`
  - `gst_filing_config`
  - `gst_filing_rule_engine`
  - manual followups
- Services and service config
- Entity types
- CRM family:
  - `crm_leads` (GST lead-level APIs)
  - `crm_leads_common` (shared APIs requiring `entity_type`)
  - `crm_leads_itr` (ITR lead-level APIs)
- Payments family:
  - `registration_payments`
  - `filing_payments`
  - `income_tax_payments`
  - `payments_config`
- Income tax family:
  - `income_tax`
  - `income_tax_documents`

---

## 2) Business-Level Flow (How System Works)

## 2.1 GST Registration Flow

1. Create GST registration.
2. System syncs/creates CRM lead for GST (`entity_type=GST_REGISTRATION`) by mobile-based linkage.
3. Add people + documents.
4. Update/activate/deactivate GST registration updates service + CRM linkage.
5. UI can fetch full combined data via full detail endpoint.

### Important behavior

- CRM linkage now prefers:
  - exact GST lead by `entity_type + entity_id`, else
  - fallback by `entity_type + mobile`
  - else create new lead.

---

## 2.2 Income Tax Flow

1. Create income tax record.
2. System upserts CRM lead (`entity_type=INCOME_TAX`) by `mobile + entity_type`:
  - if found -> update `entity_id`
  - else -> insert new lead.
3. Manage ITR docs through income tax documents APIs.
4. Activate/deactivate income tax records via dedicated endpoints.

### Important behavior

- Current lead upsert is done on create path.

---

## 2.3 CRM Flow (Common + GST + ITR)

- Shared APIs are in `crm_leads_common.py`.
- Lead-level GST APIs are in `crm_leads.py`.
- Lead-level ITR APIs are in `crm_leads_itr.py`.
- Common APIs require explicit `entity_type`.
- Call update and followup-status endpoints drive stage transitions and activity rows.
- Visibility is role-aware (ADMIN, RM, OP, manager roles via team mapping).

---

## 2.4 Payments Flow

- GST Registration payments: `/api/v1/payments`
- GST Filing payments: `/api/v1/filing-payments`
- Income Tax payments: `/api/v1/income-tax-payments`
- Dynamic payment listing: `/api/v1/payments/dynamic_filter`
- Config/amount utility:
  - `/api/v1/payments_config/payment-config`
  - `/api/v1/payments_config/amount/{entity_id}?entity_type=...`

### Payment math model (all create flows)

- `original_amount`: first non-cancelled payment amount
- cumulative `discount` + cumulative `paid_amount`
- status:
  - `PAID` if payment closes remaining exactly
  - otherwise `PENDING`

---

## 3) UI Integration Guide

## 3.1 CRM UI Expectations

- For common endpoints, pass `entity_type` always.
- For ITR-specific read/write-by-lead APIs, use `/api/v1/crm/itr/leads/...`.
- For shared activity listing:
  - `/api/v1/crm/leads/{lead_id}/activities/calls?entity_type=...`
  - `/api/v1/crm/leads/{lead_id}/activities/stage-history?entity_type=...`
  - `/api/v1/crm/leads/{lead_id}/activities?entity_type=...`

### Required UI caution

- Old callers using ITR-prefixed activity GET paths must migrate to common endpoints.

---

## 3.2 Payments UI Expectations

- Use correct create endpoint by entity family:
  - GST registration, GST filing, or income tax.
- For payable details before create, call:
  - `/api/v1/payments_config/amount/{entity_id}?entity_type=...`
- Handle these common errors:
  - `409 Payment already completed`
  - `400 discount/paid exceeds remaining`
  - `404 entity/payment not found`

---

## 3.3 GST/ITR Lead Linking UI Expectations

- Bulk-import can create CRM lead first without final `entity_id`.
- Later, when GST/ITR master row is created, backend should attach `entity_id` to same lead (via mobile + entity type lookup).

---

## 4) Verified Gaps / Missing Items

These are verified in current code and should be treated as actionable.

## 4.1 Critical

1. Missing `timezone` import in GST registration filter date normalization.
   - File: `app/gst_registration/gst_registration.py`
   - Impact: runtime error when code path uses `timezone.utc`.

2. Undefined variable `now` in GST document edit endpoint.
   - File: `app/gst_registration/gst_documents.py`
   - In `edit_registration_document`, `update_data["verified_at"] = now` is used without defining `now`.
   - Impact: runtime failure when setting `verified=true`.

## 4.2 High

3. Registration payment activate/soft-delete endpoints do not enforce `entity_type=GST_REGISTRATION`.
   - File: `app/payments/registration_payments.py`
   - Impact: endpoint can mutate non-registration payment rows if id is known.

4. Income tax CRM sync parity is weaker than GST (create-only upsert path).
   - File: `app/Income_tax/income_tax.py`
   - Impact: assignment/active-state drift possible after edit/activate/deactivate if not covered elsewhere (for example by DB trigger logic).

## 4.3 Medium

5. Some CRM query paths normalize `entity_type`, others compare directly.
   - File: `app/crm/crm_leads.py`
   - Impact: inconsistent behavior if dirty casing/spacing exists in data.

6. Potential stale per-lead CRM cache after bulk actions.
   - File: `app/crm/crm_leads.py`
   - Impact: after bulk-import/bulk-assign, by-id/activity caches may remain stale until TTL.

7. `dynamic_filter` accepts any `entity_type` string (returns empty set for unknown values).
   - File: `app/payments/registration_payments.py`
   - Impact: harder UI debugging for typo inputs.

## 4.4 Low

8. Minor docs/description drift can still appear as features evolve.
9. Repeated logic across payment modules increases long-term divergence risk.

---

## 5) Prioritized Fix Order

1. Fix runtime blockers:
   - add missing `timezone` import
   - define `now` in GST documents edit flow.
2. Add `entity_type` guard in registration payment activate/soft-delete.
3. Align income-tax CRM sync lifecycle parity (or confirm DB trigger fully covers it).
4. Normalize `entity_type` handling consistently in CRM filters/queries.
5. Improve cache invalidation for bulk CRM operations (invalidate affected lead tags).

---

## 6) QA Checklist (Business + UI)

## 6.1 CRM

- Common routes reject missing `entity_type`.
- GST and ITR call-update stage transitions match expected mappings.
- Role visibility:
  - RM sees own
  - OP sees own
  - managers see team
  - ADMIN sees all.
- Bulk import + post-create master linkage updates `entity_id` on same lead.

## 6.2 GST / Income Tax

- Create/edit/deactivate/activate all work with expected response shape.
- Duplicate checks return UI-friendly field errors.
- Cache invalidation refreshes list and detail responses after mutation.

## 6.3 Payments

- Create partial/full payments and verify amount math.
- Verify `PAID` safeguards on soft-delete/activate.
- Verify dynamic_filter + pagination + entity_type filters.
- Verify income tax payable/config endpoints.

---

## 7) Notes For Business Team

- Multi-entity CRM architecture is now in place (GST + ITR).
- Entity-type-aware common APIs reduce future duplication.
- Payment stack now includes income tax flow.
- Remaining work is mainly hardening/consistency, not foundational redesign.

---

## 8) Notes For UI Team

- Treat `entity_type` as first-class state in CRM screens.
- Switch ITR activity list calls to common routes with `entity_type=INCOME_TAX`.
- For payments, always pre-check payable amount from config endpoint.
- Display backend validation errors directly (discount/paid/duplicate guards are strict).

