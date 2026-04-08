# File-Level Doc: `app/gst_registration/document_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Exposes required-document resolution APIs and document-config listing for GST registration flows.

## Router

- Prefix: `/api/v1/document-config`
- Tag: `Document Config`

## Endpoints in this file

- `GET /api/v1/document-config/gst-registration/{gst_id}/required-documents`
- `GET /api/v1/document-config/document-config`

## Permission usage

- Both endpoints: `EMPLOYEE:READ`

## Core behaviors

- Computes missing required docs by combining:
  - GST ownership/category context,
  - person linkage,
  - config master definitions,
  - already-uploaded active docs.
- Second endpoint provides generic filtered/paginated config master list.

## Main tables touched

- `document_config`
- `gst_registration`
- `gst_registration_persons`
- `gst_registration_documents`
