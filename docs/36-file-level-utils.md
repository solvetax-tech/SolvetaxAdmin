# File-Level Doc: `app/utils.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Shared utility layer for DB/schema constants, response helpers, permission derivation helpers, visibility SQL fragments, and common helper functions used across modules.

## Core utility groups

- **DB utilities**
  - connection pool acquisition (`get_db_pool`)
  - schema constant (`DB_SCHEMA`)
- **Auth/permissions helpers**
  - role-feature permission aggregation for JWT payloads
- **Visibility builders**
  - role-aware SQL conditions for customer, GST, filing, and service datasets
- **Response/helpers**
  - reusable formatting and validation helpers used by routers

## Architectural role

- Central dependency module imported by most API files.
- Determines consistent visibility and permission behavior across domains.
- Heavily impacts query correctness and access control outcomes.

## Main tables referenced by helper functions

- `employee_roles`
- `role_features`
- `features`
- and domain tables indirectly through visibility helper fragments.
