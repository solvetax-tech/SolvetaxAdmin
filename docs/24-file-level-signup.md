# File-Level Doc: `app/sign_up/signup.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles employee onboarding after verification: account creation, role mapping, optional team/manager mapping, and audit capture.

## Router

- Prefix: `/app/v1`
- Tag: `Signup`

## Endpoint in this file

- `POST /app/v1/signup`

## Permission usage

- Requires `USER_ACCESS:WRITE`.

## Core behaviors

- Validates verified email/OTP prerequisites before onboarding.
- Inserts employee row with normalized identity/profile fields.
- Assigns role using `roles` + `employee_roles` mapping.
- Optional team membership setup:
  - `team_members`
  - `team_managers` when requested.
- Enforces uniqueness and consistency checks.
- Writes onboarding audit in `versions`.

## Main tables touched

- `employees`
- `roles`
- `employee_roles`
- `employee_email_verifications`
- `teams`
- `team_members`
- `team_managers`
- `versions`
