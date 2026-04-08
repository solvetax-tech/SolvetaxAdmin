# File-Level Doc: `app/payments/filing_payments.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Implements payment operations specifically for GST filing entities, including creation, soft deactivation, and reactivation with financial consistency checks.

## Router

- Prefix: `/api/v1/filing-payments`
- Tag: `Filing Payments`

## Endpoints in this file

- `POST /api/v1/filing-payments`
- `DELETE /api/v1/filing-payments/{payment_id}/soft_delete`
- `POST /api/v1/filing-payments/{payment_id}/activate`

## Permission usage

- All endpoints require `EMPLOYEE:WRITE`.

## Create flow highlights

- Validates parent filing exists and is active.
- Prevents duplicate fully-paid active payment records for same filing/customer scope.
- Validates amount/discount/paid boundaries.
- Derives status (`PAID` vs `PENDING`) from financial values.
- Inserts payment row and writes `versions` audit event.

## Soft delete / activate highlights

- Soft delete marks `is_active = FALSE` with guards (for example, paid-state constraints).
- Activate restores `is_active = TRUE` with conflict checks.
- Both actions are audited into `versions`.

## Main tables touched

- `payments`
- `gst_filings`
- `versions`

## Operational notes

- Entity polymorphism is handled via `payments.entity_type`, with this file operating on filing-oriented entity values.
- Aggregation/reporting endpoints for payments are in other modules (`registration_payments.py`, dashboard).
