# File-Level Doc: `app/follow_ups/gst_reg_manual_followups.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles manual followup lifecycle for GST registration-related customer services.

## Router

- Prefix: `/api/v1/Followups`
- Tag: `Followups`

## Endpoints in this file

- `GET /api/v1/Followups/customer-service-followups/filter`
- `POST /api/v1/Followups/customer-service-followups`
- `POST /api/v1/Followups/customer-service-followups/{followup_id}`

## Permission usage

- Filter/create: `EMPLOYEE:READ`
- Update: `EMPLOYEE:WRITE`

## Core behaviors

- Rich dynamic filtering with role visibility and pagination modes.
- Create enforces:
  - active customer-service linkage,
  - no duplicate pending followup at same schedule,
  - assignment logic for RM/OP/user roles.
- Update enforces finalized-state guards and controlled status transitions.
- Status progression aligns with scheduler, which can later mark overdue pending items as `MISSED`.

## Main tables touched

- `customer_service_followups`
- `customer_services`
- `service_config`
- `customers`
- `employees`
