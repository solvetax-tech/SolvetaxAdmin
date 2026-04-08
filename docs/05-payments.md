# Payments Modules

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Registration Payments (`app/payments/registration_payments.py`, prefix `/api/v1/payments`)

- `POST /api/v1/payments` - create registration payment transaction.
- `GET /api/v1/payments/dynamic_filter` - ledger/filter endpoint.
- `DELETE /api/v1/payments/{payment_id}/soft_delete` - soft deactivate payment.
- `POST /api/v1/payments/{payment_id}/activate` - reactivate payment.

## Filing Payments (`app/payments/filing_payments.py`, prefix `/api/v1/filing-payments`)

- `POST /api/v1/filing-payments` - create filing payment transaction.
- `DELETE /api/v1/filing-payments/{payment_id}/soft_delete` - soft deactivate filing payment.
- `POST /api/v1/filing-payments/{payment_id}/activate` - reactivate filing payment.

## Payment Config (`app/payments/payments_config.py`, prefix `/api/v1/payments_config`)

- `GET /api/v1/payments_config/payment-config` - config rows by entity type.
- `GET /api/v1/payments_config/amount/{entity_id}` - calculate payable amount context.

## Validation and Financial Rules

- Schema validation in `app/payments/schemas.py`:
  - strict decimal constraints for amount fields.
  - unknown fields forbidden.
- API-level validations:
  - target entity must exist and be active (`gst_registration` or `gst_filings`).
  - prevents duplicate fully-paid active records for same entity/customer.
  - enforces `discount <= remaining` and `paid_amount <= remaining_after_discount`.

## Payment Status Behavior

- New entry becomes:
  - `PAID` when paid amount closes net amount.
  - otherwise `PENDING`.
- `CANCELLED` status is treated specially in aggregate calculations (excluded paths).
- Soft-delete blocked for active `PAID` entries.

## Audit/Versioning

- Payment create/delete/activate writes to `versions` with entity-specific types:
  - `GST_REGISTRATION_PAYMENT`
  - `GST_FILING_PAYMENT`

## Tables Used

- `payments`
- `payment_config`
- `gst_registration`
- `gst_filings`
- `customers`
- `employees`
- `versions`
