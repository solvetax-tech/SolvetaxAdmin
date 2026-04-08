# File-Level Doc: Schemas Overview (`app/**/schemas.py`)

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Central reference for Pydantic schema files used across modules for request validation, normalization, and response shaping.

## Schema files covered

- `app/sign_up/schemas.py`
- `app/customer_registration/schemas.py`
- `app/gst_registration/schemas.py`
- `app/gst_registration_filing/schemas.py`
- `app/payments/schemas.py`

## Common schema patterns

- `extra="forbid"` to block unknown fields.
- Whitespace trimming and normalization.
- Enum/literal constraints for controlled status/type fields.
- Field validators for:
  - email/mobile/GSTIN/PAN formats
  - date/period patterns
  - numeric boundaries for amounts
- Model-level validators for cross-field rules (for example, mutually exclusive or required-combination fields).

## Domain highlights

- **Sign-up/auth schemas**: verification/login/reset payloads.
- **Customer schemas**: customer create/edit with text sanitization and identity validation.
- **GST registration schemas**: registration/person/document state constraints.
- **GST filing schemas**: filing frequency/category compatibility, filing period format enforcement, return status update payloads.
- **Payment schemas**: decimal precision and payment input constraints.

## Operational notes

- Schema validation is the first guardrail before DB logic executes.
- Several APIs add extra business validation in handlers after schema validation passes.
