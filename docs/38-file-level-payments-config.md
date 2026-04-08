# File-Level Doc: `app/payments/payments_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Provides payment configuration and amount-helper endpoints for payment initiation screens.

## Router

- Prefix: `/api/v1/payments_config`
- Tag: `Payments Config`

## Endpoints in this file

- `GET /api/v1/payments_config/payment-config`
- `GET /api/v1/payments_config/amount/{entity_id}`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Reads config rows by `entity_type`.
- Computes amount context for target entity by combining config and existing payment records.
- Read-only support module for payment create flows.

## Main tables touched

- `payment_config`
- `payments`
- `gst_registration` and/or `gst_filings` (entity lookups)
