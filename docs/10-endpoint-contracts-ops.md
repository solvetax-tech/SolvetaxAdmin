# Endpoint Contracts: Followups, Dashboard, Scheduler, Version

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Followups

### Registration followups (`/api/v1/Followups`)
- `GET /customer-service-followups/filter` (`EMPLOYEE:READ`)
  - Supports broad filtering, role visibility, and pagination.
- `POST /customer-service-followups` (`EMPLOYEE:READ`)
  - Creates manual followup for active customer service.
- `POST /customer-service-followups/{followup_id}` (`EMPLOYEE:WRITE`)
  - Updates followup status/timing/assignment with finalized-state guards.

### Filing followups (`/api/v1/filing-followups`)
- `POST /` (`EMPLOYEE:READ`) - create.
- `POST /{followup_id}` (`EMPLOYEE:WRITE`) - update.

## Dashboard (`/api/v1/dashboard`)

- `GET /employee-metrics` (`USER_ACCESS:READ`)
- `GET /customer-metrics` (`USER_ACCESS:READ`)
- `GET /payment-metrics` (`USER_ACCESS:READ`)
- `GET /gst-missed-filings/gt-one` (`EMPLOYEE:READ`)
- `GET /gst-missed-filings/exact-one` (`EMPLOYEE:READ`)
- `GET /gst-missed-filings/buckets` (`EMPLOYEE:READ`)

### Contract notes
- Metrics endpoints support time-window filters and standardized range validation.
- Missed-filing endpoints apply GST filing visibility rules and pagination.
- Buckets endpoint returns both counts and selected bucket data.

## Version API (`/api/v1/version`)

- `GET /dynamic_filter` (`EMPLOYEE:READ`)
  - Query filters for entity/action/date fields.
  - Returns joined audit records from `versions` + employee/customer labels.

## Scheduler Contracts (`app/schedular/schedular.py`)

Scheduler is internal (not an HTTP API), but has stable behavior contracts:

- marks overdue followups as `MISSED`.
- deactivates expired session tokens.
- transitions overdue GST return statuses to `MISSED`.
- auto-generates next GST return-detail rows when:
  - filing is active,
  - auto-enabled,
  - and `gst_reg_status = 'APPROVED'`.

## Error/Response Conventions (cross-module)

- Errors are returned via `HTTPException` with `detail`.
- List APIs typically return:
  - `items` (records array)
  - pagination metadata (`total`, `limit`, `offset`, optional `next_cursor`).
- Write APIs typically return:
  - message/status text
  - primary entity identifiers
  - occasionally full updated object snapshots.
