# File-Level Doc: `app/security/teams_api.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Team management endpoints for creating teams, editing, member assignment/removal, and team membership views.

## Router

- Prefix: `/app/v1/teams`
- Tag: `Teams`

## Endpoints in this file

- `POST /app/v1/teams/create`
- `GET /app/v1/teams/teams`
- `POST /app/v1/teams/edit/{team_id}`
- `POST /app/v1/teams/add-member`
- `POST /app/v1/teams/remove-member`
- `GET /app/v1/teams/{team_id}/members`

## Permission usage

- Read: `USER_ACCESS:READ`
- Mutations: `USER_ACCESS:WRITE`

## Core behaviors

- Team creation/update with naming/status validations.
- Add-member flow supports move semantics by deactivating old team memberships before activating target team membership.
- Remove-member uses soft membership deactivation.
- Team listing joins manager/member metadata.
- Handles manager-protection style checks in membership operations.

## Main tables touched

- `teams`
- `team_members`
- `team_managers`
- `employees`
