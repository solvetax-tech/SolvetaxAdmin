# File-Level Doc: `app/version/version.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Provides filtered access to audit/version history records across entities.

## Router

- Prefix: `/api/v1/version`
- Tag: `Version History`

## Endpoint in this file

- `GET /api/v1/version/dynamic_filter`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Accepts filters by:
  - version id
  - employee id
  - entity type/id
  - customer id
  - action type
  - date range
- Applies pagination (`limit`, `offset`).
- Joins employee/customer metadata for readable response payloads.

## Main tables touched

- `versions`
- `employees`
- `customers`
