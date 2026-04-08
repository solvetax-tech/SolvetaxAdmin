# File-Level Doc: `app/customer_registration/service_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Read-only service master lookup API for customer-service workflows.

## Router

- Prefix: `/api/v1/services-config`
- Tag: `Services_config`

## Endpoint in this file

- `GET /api/v1/services-config/services`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Returns active service configuration rows.
- Supports optional filtering by service category and search context.
- Used by UI dropdowns and service assignment flows.

## Main tables touched

- `service_config`
