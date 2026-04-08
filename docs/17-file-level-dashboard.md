# File-Level Doc: `app/Dashboard/dashboard.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Provides dashboard/analytics APIs for employee/customer/payment metrics and GST missed-filing buckets with filters and visibility rules.

## Router

- Prefix: `/api/v1/dashboard`
- Tag: `Dashboard Metrics`

## Endpoints in this file

- `GET /employee-metrics`
- `GET /customer-metrics`
- `GET /payment-metrics`
- `GET /gst-missed-filings/gt-one`
- `GET /gst-missed-filings/exact-one`
- `GET /gst-missed-filings/buckets`

## Permission usage

- Metrics endpoints (`employee/customer/payment`): `USER_ACCESS:READ`
- GST missed-filing endpoints: `EMPLOYEE:READ`

## Core behaviors

- Supports date-window selection with:
  - pre-defined filter windows (today, last 7 days, last month, etc.)
  - explicit `start_date/end_date`
- GST missed-filing endpoints:
  - share filter builder logic.
  - apply role-based visibility constraints.
  - provide pagination and count metadata.
- Buckets endpoint:
  - exposes `exact_one`, `gt_one`, and configurable threshold bucket.

## Main tables touched

- `employees`
- `customers`
- `payments`
- `gst_filings`
- `gst_filing_return_details`

## Operational notes

- Timezone helper normalization is used for consistency on date-time filters.
- Useful for ops monitoring after scheduler transitions overdue returns/followups.
