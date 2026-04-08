# GST Registration Modules

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Core GST Registration (`app/gst_registration/gst_registration.py`, prefix `/api/v1/gst-registrations`)

- `POST /api/v1/gst-registrations` - create GST registration + link customer service.
- `GET /api/v1/gst-registrations/dynamic_filter` - list/filter registrations with visibility.
- `POST /api/v1/gst-registrations/{gst_id}/edit` - dynamic update.
- `DELETE /api/v1/gst-registrations/{gst_id}/soft_delete` - deactivate GST + cascade persons/docs.
- `POST /api/v1/gst-registrations/{gst_id}/activate` - reactivate GST + cascade persons/docs.

### Behavior Notes

- Validates active customer before create.
- Performs duplicate checks for GSTIN/username/pan/mobile/email combinations.
- Writes `customer_services` for GST registration entity.
- Writes `versions` for create/update/delete/activate.

## GST People (`app/gst_registration/gst_people.py`, prefix `/api/v1/gst-people`)

- `GET /gst-registration/{gst_id}/designations` - designations from config by ownership category.
- `POST /api/v1/gst-people` - create person row under GST registration.
- `GET /api/v1/gst-people/dynamic_filter` - filter/list persons.
- `POST /api/v1/gst-people/{person_id}/edit` - edit person.
- `DELETE /api/v1/gst-people/{person_id}/soft_delete` - deactivate person + person docs.
- `POST /api/v1/gst-people/{person_id}/activate` - activate person + person docs.

### Behavior Notes

- Enforces primary-person constraints.
- On person mobile updates, related document mobile values are synced.
- Uses visibility constraints through GST-linked ownership.

## GST Documents (`app/gst_registration/gst_documents.py`, prefix `/api/v1/gst-documents`)

- `POST /api/v1/gst-documents` - create document for registration person.
- `GET /api/v1/gst-documents/dynamic_filter` - list/filter documents.
- `POST /api/v1/gst-documents/{document_id}/edit` - update document metadata/verification fields.
- `DELETE /api/v1/gst-documents/{document_id}/soft_delete` - deactivate document.
- `POST /api/v1/gst-documents/{document_id}/activate` - activate document.
- Also contains filing-document deactivation endpoint:
  - `DELETE /api/v1/gst-documents/gst-filing-documents/{document_id}/deactivate`

## Blob Access (`app/gst_registration/gst_blob.py`, prefix `/api/v1/gst-blob`)

- `POST /upload` - upload file to Azure Blob and return URL.
- `GET /view` - generate SAS URL for inline view.
- `GET /download` - generate SAS URL for attachment download.

## Config and Lookup

- `app/gst_registration/gst_registration_config.py`:
  - `GET /api/v1/gst-registration/config/{config_type}`
- `app/gst_registration/document_config.py`:
  - `GET /api/v1/document-config/gst-registration/{gst_id}/required-documents`
  - `GET /api/v1/document-config/document-config`
- `app/gst_registration/city_config.py`:
  - `GET /api/v1/city-config`

## Status and State Model

- Business lifecycle is in `gst_registration.registration_status` (for example `DRAFT`, `APPROVED`, `SUSPENDED`, `CANCELLED`).
- Operational activity is via `is_active`.
- Soft delete/activate cascades to:
  - `gst_registration_persons`
  - `gst_registration_documents`
  - `customer_services.status`

## Tables Used

- `gst_registration`
- `gst_registration_persons`
- `gst_registration_documents`
- `gst_registration_config`
- `document_config`
- `city_config`
- `customer_services`
- `customers`
- `employees`
- `versions`
- `gst_filings_documents` (cross-domain deactivate endpoint)
