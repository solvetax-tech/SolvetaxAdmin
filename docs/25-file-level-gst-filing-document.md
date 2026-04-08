# File-Level Doc: `app/gst_registration_filing/gst_filing_document.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Manages GST filing document records: create, edit, filter, activate, and deactivate.

## Router

- Prefix: `/api/v1/gst-filings-docs`
- Tag: `GST Filings Docs`

## Endpoints in this file

- `POST /api/v1/gst-filings-docs`
- `PATCH /api/v1/gst-filings-docs/{document_id}`
- `GET /api/v1/gst-filings-docs/gst-filing-documents/filter`
- `DELETE /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/deactivate`
- `POST /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/activate`

## Permission usage

- Filter: `EMPLOYEE:READ`
- Mutations: `EMPLOYEE:WRITE`

## Core behaviors

- Validates parent filing existence/activity.
- Supports GSTIN fallback from parent filing context.
- Maintains verification fields coherently for verified/unverified updates.
- Uses soft delete/activate lifecycle (`is_active`).
- Logs write operations to `versions`.

## Main tables touched

- `gst_filings_documents`
- `gst_filings`
- `employees`
- `versions`
