# File-Level Doc: `app/gst_registration/gst_registration_config.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Serves GST registration config values by config type for UI and validation support.

## Router

- Prefix: `/api/v1/gst-registration`
- Tag: `GST Registration Config`

## Endpoint in this file

- `GET /api/v1/gst-registration/config/{config_type}`

## Permission usage

- `EMPLOYEE:READ`

## Core behaviors

- Normalizes and validates `config_type`.
- Returns active values mapped to requested config dimension.
- Read-only helper endpoint used by multiple GST registration forms.

## Main tables touched

- `gst_registration_config`
