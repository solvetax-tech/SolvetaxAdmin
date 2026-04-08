# File-Level Doc: `app/token_validator.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Global middleware for access-token validation and DB-backed session enforcement.

## Component

- `TokenValidatorMiddleware` (mounted in `app/main.py`).

## Responsibility

- Bypass configured public routes and `OPTIONS` requests.
- Validate bearer JWT signature/expiry.
- Verify matching active session row exists in DB.
- Deactivate expired sessions.
- Enforce employee active-state checks.
- Add request-level auth context for downstream permission dependencies.

## Main behaviors

- Rejects malformed/missing bearer tokens for protected routes.
- Rejects tokens without active matching `session_token` row.
- Writes session audit entries for certain invalidation paths.
- Returns consistent auth failure responses via HTTP exceptions.

## Main tables touched

- `session_token`
- `session_audit_log`
- `employees`
