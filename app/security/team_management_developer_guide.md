# Team Management Developer Guide

This guide documents the current production contract between:

- `app/sign_up/employee_edit.py`
- `app/security/teams_api.py`

It explains what each API owns, what validations are enforced, and how to handle manager/team changes safely.

---

## 1) Ownership Split (Single Responsibility)

### `employee_edit` owns

- employee profile fields (`username`, `email`, `phone_number`, etc.)
- role changes
- `manager_emp_id` validation and update

### `teams_api` owns

- team membership assignment/movement
- team manager assignment/replacement
- team-member/manager cascade updates

This split avoids hidden side effects and keeps data consistency rules explicit.

---

## 2) Current Behavioral Rules

## `employee_edit` (`/api/v1/employees/{emp_id}/emp_dyn/edit`)

- `team_id` is rejected with `400`.
  - Message: use teams API for team assignment/movement.
- If `manager_emp_id` is supplied:
  - manager must exist
  - manager must be active
  - manager role must be one of `ADMIN`, `SALES_MANAGER`, `OP_MANAGER`
- If role demotion is requested for an active team manager:
  - request is rejected with `400`
  - manager must be reassigned through teams API first
- Writes to `versions` table for employee update audit.

## `teams_api` (`/app/v1/teams/*`)

### `POST /assign-member`

- Assigns/moves an employee between teams (`team_members` only).
- Rejects movement if employee is currently an active team manager.
- Writes an audit row to `versions` with:
  - `entity_type = TEAM_MEMBER_ASSIGNMENT`
  - old/new team IDs in `json` / `updated_json`.

### `POST /set-manager`

- Replaces active manager for a team (`team_managers`).
- Validates:
  - team exists and active
  - manager exists and active
  - manager role in `ADMIN`, `SALES_MANAGER`, `OP_MANAGER`
  - manager is active member of that same team
- Cascade behavior:
  - previous active manager mapping deactivated
  - previous manager role changed to `NORMAL` (except `ADMIN`)
  - all active team members get `employees.manager_emp_id = new_manager_emp_id`
  - new manager gets `manager_emp_id = NULL` (no self-reporting)
- Writes an audit row to `versions` with:
  - `entity_type = TEAM_MANAGER`
  - previous/new manager IDs in `json` / `updated_json`.

---

## 3) Recommended UI Flow

1. Create team in `teams_api`.
2. Add/move members using `POST /assign-member`.
3. Set or change manager using `POST /set-manager`.
4. Use `employee_edit` only for profile/role/manager field updates (not team movement).

For manager-role UI:

- If role is manager-capable (`SALES_MANAGER` / `OP_MANAGER`), show team manager assignment action.
- Do not send `team_id` in employee edit payload.

---

## 4) Data Consistency Guarantees

The current design protects against:

- accidental team movement via employee edit
- silent manager reassignment side effects
- moving active managers as normal members
- demoting active manager without reassignment
- role downgrade of `ADMIN` during manager replacement
- missing audit trail for team membership/manager changes

---

## 5) API Examples

## Assign/Move Member

`POST /app/v1/teams/assign-member`

```json
{
  "team_id": 12,
  "emp_id": 45
}
```

## Set/Replace Team Manager

`POST /app/v1/teams/set-manager`

```json
{
  "team_id": 12,
  "manager_emp_id": 45
}
```

## Employee Edit (team_id not allowed)

`POST /api/v1/employees/45/emp_dyn/edit`

```json
{
  "email": "new.mail@example.com",
  "role": "SALES_MANAGER"
}
```

---

## 6) Migration Note

If any old frontend flow still sends `team_id` to employee edit, update it to:

- call `employee_edit` for profile/role fields
- call `teams_api /assign-member` for team movement
- call `teams_api /set-manager` for manager assignment/replacement

This is required for compatibility with current backend validations.
