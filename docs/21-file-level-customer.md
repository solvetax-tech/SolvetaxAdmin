# File-Level Doc: `app/customer_registration/customer.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Core customer lifecycle management: create, read, filter, edit, activate/deactivate, business-description generation, and business image upload.

## Router

- Prefix: `/api/v1/customers`
- Tag: `Customers`

## Endpoints in this file

- `POST /api/v1/customers`
- `POST /api/v1/customers/{customer_id}/edit`
- `POST /api/v1/customers/business-description/generate`
- `GET /api/v1/customers/{customer_id}`
- `GET /api/v1/customers/customer_get/filter`
- `POST /api/v1/customers/business-image/upload`
- `DELETE /api/v1/customers/{customer_id}/soft_delete`
- `POST /api/v1/customers/{customer_id}/activate`

## Permission usage

- Reads: `EMPLOYEE:READ`
- Mutations: `EMPLOYEE:WRITE`

## Core behaviors

- Strong payload normalization and validation through customer schemas.
- Duplicate checks for key identifiers (mobile/email).
- Role-aware defaulting for RM/OP assignment in create/edit paths.
- Soft delete / activate includes conditional GST cascade behavior.
- AI generation endpoint returns suggested business description text (no mandatory DB persistence).
- Business image upload endpoint stores file externally and returns URL.
- Writes to `versions` on major state-changing operations.

## Main tables touched

- `customers`
- `gst_registration`
- `gst_registration_persons`
- `gst_registration_documents`
- `employees`
- `versions`
