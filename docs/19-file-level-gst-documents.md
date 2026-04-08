# File-Level Doc: `app/gst_registration/gst_documents.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Manages GST registration document lifecycle: create, filter, edit, activate/deactivate, and verification-related field handling.

## Router

- Prefix: `/api/v1/gst-documents`
- Tag: `GST Registration Documents`

## Endpoints in this file

- `POST /api/v1/gst-documents`
- `GET /api/v1/gst-documents/dynamic_filter`
- `POST /api/v1/gst-documents/{document_id}/edit`
- `DELETE /api/v1/gst-documents/{document_id}/soft_delete`
- `POST /api/v1/gst-documents/{document_id}/activate`
- `DELETE /api/v1/gst-documents/gst-filing-documents/{document_id}/deactivate` (cross-domain helper)

## Permission usage

- Create/activate/deactivate: `EMPLOYEE:WRITE`
- Filter: `EMPLOYEE:READ`
- Edit: `USER_ACCESS:WRITE`

## Core behaviors

- Validates parent person and parent GST registration state before create/update flows.
- Supports verification toggles with `verified`, `verified_by`, `verified_at` coherence.
- Applies role visibility filters in dynamic list endpoint.
- Uses soft delete/activate semantics (`is_active` toggle).
- Writes audit events to `versions`.

## Main tables touched

- `gst_registration_documents`
- `gst_registration_persons`
- `gst_registration`
- `employees`
- `versions`
- `gst_filings_documents` (deactivate helper endpoint)
