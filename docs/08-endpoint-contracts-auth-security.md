# Endpoint Contracts: Auth and Security

Owner: Engineering Team  
Last Verified On: 2026-04-07

This file provides contract-style API documentation for auth/security modules.

## Auth (`/app/v1`)

### `POST /app/v1/email-verification/request`
- **Body**: email + employee identity fields (see `app/sign_up/schemas.py`).
- **Success**: OTP dispatched for signup verification.
- **Errors**:
  - duplicate/already-registered email
  - cooldown/rate-limit violations
  - invalid payload format

### `POST /app/v1/email-verification/verify`
- **Body**: email + OTP.
- **Success**: verification record marked verified/used.
- **Errors**:
  - invalid/expired OTP
  - OTP reuse
  - email mismatch

### `POST /app/v1/signup`
- **Auth**: `USER_ACCESS:WRITE`.
- **Body**: employee create payload (role/team assignment fields included).
- **Success**: employee created + role mapping; optional team mappings.
- **Side effects**: `employees`, `employee_roles`, `team_members`, `team_managers`, `versions`.
- **Errors**:
  - duplicate email/mobile
  - invalid role/team reference
  - missing prerequisite verification

### `POST /app/v1/login`
- **Body**: email + password.
- **Success**:
  - returns access token payload
  - sets `refresh_token` httpOnly cookie (`path=/app/v1`)
- **Side effects**: inserts `session_token`.
- **Errors**:
  - invalid credentials
  - inactive employee

### `POST /app/v1/refresh`
- **Body**: none (uses cookie).
- **Success**:
  - rotates access + refresh tokens
  - resets refresh cookie
- **Side effects**: updates `session_token`.
- **Errors**:
  - missing/invalid refresh cookie
  - expired/deactivated session

### `POST /app/v1/logout`
- **Auth**: `EMPLOYEE:READ`.
- **Body**: none.
- **Success**: session deactivated, cookie deleted.
- **Side effects**: updates `session_token`, inserts `session_audit_log`.

### `POST /app/v1/forgot-password/request`
- **Body**: email.
- **Success**: reset OTP issued.
- **Side effects**: insert/update `password_reset_otps`.

### `POST /app/v1/forgot-password/verify`
- **Body**: email + OTP + new password.
- **Success**: password updated.
- **Side effects**: updates `employees.password_hash`, marks OTP used.

## Teams (`/app/v1/teams`)

### `POST /create`
- **Auth**: `USER_ACCESS:WRITE`
- **Body**: team create payload.
- **Success**: team row created.

### `GET /teams`
- **Auth**: `USER_ACCESS:READ`
- **Query**: optional paging/filter fields.
- **Success**: list of teams + manager/member metadata.

### `POST /edit/{team_id}`
- **Auth**: `USER_ACCESS:WRITE`
- **Body**: editable team fields.
- **Success**: team updated.

### `POST /add-member`
- **Auth**: `USER_ACCESS:WRITE`
- **Body**: `team_id`, `emp_id`.
- **Success**: member active under target team (old memberships deactivated).

### `POST /remove-member`
- **Auth**: `USER_ACCESS:WRITE`
- **Body**: `team_id`, `emp_id`.
- **Success**: membership deactivated.

### `GET /{team_id}/members`
- **Auth**: `USER_ACCESS:READ`
- **Success**: list of team members with role flags.

## Employees (`/api/v1/employees`)

### Main operations
- `POST /{emp_id}/emp_dyn/edit` (`USER_ACCESS:WRITE`) - partial employee update.
- `GET /filter` (`EMPLOYEE:READ`) - employee listing with filters.
- `GET /employee/{emp_id}` (`EMPLOYEE:READ`) - single employee details.
- `DELETE /{emp_id}/soft_delete` (`USER_ACCESS:WRITE`) - soft delete employee.
- `POST /{emp_id}/change-password` (`USER_ACCESS:WRITE`) - password update.
- `GET /roles` (`EMPLOYEE:READ`) - roles list.

### Common contract behavior
- **Validation**: uniqueness checks, state checks, role/team consistency.
- **Audit**: write operations log into `versions`.
- **Error shape**: FastAPI `HTTPException` with detail messages.
