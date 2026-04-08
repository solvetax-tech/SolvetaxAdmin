# File-Level Doc: `app/follow_ups/gst_filing_manual_followups.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles manual followup creation and updates for GST filing services, including assignment, schedule control, and status lifecycle updates.

## Router

- Prefix: `/api/v1/filing-followups`
- Tag: `GST Filing Followups`

## Endpoints in this file

- `POST /api/v1/filing-followups/`
  - Create followup for filing-related customer service.
- `POST /api/v1/filing-followups/{followup_id}`
  - Update followup details/state.

## Permission usage

- Create: `EMPLOYEE:READ`
- Update: `EMPLOYEE:WRITE`

## Business rules

- Followup time must be valid (future-oriented checks on create).
- Duplicate pending followup windows are prevented.
- Finalized statuses (such as completed/cancelled) are guarded from invalid transitions.
- Re-scheduling resets reminder flags/counters.
- Assignment logic can derive assignee from current user or RM fallback path.

## Status model

- API-driven states: `PENDING`, `COMPLETED`, `CANCELLED`
- Scheduler can later transition overdue pending followups to `MISSED`.

## Main tables touched

- `customer_service_followups`
- `customer_services`
- `employees`

## Operational notes

- Uses entity scoping to filing context (`GST_FILING` service entities).
- Complements registration followups module and shares similar workflow semantics.
