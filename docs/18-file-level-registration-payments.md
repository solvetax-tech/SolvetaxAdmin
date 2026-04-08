# File-Level Doc: `app/payments/registration_payments.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles payment operations for GST registration entities: create, dynamic filter, soft deactivate, and activate.

## Router

- Prefix: `/api/v1/payments`
- Tag: `Registration Payments`

## Endpoints in this file

- `POST /api/v1/payments`
- `GET /api/v1/payments/dynamic_filter`
- `DELETE /api/v1/payments/{payment_id}/soft_delete`
- `POST /api/v1/payments/{payment_id}/activate`

## Permission usage

- Create/delete/activate: `EMPLOYEE:WRITE`
- Dynamic filter: `EMPLOYEE:READ`

## Core behaviors

- Create:
  - validates active GST registration target.
  - calculates payment boundaries (remaining, discount, paid amount).
  - blocks duplicate fully-paid active records.
  - inserts payment row and versions audit.
- Dynamic filter:
  - supports customer/entity/status/mode/date/amount filters.
  - joins RM/OP/customer display metadata.
- Soft delete:
  - logical deactivate with paid-state safeguards.
  - writes versions audit.
- Activate:
  - restores inactive row after conflict checks.
  - writes versions audit.

## Main tables touched

- `payments`
- `gst_registration`
- `customers`
- `employees`
- `versions`

## Operational notes

- Uses same central `payments` table as filing payments, differentiated by `entity_type`.
- Dashboard payment metrics consume the same underlying payment records.
