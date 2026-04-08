# Followups, Dashboard, Scheduler, and Versioning

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Followups

### Registration Followups (`app/follow_ups/gst_reg_manual_followups.py`, prefix `/api/v1/Followups`)

- `GET /customer-service-followups/filter` - rich filtering + pagination + visibility.
- `POST /customer-service-followups` - create manual followup.
- `POST /customer-service-followups/{followup_id}` - update followup.

### Filing Followups (`app/follow_ups/gst_filing_manual_followups.py`, prefix `/api/v1/filing-followups`)

- `POST /` - create filing followup.
- `POST /{followup_id}` - update filing followup.

### Followup State Model

- Manual creation starts as `PENDING`.
- Update can move to `COMPLETED`/`CANCELLED` and sets `completed_at`.
- Scheduler can mark overdue pending followups as `MISSED`.

## Dashboard (`app/Dashboard/dashboard.py`, prefix `/api/v1/dashboard`)

- `GET /employee-metrics`
- `GET /customer-metrics`
- `GET /payment-metrics`
- `GET /gst-missed-filings/gt-one`
- `GET /gst-missed-filings/exact-one`
- `GET /gst-missed-filings/buckets`

### Dashboard Notes

- Uses shared filtering helpers for GST missed-filing endpoints.
- Uses visibility filters based on employee role and assigned RM/OP scope.
- Supports date filtering and pagination on list-style endpoints.

## Version API (`app/version/version.py`, prefix `/api/v1/version`)

- `GET /dynamic_filter` - filtered version/audit history with employee/customer joins.

## Scheduler (`app/schedular/schedular.py`)

Background loop (typically every 60 seconds) runs:

1. mark overdue followups as `MISSED`
2. deactivate expired sessions
3. mark overdue GST return statuses from `NOT_FILED` to `MISSED`
4. auto-generate next GST return-detail rows

### GST Auto-generation Guard

Auto-generation checks parent filing conditions before creating next rows:

- `is_active = TRUE`
- `is_auto_enabled = TRUE`
- `gst_reg_status = 'APPROVED'`

This prevents recurrence generation for non-approved GST registration context.

## Tables Used

- `customer_service_followups`
- `customer_services`
- `service_config`
- `customers`
- `employees`
- `payments`
- `versions`
- `session_token`
- `gst_filings`
- `gst_filing_return_details`
