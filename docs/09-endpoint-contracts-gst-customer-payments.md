# Endpoint Contracts: Customer, GST, and Payments

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Customer (`/api/v1/customers`)

### `POST /api/v1/customers`
- **Auth**: `EMPLOYEE:WRITE`
- **Body**: `CustomerIn`
- **Success**: created customer object.
- **Writes**: `customers`, `versions`.

### `POST /api/v1/customers/{customer_id}/edit`
- **Auth**: `EMPLOYEE:WRITE`
- **Body**: `CustomerEditIn` (at least one field required).
- **Success**: updated customer object.
- **Validation**: no-op edits rejected, duplicate mobile/email checks.

### `GET /api/v1/customers/{customer_id}`
- **Auth**: `EMPLOYEE:READ`
- **Success**: customer + RM/OP display fields.

### `GET /api/v1/customers/customer_get/filter`
- **Auth**: `EMPLOYEE:READ`
- **Query**: rich filter set + pagination.
- **Success**: paginated customer list.

### `DELETE /api/v1/customers/{customer_id}/soft_delete`
- **Auth**: `EMPLOYEE:WRITE`
- **Success**: customer deactivated.
- **Side effects**: optional GST/person/doc cascade based on linked records.

### `POST /api/v1/customers/{customer_id}/activate`
- **Auth**: `EMPLOYEE:WRITE`
- **Success**: customer activated + optional GST cascade.

## GST Registration (`/api/v1/gst-registrations`, `/api/v1/gst-people`, `/api/v1/gst-documents`)

### Registration
- `POST /api/v1/gst-registrations` (`EMPLOYEE:WRITE`) - create GST registration.
- `GET /api/v1/gst-registrations/dynamic_filter` (`EMPLOYEE:READ`) - filter/list.
- `POST /api/v1/gst-registrations/{gst_id}/edit` (`USER_ACCESS:WRITE`) - update.
- `DELETE /api/v1/gst-registrations/{gst_id}/soft_delete` (`EMPLOYEE:WRITE`) - deactivate.
- `POST /api/v1/gst-registrations/{gst_id}/activate` (`EMPLOYEE:WRITE`) - activate.

### People
- `GET /api/v1/gst-people/gst-registration/{gst_id}/designations` (`EMPLOYEE:READ`)
- `POST /api/v1/gst-people` (`EMPLOYEE:WRITE`)
- `GET /api/v1/gst-people/dynamic_filter` (`EMPLOYEE:READ`)
- `POST /api/v1/gst-people/{person_id}/edit` (`USER_ACCESS:WRITE`)
- `DELETE /api/v1/gst-people/{person_id}/soft_delete` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-people/{person_id}/activate` (`EMPLOYEE:WRITE`)

### Documents
- `POST /api/v1/gst-documents` (`EMPLOYEE:WRITE`)
- `GET /api/v1/gst-documents/dynamic_filter` (`EMPLOYEE:READ`)
- `POST /api/v1/gst-documents/{document_id}/edit` (`USER_ACCESS:WRITE`)
- `DELETE /api/v1/gst-documents/{document_id}/soft_delete` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-documents/{document_id}/activate` (`EMPLOYEE:WRITE`)

### Contract Notes
- Visibility filters are role-aware and applied in list/filter endpoints.
- Soft-delete/activate operations usually cascade and audit to `versions`.
- Primary-person and verification constraints are enforced server-side.

## GST Filing (`/api/v1/gst-filings`, `/api/v1/gst-filings-docs`)

### Filing
- `GET /api/v1/gst-filings/filter` (`EMPLOYEE:READ`)
- `GET /api/v1/gst-filings/gst-registration/{gst_registration_id}/prefill` (`EMPLOYEE:READ`)
- `POST /api/v1/gst-filings` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-filings/gst-filings/yearly` (`EMPLOYEE:WRITE`)
- `PATCH /api/v1/gst-filings/gst-filings/{filing_id}` (`EMPLOYEE:WRITE`)
- `DELETE /api/v1/gst-filings/gst-filings/{filing_id}/deactivate` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-filings/gst-filings/{filing_id}/activate` (`EMPLOYEE:WRITE`)
- `PATCH /api/v1/gst-filings/gst-filings/{filing_id}/returns/status` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-filings/gst-filings/returns/delete-missed` (`EMPLOYEE:WRITE`)

### Filing documents
- `POST /api/v1/gst-filings-docs` (`EMPLOYEE:WRITE`)
- `PATCH /api/v1/gst-filings-docs/{document_id}` (`EMPLOYEE:WRITE`)
- `GET /api/v1/gst-filings-docs/gst-filing-documents/filter` (`EMPLOYEE:READ`)
- `DELETE /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/deactivate` (`EMPLOYEE:WRITE`)
- `POST /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/activate` (`EMPLOYEE:WRITE`)

## Payments

### Registration payments (`/api/v1/payments`)
- `POST /` (`EMPLOYEE:WRITE`)
- `GET /dynamic_filter` (`EMPLOYEE:READ`)
- `DELETE /{payment_id}/soft_delete` (`EMPLOYEE:WRITE`)
- `POST /{payment_id}/activate` (`EMPLOYEE:WRITE`)

### Filing payments (`/api/v1/filing-payments`)
- `POST /` (`EMPLOYEE:WRITE`)
- `DELETE /{payment_id}/soft_delete` (`EMPLOYEE:WRITE`)
- `POST /{payment_id}/activate` (`EMPLOYEE:WRITE`)

### Payment config (`/api/v1/payments_config`)
- `GET /payment-config` (`EMPLOYEE:READ`)
- `GET /amount/{entity_id}` (`EMPLOYEE:READ`)

### Contract Notes
- Financial fields use strict decimal validation.
- Duplicate fully-paid active records are blocked.
- Payment write operations are audited to `versions`.
