# File-Level Doc: `app/gst_registration/gst_registration.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Manages GST registration lifecycle for customers: create, filter/list, edit, deactivate, and activate with related cascades and service linking.

## Router

- Prefix: `/api/v1/gst-registrations`
- Tag: `GST Registration`

## Endpoints in this file

- `POST /api/v1/gst-registrations`
- `GET /api/v1/gst-registrations/dynamic_filter`
- `POST /api/v1/gst-registrations/{gst_id}/edit`
- `DELETE /api/v1/gst-registrations/{gst_id}/soft_delete`
- `POST /api/v1/gst-registrations/{gst_id}/activate`

## Permission usage

- Create: `EMPLOYEE:WRITE`
- Read/filter: `EMPLOYEE:READ`
- Edit: `USER_ACCESS:WRITE`
- Activate/deactivate: `EMPLOYEE:WRITE`

## Core behaviors

- Create:
  - validates customer activity.
  - validates GST identity/contact fields and duplicates.
  - inserts registration row.
  - creates/updates corresponding `customer_services` entry.
  - writes version audit.
- Filter:
  - dynamic filtering with visibility constraints based on role/user.
- Edit:
  - partial updates with duplicate checks and guarded fields.
  - version audit insert.
- Soft delete / activate:
  - toggles GST `is_active`.
  - cascades active state to persons/documents.
  - syncs customer service status.
  - version audit insert.

## Main tables touched

- `gst_registration`
- `customers`
- `customer_services`
- `gst_registration_persons`
- `gst_registration_documents`
- `employees`
- `versions`

## Operational notes

- This file establishes registration state used by filing prefill and filing status synchronization.
- Workflow/business status (`registration_status`) and operational active flag (`is_active`) are distinct concerns.
