# File-Level Doc: `app/sign_up/login.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Implements login, refresh-token rotation, and logout flows with DB-backed session enforcement.

## Router

- Prefix: `/app/v1`
- Tag: `Login`

## Endpoints in this file

- `POST /app/v1/login`
- `POST /app/v1/refresh`
- `POST /app/v1/logout`

## Permission usage

- Login/refresh are public auth endpoints.
- Logout requires `EMPLOYEE:READ`.

## Core behaviors

- Login:
  - verifies credentials against active employee.
  - builds permissions payload from role-feature mappings.
  - issues JWT access token and refresh token.
  - inserts active session row in `session_token`.
  - sets refresh cookie (`HttpOnly`, secure flags, fixed path).
- Refresh:
  - validates refresh cookie/session.
  - rotates access token + refresh token and updates DB session row.
- Logout:
  - deactivates active session tied to refresh token hash.
  - writes session audit row.
  - deletes refresh cookie with matching path settings.

## Main tables touched

- `employees`
- `session_token`
- `session_audit_log`
- `employee_roles`
- `role_features`
- `features`
