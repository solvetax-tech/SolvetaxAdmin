# Database Reference (Code-Derived)

Owner: Engineering Team  
Last Verified On: 2026-04-07

This reference is derived from SQL usage in Python modules. It documents how tables are used by APIs/jobs currently in code.

## Core Identity and Access

- `employees`: authentication, profile, active checks, RM/OP/manager joins.
- `roles`, `employee_roles`, `features`, `role_features`: permission graph used to build JWT permission claims.
- `session_token`: active sessions for JWT + refresh token lifecycle.
- `session_audit_log`: login/logout/session validation audit events.
- `teams`, `team_members`, `team_managers`: team and hierarchy management.
- `employee_email_verifications`, `password_reset_otps`: signup and password reset OTP flows.

## Customer Domain

- `customers`: canonical customer profile and ownership metadata.
- `customer_services`: service-instance tracking by customer and entity linkage.
- `service_config`: service master catalog.
- `customer_service_followups`: manual followups and scheduler status transitions.

## GST Registration Domain

- `gst_registration`: registration master + registration workflow status.
- `gst_registration_persons`: linked person records under registrations.
- `gst_registration_documents`: document records linked to registration persons.
- `gst_registration_config`: registration config master.
- `document_config`: required-document master and ownership/category-based document rules.
- `city_config`: state/city lookup master.

## GST Filing Domain

- `gst_filings`: filing master rows.
- `gst_filing_return_details`: return-line details and due/status transitions.
- `gst_filings_documents`: filing document rows.
- `gst_filing_config`: filing config master.

## Payments Domain

- `payments`: registration and filing payments (`entity_type`-based polymorphism).
- `payment_config`: payment config master used for amount/config reads.

## Audit Domain

- `versions`: generic entity action history (`CREATE`, `UPDATE`, `DELETE`, `ACTIVATE`).

## Table Usage Cross-links

- **Auth endpoints**: `employees`, `session_token`, `session_audit_log`, role tables.
- **Customer APIs**: `customers`, `customer_services`, `versions`.
- **GST registration APIs**: `gst_registration`, `gst_registration_persons`, `gst_registration_documents`, `customer_services`, `versions`, config tables.
- **GST filing APIs**: `gst_filings`, `gst_filing_return_details`, `gst_filings_documents`, `customer_services`, `versions`.
- **Payments APIs**: `payments`, `payment_config`, plus entity tables (`gst_registration`, `gst_filings`), `versions`.
- **Dashboard/ops**: aggregate reads across `customers`, `employees`, `payments`, `gst_filings`, `gst_filing_return_details`.

## Trigger/Function Behavior Notes (as reflected in current code usage)

- Application logic assumes DB-side sync/status behaviors for some fields (for example, filing and registration status propagation).
- Scheduler and API flows rely on consistent DB invariants for:
  - return due/status transitions,
  - service active/inactive linkage,
  - payment amount correctness,
  - timestamp consistency.
- For full trigger DDL definitions, maintain a dedicated SQL migration/DDL repository (currently this repo stores SQL primarily inline in Python).
