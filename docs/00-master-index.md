# Solvetax Backend Documentation Index

Owner: Engineering Team  
Last Verified On: 2026-04-07

This documentation is generated from the current code under `app/` and focuses on API behavior, permission model, and database interaction patterns.

## Architecture Overview

- **Runtime**: FastAPI app bootstrapped in `app/main.py`.
- **Auth layer**:
  - `TokenValidatorMiddleware` in `app/token_validator.py` validates JWT + session row.
  - Route-level authorization is enforced using `require_permission()` from `app/security/rbac.py`.
- **Data access**: Async PostgreSQL queries via pooled connections (`get_db_pool`) and SQL written directly in Python modules.
- **Audit/versioning**: Most write APIs insert version rows into `solvetax.versions`.
- **Scheduler**: Background loop in `app/schedular/schedular.py` performs overdue/status automation.

## Router Map (from `app/main.py`)

- `app/sign_up/email_verification.py`
- `app/sign_up/signup.py`
- `app/sign_up/login.py`
- `app/sign_up/forgot.py`
- `app/security/teams_api.py`
- `app/customer_registration/customer.py`
- `app/gst_registration/gst_registration.py`
- `app/gst_registration/gst_people.py`
- `app/sign_up/employee_edit.py`
- `app/gst_registration/gst_documents.py`
- `app/gst_registration/gst_registration_config.py`
- `app/gst_registration_filing/gst_registation_filing.py`
- `app/gst_registration_filing/gst_filing_document.py`
- `app/Dashboard/dashboard.py`
- `app/gst_registration_filing/gst_filing_config.py`
- `app/version/version.py`
- `app/payments/registration_payments.py`
- `app/payments/filing_payments.py`
- `app/payments/payments_config.py`
- `app/gst_registration/gst_blob.py`
- `app/gst_registration/document_config.py`
- `app/gst_registration/city_config.py`
- `app/follow_ups/gst_reg_manual_followups.py`
- `app/follow_ups/gst_filing_manual_followups.py`
- `app/customer_registration/services.py`
- `app/customer_registration/service_config.py`

## Documentation Set

1. `docs/01-bootstrap-auth-security.md`
2. `docs/02-customer-services.md`
3. `docs/03-gst-registration.md`
4. `docs/04-gst-filing.md`
5. `docs/05-payments.md`
6. `docs/06-followups-dashboard-scheduler-version.md`
7. `docs/07-db-reference.md`
8. `docs/08-endpoint-contracts-auth-security.md`
9. `docs/09-endpoint-contracts-gst-customer-payments.md`
10. `docs/10-endpoint-contracts-ops.md`
11. `docs/11-file-level-employee-edit.md`
12. `docs/12-file-level-gst-filing-followups.md`
13. `docs/13-file-level-filing-payments.md`
14. `docs/14-file-level-scheduler.md`
15. `docs/15-file-level-gst-registation-filing.md`
16. `docs/16-file-level-gst-registration.md`
17. `docs/17-file-level-dashboard.md`
18. `docs/18-file-level-registration-payments.md`
19. `docs/19-file-level-gst-documents.md`
20. `docs/20-file-level-gst-people.md`
21. `docs/21-file-level-customer.md`
22. `docs/22-file-level-services.md`
23. `docs/23-file-level-login.md`
24. `docs/24-file-level-signup.md`
25. `docs/25-file-level-gst-filing-document.md`
26. `docs/26-file-level-gst-filing-config.md`
27. `docs/27-file-level-gst-blob.md`
28. `docs/28-file-level-document-config.md`
29. `docs/29-file-level-gst-registration-config.md`
30. `docs/30-file-level-city-config.md`
31. `docs/31-file-level-forgot.md`
32. `docs/32-file-level-email-verification.md`
33. `docs/33-file-level-teams-api.md`
34. `docs/34-file-level-version.md`
35. `docs/35-file-level-token-validator.md`
36. `docs/36-file-level-utils.md`
37. `docs/37-file-level-service-config.md`
38. `docs/38-file-level-payments-config.md`
39. `docs/39-file-level-gst-reg-followups.md`
40. `docs/40-file-level-main.md`
41. `docs/41-file-level-schemas-overview.md`
98. `docs/98-known-risks-and-todos.md`
99. `docs/99-quick-navigation.md`

## File Inventory by Module Group

- **Core/bootstrap**
  - `app/main.py`, `app/utils.py`, `app/logger.py`, `app/token_validator.py`, `app/generate_jwt_secret.py`
- **Auth + IAM**
  - `app/sign_up/email_verification.py`
  - `app/sign_up/signup.py`
  - `app/sign_up/login.py`
  - `app/sign_up/forgot.py`
  - `app/sign_up/employee_edit.py`
  - `app/sign_up/schemas.py`
  - `app/security/rbac.py`
  - `app/security/teams_api.py`
  - `app/security/team_scope.py`
- **Customer**
  - `app/customer_registration/customer.py`
  - `app/customer_registration/services.py`
  - `app/customer_registration/service_config.py`
  - `app/customer_registration/schemas.py`
  - `app/customer_registration/business_description_ai.py`
- **GST registration**
  - `app/gst_registration/gst_registration.py`
  - `app/gst_registration/gst_people.py`
  - `app/gst_registration/gst_documents.py`
  - `app/gst_registration/gst_blob.py`
  - `app/gst_registration/gst_registration_config.py`
  - `app/gst_registration/document_config.py`
  - `app/gst_registration/city_config.py`
  - `app/gst_registration/schemas.py`
- **GST filing**
  - `app/gst_registration_filing/gst_registation_filing.py`
  - `app/gst_registration_filing/gst_filing_document.py`
  - `app/gst_registration_filing/gst_filing_config.py`
  - `app/gst_registration_filing/schemas.py`
- **Payments**
  - `app/payments/registration_payments.py`
  - `app/payments/filing_payments.py`
  - `app/payments/payments_config.py`
  - `app/payments/schemas.py`
- **Followups + reporting + ops**
  - `app/follow_ups/gst_reg_manual_followups.py`
  - `app/follow_ups/gst_filing_manual_followups.py`
  - `app/Dashboard/dashboard.py`
  - `app/version/version.py`
  - `app/schedular/schedular.py`
