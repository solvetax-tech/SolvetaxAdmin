# File-Level Doc: `app/schedular/schedular.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Runs periodic background jobs for operational maintenance and status automation.

## Execution model

- Started from app startup when scheduler is enabled via environment/config.
- Loop interval: approximately every 60 seconds.

## Jobs in this file

1. **Followup overdue update**
   - Marks pending followups as `MISSED` when overdue.
   - Table: `customer_service_followups`.

2. **Session expiry cleanup**
   - Deactivates expired active sessions.
   - Table: `session_token`.

3. **GST return overdue status transitions**
   - Converts return status fields from `NOT_FILED` to `MISSED` when due dates pass.
   - Table: `gst_filing_return_details` (joined with active filings).

4. **GST auto-generation of return detail rows**
   - Creates next cycle return-detail rows using date-shift logic.
   - Source tables: `gst_filings`, `gst_filing_return_details`.
   - Critical guard: only when parent filing has `gst_reg_status = 'APPROVED'`.

## Data integrity guards

- Operates only on active rows where applicable.
- Uses schedule pointer (`next_auto_generate_at`) to avoid duplicate auto generation.
- Clears or updates scheduling pointers post-generation.

## Main tables touched

- `customer_service_followups`
- `session_token`
- `gst_filing_return_details`
- `gst_filings`

## Operational notes

- This file is core to asynchronous lifecycle behavior; API behavior and dashboard metrics can reflect scheduler outcomes shortly after each run.
- Any changes here should be validated against filing status assumptions and recurrence rules.
