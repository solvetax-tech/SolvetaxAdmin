# File-Level Doc: `app/sign_up/employee_edit.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Employee administration API for profile edits, listing/filtering, role lookups, activation state management, and password changes.

## Router

- Prefix: `/api/v1/employees`
- Tag: `Employees`

## Endpoints in this file

- `POST /{emp_id}/emp_dyn/edit`
- `GET /filter`
- `GET /employee/{emp_id}`
- `GET /active-rm`
- `GET /active-op`
- `GET /active-managers`
- `DELETE /{emp_id}/soft_delete`
- `GET /roles`
- `POST /create`
- `POST /{emp_id}/change-password`

## Permission usage

- Read endpoints mostly require `EMPLOYEE:READ`.
- Mutating endpoints require `USER_ACCESS:WRITE`.

## Core logic patterns

- Uses dynamic patch building for employee updates.
- Performs uniqueness checks (email/mobile, depending on operation).
- Validates team/manager consistency where applicable.
- Uses `versions` audit insertions for write operations.
- Applies role-aware filtering in list endpoints.

## Main tables touched

- `employees`
- `roles`
- `employee_roles`
- `team_members`
- `team_managers`
- `versions`

## Operational notes

- `soft_delete` is logical deactivation rather than hard deletion.
- Password-change flow updates credential hash and can emit audit metadata.
- This file is large and mixes multiple concerns (profile, team, role, auth-adjacent updates), so it is a high-value candidate for future split-by-submodule refactor.
