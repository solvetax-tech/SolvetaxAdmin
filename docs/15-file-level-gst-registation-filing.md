# File-Level Doc: GST Filing Core (`app/gst_registration_filing/gst_registation_filing.py`)

Owner: Engineering Team  
Last Verified On: 2026-04-07

> Note: filename uses `registation` in codebase; documentation uses "registration" terminology for readability.

## Purpose

Primary GST filing workflow API: prefill, create, yearly create, edit, activate/deactivate, return-status updates, and bulk delete of missed return details.

## Router

- Prefix: `/api/v1/gst-filings`
- Tag: `GST Filings`

## Endpoints in this file

- `GET /filter`
- `GET /gst-registration/{gst_registration_id}/prefill`
- `POST /`
- `POST /gst-filings/yearly`
- `PATCH /gst-filings/{filing_id}`
- `DELETE /gst-filings/{filing_id}/deactivate`
- `POST /gst-filings/{filing_id}/activate`
- `PATCH /gst-filings/{filing_id}/returns/status`
- `POST /gst-filings/returns/delete-missed`

## Permission usage

- Read operations: `EMPLOYEE:READ`
- Write operations: `EMPLOYEE:WRITE`

## Core behaviors

- Prefill endpoint loads registration-linked filing defaults (and business context).
- Create endpoint:
  - validates customer + optional GST registration link.
  - populates filing fields from payload and fallback sources.
  - inserts filing row and corresponding return-detail schedule rows.
  - links/updates customer services and version audit.
- Edit endpoint:
  - dynamic field updates with validation and normalization.
  - can regenerate return-detail schedule when schedule-driving fields change.
- Deactivate/activate:
  - toggles filing active state.
  - cascades to filing docs and return details.
  - updates customer-service status and version logs.
- Returns status endpoint:
  - updates allowed status columns and/or row active state with applicability checks.
- Bulk delete endpoint:
  - deletes only return-detail rows where at least one status is `MISSED`.

## Main tables touched

- `gst_filings`
- `gst_filing_return_details`
- `gst_registration`
- `customers`
- `customer_services`
- `gst_filings_documents`
- `versions`

## Operational notes

- This file is the central authority for filing lifecycle and recurrence seed data.
- Scheduler behavior in `app/schedular/schedular.py` depends on fields managed here (including `is_auto_enabled` and `gst_reg_status`).
