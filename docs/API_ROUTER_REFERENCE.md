# API Router Reference

This file documents router modules currently present in `app/` and their primary endpoint responsibilities.

## Router Mounting Source
- App entrypoint: `app/main.py`
- Full route path = `router.prefix` + endpoint decorator path

---

## Auth and Employee

## `app/sign_up/signup.py`
- Prefix: `/app/v1`
- Tags: Signup
- Key routes:
  - `POST /signup` - create employee account

## `app/sign_up/login.py`
- Prefix: `/app/v1`
- Tags: Login
- Key routes:
  - `POST /login` - login and issue tokens
  - `POST /refresh` - refresh access token
  - `POST /logout` - logout and revoke session

## `app/sign_up/email_verification.py`
- Prefix: `/app/v1`
- Tags: EmailVerification
- Key routes:
  - `POST /email-verification/request`
  - `POST /email-verification/verify`

## `app/sign_up/forgot.py`
- Prefix: `/app/v1`
- Tags: ForgotPassword
- Key routes:
  - `POST /forgot-password/request`
  - `POST /forgot-password/verify`

## `app/sign_up/employee_edit.py`
- Prefix: `/api/v1/employees`
- Tags: Employees
- Key routes:
  - `POST /{emp_id}/emp_dyn/edit`
  - `GET /filter`
  - `GET /employee/{emp_id}`
  - `GET /active-rm`
  - `GET /active-op`
  - `GET /active-managers`
  - `DELETE /{emp_id}/soft_delete`
  - `GET /roles`
  - `POST /create` (role creation)
  - `POST /{emp_id}/change-password`

## `app/security/teams_api.py`
- Prefix: `/app/v1/teams`
- Tags: Teams
- Key routes:
  - `POST /create`
  - `GET /teams`
  - `POST /edit/{team_id}`
  - `POST /add-member`
  - `POST /remove-member`
  - `GET /{team_id}/members`

---

## Customer and Services

## `app/customer_registration/customer.py`
- Prefix: `/api/v1/customers`
- Tags: Customers
- Key routes:
  - `POST /`
  - `GET /{customer_id}`
  - `GET /customer_get/filter`
  - `POST /{customer_id}/edit`
  - `DELETE /{customer_id}/soft_delete`
  - `POST /{customer_id}/activate`

## `app/customer_registration/services.py`
- Prefix: `/api/v1/services`
- Tags: services
- Key routes:
  - `GET /customer-services/filter`
  - `POST /customer-services/{service_id}/activate`
  - `POST /customer-services/{service_id}/deactivate`
  - `GET /services/dashboard/stats`
  - `GET /services/pending`

## `app/customer_registration/service_config.py`
- Prefix: `/api/v1/services-config`
- Tags: Services_config
- Key routes:
  - `GET /services`

---

## GST Registration

## `app/gst_registration/gst_registration.py`
- Prefix: `/api/v1/gst-registrations`
- Tags: GST Registration
- Key routes:
  - `POST /`
  - `GET /dynamic_filter`
  - `POST /{gst_id}/edit`
  - `DELETE /{gst_id}/soft_delete`
  - `POST /{gst_id}/activate`

## `app/gst_registration/gst_people.py`
- Prefix: `/api/v1/gst-people`
- Tags: GST Registration People
- Key routes:
  - `GET /gst-registration/{gst_id}/designations`
  - `POST /`
  - `GET /dynamic_filter`
  - `POST /{person_id}/edit`
  - `DELETE /{person_id}/soft_delete`
  - `POST /{person_id}/activate`

## `app/gst_registration/gst_documents.py`
- Prefix: `/api/v1/gst-documents`
- Tags: GST Registration Documents
- Key routes:
  - `POST /`
  - `GET /dynamic_filter`
  - `POST /{document_id}/edit`
  - `DELETE /{document_id}/soft_delete`
  - `POST /{document_id}/activate`

## `app/gst_registration/gst_blob.py`
- Prefix: `/api/v1/gst-blob`
- Tags: GST Registration Blob
- Key routes:
  - `POST /upload`
  - `GET /view`
  - `GET /download`

## `app/gst_registration/gst_registration_config.py`
- Prefix: `/api/v1/gst-registration`
- Tags: GST Registration Config
- Key routes:
  - `GET /config/{config_type}`

## `app/gst_registration/document_config.py`
- Prefix: `/api/v1/document-config`
- Tags: Document Config
- Key routes:
  - `GET /gst-registration/{gst_id}/required-documents`
  - `GET /document-config`

---

## GST Filing

## `app/gst_registration_filing/gst_registation_filing.py`
- Prefix: `/api/v1/gst-filings`
- Tags: GST Filings
- Key routes:
  - `GET /gst-filings/filter`
  - `POST /gst-filings`
  - `PATCH /gst-filings/{filing_id}`
  - `DELETE /gst-filings/{filing_id}/deactivate`
  - `POST /gst-filings/{filing_id}/activate`
  - `PATCH /gst-filings/{filing_id}/returns/status`

## `app/gst_registration_filing/gst_filing_config.py`
- Prefix: `/api/v1/gst-filing-config`
- Tags: GST Filing Config
- Key routes:
  - `GET /gst-filing-config`

## `app/gst_registration_filing/gst_filing_document.py`
- Prefix: `/api/v1/gst-filings-docs`
- Tags: GST Filings Docs
- Key routes:
  - `POST /`
  - `PATCH /{document_id}`
  - `GET /gst-filing-documents/filter`
  - `DELETE /gst-filing-documents/{document_id}/deactivate`
  - `POST /gst-filing-documents/{document_id}/activate`

Note:
- Verify router inclusion in `main.py` if these endpoints are expected active.

---

## Payments

## `app/payments/registration_payments.py`
- Prefix: `/api/v1/payments`
- Tags: Registration Payments
- Key routes:
  - `POST /`
  - `GET /dynamic_filter`
  - `DELETE /{payment_id}/soft_delete`
  - `POST /{payment_id}/activate`

## `app/payments/filing_payments.py`
- Prefix: `/api/v1/filing-payments`
- Tags: Filing Payments
- Key routes:
  - `POST /`
  - `GET /dynamic_filter`
  - `DELETE /{payment_id}/soft_delete`
  - `POST /{payment_id}/activate`

## `app/payments/payments_config.py`
- Prefix: `/api/v1/payments_config`
- Tags: Payments Config
- Key routes:
  - `GET /payment-config`
  - `GET /amount/{entity_id}`

---

## Follow-ups

## `app/follow_ups/gst_reg_manual_followups.py`
- Prefix: `/api/v1/Followups`
- Tags: Followups
- Key routes:
  - `GET /customer-service-followups/filter`
  - `POST /customer-service-followups`
  - `POST /customer-service-followups/{followup_id}`

## `app/follow_ups/gst_filing_manual_followups.py`
- Prefix: `/api/v1/filing-followups`
- Tags: GST Filing Followups
- Key routes:
  - `GET /filter`
  - `POST /`
  - `POST /{followup_id}`

---

## Dashboard and Version

## `app/Dashboard/dashboard.py`
- Prefix: `/api/v1/dashboard`
- Tags: Dashboard Metrics
- Key routes:
  - `GET /employee-metrics`
  - `GET /customer-metrics`
  - `GET /payment-metrics`

## `app/version/version.py`
- Prefix: `/api/v1/version`
- Tags: Version History
- Key routes:
  - `GET /dynamic_filter`

