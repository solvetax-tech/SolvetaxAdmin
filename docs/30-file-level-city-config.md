# File-Level Doc: `app/gst_registration/city_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Provides city lookup/filter endpoint by state code for GST/customer form selection.

## Router

- Prefix: `/api/v1/city-config`
- Tag: `City Config`

## Endpoint in this file

- `GET /api/v1/city-config`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Requires state code context.
- Supports optional search filtering for city names.
- Returns config rows suitable for dropdown/autocomplete usage.

## Main tables touched

- `city_config`
