# File-Level Doc: `app/gst_registration_filing/gst_filing_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Read-only API for GST filing configuration master data used by filing workflows/UI dropdowns.

## Router

- Prefix: `/api/v1/gst-filing-config`
- Tag: `GST Filing Config`

## Endpoint in this file

- `GET /api/v1/gst-filing-config/gst-filing-config`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Provides filterable/paginated list over filing configuration records.
- Used for category/frequency/return-type applicability support in filing flows.
- Read-only; no create/update/delete endpoints in this file.

## Main tables touched

- `gst_filing_config`
