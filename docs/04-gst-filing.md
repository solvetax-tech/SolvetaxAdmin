# GST Filing Modules

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Filing API (`app/gst_registration_filing/gst_registation_filing.py`, prefix `/api/v1/gst-filings`)

- `GET /api/v1/gst-filings/filter` - filing list with filters/visibility.
- `GET /api/v1/gst-filings/gst-registration/{gst_registration_id}/prefill` - prefill data from registration + customer context.
- `POST /api/v1/gst-filings` - create filing.
- `POST /api/v1/gst-filings/gst-filings/yearly` - yearly create convenience endpoint.
- `PATCH /api/v1/gst-filings/gst-filings/{filing_id}` - update filing.
- `DELETE /api/v1/gst-filings/gst-filings/{filing_id}/deactivate` - deactivate filing and related records.
- `POST /api/v1/gst-filings/gst-filings/{filing_id}/activate` - activate filing and related records.
- `PATCH /api/v1/gst-filings/gst-filings/{filing_id}/returns/status` - update return-detail statuses/active flag.
- `POST /api/v1/gst-filings/gst-filings/returns/delete-missed` - bulk delete only MISSED return-detail rows.

## Core Filing Behaviors

- Create flow supports deriving filing fields from linked `gst_registration` when provided.
- Persists business context fields on filing (`business_name`, `business_type`, `business_description`) through payload/fallback logic.
- Maintains `gst_reg_status` on filing when linked registration exists.
- Creates return-detail rows based on filing category, frequency, and taxpayer type.
- Upserts customer-service linkage for filing entity.
- Writes to `versions`.

## Filing Edit Behaviors

- Dynamic patch updates only supplied fields.
- Rebuilds return details when critical schedule-driving fields are changed.
- Can sync `gst_reg_status` from registration when registration linkage changes.

## Filing Documents (`app/gst_registration_filing/gst_filing_document.py`, prefix `/api/v1/gst-filings-docs`)

- `POST /api/v1/gst-filings-docs` - create filing document.
- `PATCH /api/v1/gst-filings-docs/{document_id}` - update document.
- `GET /api/v1/gst-filings-docs/gst-filing-documents/filter` - filter/list documents.
- `DELETE /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/deactivate` - deactivate.
- `POST /api/v1/gst-filings-docs/gst-filing-documents/{document_id}/activate` - activate.

## Filing Config (`app/gst_registration_filing/gst_filing_config.py`, prefix `/api/v1/gst-filing-config`)

- `GET /api/v1/gst-filing-config/gst-filing-config` - list filing config rows for UI/business logic.

## Schemas (`app/gst_registration_filing/schemas.py`)

- `GSTFilingIn`, `GSTFilingYearlyIn`, `GSTFilingEditIn`
  - category/frequency validations
  - period format validations
  - enum normalization/uppercase handling for key fields
- `GSTReturnStatusUpdateIn`
  - requires at least one status field or `is_active`
- `GSTReturnDetailsBulkDeleteIn`
  - validates list of return detail IDs for bulk delete

## Tables Used

- `gst_filings`
- `gst_filing_return_details`
- `gst_filings_documents`
- `gst_registration`
- `customers`
- `customer_services`
- `employees`
- `versions`
- `gst_filing_config`

## Scheduler Relationship

- Scheduler auto-generation only runs when parent filing is:
  - active
  - auto-enabled
  - `gst_reg_status = 'APPROVED'`
- Overdue return statuses are transitioned by scheduler job logic.
