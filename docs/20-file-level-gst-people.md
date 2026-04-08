# File-Level Doc: `app/gst_registration/gst_people.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles person-level records under GST registrations: create, filter, edit, activate/deactivate, and designation lookups.

## Router

- Prefix: `/api/v1/gst-people`
- Tag: `GST Registration People`

## Endpoints in this file

- `GET /api/v1/gst-people/gst-registration/{gst_id}/designations`
- `POST /api/v1/gst-people`
- `GET /api/v1/gst-people/dynamic_filter`
- `POST /api/v1/gst-people/{person_id}/edit`
- `DELETE /api/v1/gst-people/{person_id}/soft_delete`
- `POST /api/v1/gst-people/{person_id}/activate`

## Permission usage

- Read endpoints: `EMPLOYEE:READ`
- Create/activate/deactivate: `EMPLOYEE:WRITE`
- Edit: `USER_ACCESS:WRITE`

## Core behaviors

- Derives person context from parent GST registration (customer linkage, GSTIN, ownership).
- Enforces primary-person rules (single active primary and guarded transitions).
- Propagates some person updates (for example, contact-related) to related docs where applicable.
- Uses dynamic filtering with visibility controls.
- Soft delete/activate cascades to linked document rows.
- Writes changes to `versions`.

## Main tables touched

- `gst_registration_persons`
- `gst_registration`
- `gst_registration_documents`
- `gst_registration_config`
- `versions`
