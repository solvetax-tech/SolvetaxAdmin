# Customer and Service Modules

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Customer APIs (`app/customer_registration/customer.py`, prefix `/api/v1/customers`)

- `POST /api/v1/customers` - create customer.
- `POST /api/v1/customers/{customer_id}/edit` - dynamic partial update.
- `POST /api/v1/customers/business-description/generate` - AI-generated description (no DB write).
- `GET /api/v1/customers/{customer_id}` - get one customer with RM/OP names.
- `GET /api/v1/customers/customer_get/filter` - list/filter with pagination.
- `POST /api/v1/customers/business-image/upload` - upload business image to blob and return URL.
- `DELETE /api/v1/customers/{customer_id}/soft_delete` - soft deactivate customer and optional GST cascade.
- `POST /api/v1/customers/{customer_id}/activate` - activate customer and optional GST cascade.

## Service APIs (`app/customer_registration/services.py`, prefix `/api/v1/services`)

- `GET /customer-services/filter` - dynamic customer-service filtering.
- `POST /customer-services/{service_id}/activate` - activate customer service row.
- `POST /customer-services/{service_id}/deactivate` - deactivate service (blocked on pending followups).
- `GET /services/dashboard/stats` - aggregate service metrics.
- `GET /services/pending` - pending service list.

## Service Config (`app/customer_registration/service_config.py`, prefix `/api/v1/services-config`)

- `GET /services` - active service master records; optional category filter.

## Validation and Normalization Highlights

- Pydantic models in `app/customer_registration/schemas.py` sanitize/normalize:
  - mobile regex validation.
  - lowercased emails.
  - HTML escape + trim for text fields.
  - positive integer constraints for employee references.
- Edit endpoint rejects empty patch and no-op patch.
- Duplicate checks for email/mobile are enforced in create and edit paths.
- Service arrays are cleaned (trimmed, deduplicated).

## AI Business Description (`app/customer_registration/business_description_ai.py`)

- Uses Azure OpenAI Chat Completions.
- Returns generated text for UI use; does not directly persist it.
- Applies constraints on tone/length and safe fallback behavior.

## Audit and Versioning

- Customer create/edit/delete/activate write rows to `versions`.
- Customer-service activate/deactivate also writes to `versions`.

## Tables Used

- `customers`
- `customer_services`
- `service_config`
- `customer_service_followups` (deactivation guard)
- `gst_registration` (cascade checks)
- `gst_registration_persons` (cascade active/inactive)
- `gst_registration_documents` (cascade active/inactive)
- `employees` (name resolution for RM/OP)
- `versions`
