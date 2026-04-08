# Bootstrap, Auth, and Security

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Bootstrap (`app/main.py`)

- Creates FastAPI app and health endpoint (`GET /health`).
- Adds `TokenValidatorMiddleware` globally.
- Includes all domain routers.
- Uses startup event to launch scheduler if enabled by env.

## Authentication Flow

### Public endpoints (`/app/v1`)

- `POST /email-verification/request`
- `POST /email-verification/verify`
- `POST /signup`
- `POST /login`
- `POST /refresh`
- `POST /forgot-password/request`
- `POST /forgot-password/verify`

### Protected endpoint (`/app/v1`)

- `POST /logout` (requires `EMPLOYEE:READ`)

## Session + JWT (`app/sign_up/login.py`, `app/token_validator.py`)

- Login:
  - verifies employee credentials.
  - creates JWT access token and refresh token.
  - stores access token in `session_token.session_token`.
  - stores hashed refresh token in `session_token.refresh_token`.
  - sets refresh cookie with path `/app/v1`.
- Refresh:
  - reads refresh cookie.
  - validates active session + expiry + employee active state.
  - rotates access + refresh token in the same session row.
- Logout:
  - deactivates session token row and clears cookie.
  - writes session audit event.
- Middleware:
  - bypasses selected public paths.
  - for protected paths validates `Authorization: Bearer ...`.
  - checks session token in DB and token expiry.
  - deactivates expired/invalid sessions.

## Authorization (`app/security/rbac.py`, `app/utils.py`)

- `require_permission(feature, permission)` checks `permissions.platform` inside JWT.
- Permission payload is built from:
  - `employee_roles`
  - `role_features`
  - `features`
- Read endpoints accept either `READ` or `WRITE` for same feature.

## Team and Employee Management

### Teams API (`app/security/teams_api.py`, prefix `/app/v1/teams`)

- `POST /create` - create team (`USER_ACCESS:WRITE`)
- `GET /teams` - list teams (`USER_ACCESS:READ`)
- `POST /edit/{team_id}` - edit team (`USER_ACCESS:WRITE`)
- `POST /add-member` - add/move member (`USER_ACCESS:WRITE`)
- `POST /remove-member` - remove member (`USER_ACCESS:WRITE`)
- `GET /{team_id}/members` - team members (`USER_ACCESS:READ`)

### Employee API (`app/sign_up/employee_edit.py`, prefix `/api/v1/employees`)

- Dynamic employee edit, filters, role listing, active RM/OP/manager lists.
- Soft delete and create/change-password flows.
- Uses audit writes into `versions`.

## Auth/IAM Tables Used

- `employees`
- `roles`
- `employee_roles`
- `features`
- `role_features`
- `employee_email_verifications`
- `password_reset_otps`
- `session_token`
- `session_audit_log`
- `teams`
- `team_members`
- `team_managers`
- `versions`

## Notable Implementation Detail

- Cookie path consistency is centralized (`/app/v1`) for set/delete operations, preventing mismatch issues during logout and refresh.
