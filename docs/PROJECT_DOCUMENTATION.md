# SolveTax Backend Documentation

## 1) Project Overview

This repository contains the backend API for SolveTax, built with FastAPI and PostgreSQL (`asyncpg`), with Azure Blob support for document storage.

Primary business domains:
- Employee onboarding and authentication
- Role/permission-based access control
- Customer registration and service lifecycle
- GST registration lifecycle
- GST filing lifecycle (including return-detail rows and automated recurrence scheduling)
- Payments (registration + filing)
- Follow-ups (manual + scheduler-driven missed marking)
- Dashboard metrics and version history audit


## 2) Runtime and Stack

- Language: Python
- API framework: FastAPI
- DB client: `asyncpg`
- File storage: Azure Blob Storage
- Auth: JWT + DB-backed session token validation middleware
- Scheduler: in-process async task (`asyncio`) started on app startup


## 3) Project Structure

```text
slovetax/
  app/
    main.py
    utils.py
    logger.py
    token_validator.py
    security/
    sign_up/
    customer_registration/
    gst_registration/
    gst_registration_filing/
    payments/
    follow_ups/
    Dashboard/
    version/
    schedular/
  docs/
    PROJECT_DOCUMENTATION.md
```


## 4) App Startup, Shutdown, and Request Flow

### Startup (`app/main.py`)
- Loads env (`load_dotenv`).
- Creates FastAPI app.
- Initializes DB pool once per process via `get_db_pool()`.
- Starts scheduler with `start_scheduler_if_enabled()` if `RUN_SCHEDULER=true`.
- Registers middleware:
  - `TokenValidatorMiddleware`
  - CORS
- Injects bearer-auth OpenAPI security schema.
- Includes all configured routers.

### Shutdown (`app/main.py`)
- Stops scheduler task (`stop_scheduler()`).
- Closes shared DB pool (`close_db_pool()`).

### Auth/Authorization flow
1. Middleware validates JWT and active session token (DB check) for non-public paths.
2. Route-level `Depends(require_permission(...))` verifies feature-level permissions from token payload.
3. Business logic executes SQL operations and returns payload.


## 5) Shared Infrastructure Files

## `app/utils.py`
Core shared utilities:
- DB pool lifecycle (`get_db_pool`, `close_db_pool`)
- `DB_SCHEMA` env wiring
- UUID generation
- Password hashing/verification helpers
- Role visibility SQL builders:
  - `build_customer_visibility`
  - `build_gst_visibility`
  - `build_gst_filing_visibility`
  - `build_customer_service_visibility`
- Azure Blob helpers (SAS generation, path extraction)

### Design notes
- Uses singleton asyncpg pool with lock for thread-safe lazy init.
- Uses schema-qualified SQL (`{DB_SCHEMA}.table`) across modules.

## `app/token_validator.py`
Global middleware:
- Verifies bearer token
- Validates active session row in DB
- Validates employee is active
- Rejects expired/inactive sessions
- Allows public paths for docs/health/login/forgot-password endpoints

## `app/security/rbac.py`
Permission dependency:
- `require_permission(feature_code, permission_code)`
- Validates platform permissions from JWT claims
- WRITE implies READ for same feature

## `app/logger.py`
Central logger configuration:
- Rotating file + console handlers
- Request/employee context support in structured logs


## 6) Domain Modules and File Guide

## A) Authentication and Employee Management

### `app/sign_up/signup.py`
- Employee signup create flow

### `app/sign_up/login.py`
- Login endpoint
- Refresh token endpoint
- Logout endpoint (session invalidation)

### `app/sign_up/email_verification.py`
- OTP request and verification for email verification

### `app/sign_up/forgot.py`
- Forgot-password OTP request/verify/reset flow

### `app/sign_up/employee_edit.py`
- Employee dynamic edit
- Employee filter/get APIs
- Active RM/OP manager listing endpoints
- Soft delete and role operations
- Password change endpoint

### `app/security/teams_api.py`
- Team CRUD and team membership assignment APIs

### `app/security/team_scope.py`
- Team-level access filters/scoping helpers


## B) Customer Domain

### `app/customer_registration/customer.py`
- Customer create/read/filter/edit
- Soft delete and activate flows
- Related business validation and audit logging (`versions`)

### `app/customer_registration/services.py`
- Customer service lifecycle APIs
- Service activation/deactivation
- Pending service list and dashboard stats

### `app/customer_registration/service_config.py`
- Service configuration dropdown/list APIs


## C) GST Registration Domain

### `app/gst_registration/gst_registration.py`
- GST registration create/filter/edit/deactivate/activate
- Customer-services sync in state transitions

### `app/gst_registration/gst_people.py`
- GST person create/filter/edit/deactivate/activate
- Ownership/designation support endpoint

### `app/gst_registration/gst_documents.py`
- GST registration document create/filter/edit/deactivate/activate

### `app/gst_registration/gst_blob.py`
- Azure Blob upload/view/download helpers for GST files

### `app/gst_registration/gst_registration_config.py`
- GST registration config lookup APIs

### `app/gst_registration/document_config.py`
- Required document and document-config APIs


## D) GST Filing Domain

### `app/gst_registration_filing/schemas.py`
Pydantic request/response models and validations:
- Filing create/edit payloads
- Return-status update payloads
- Filing document payloads

### `app/gst_registration_filing/gst_registation_filing.py`
Main GST filing APIs:
- Filing create/filter/edit/deactivate/activate
- Return status update

Key logic implemented:
- Manual first-time filing creation inserts return-detail rows with:
  - `is_auto_generated = False`
  - `next_auto_generate_at` computed from due dates and lead days
- Applicable return rows by taxpayer type:
  - REGULAR:
    - Row 1: GSTR1/GSTR3B
    - Row 2: GSTR9 (+ GSTR9C if turnover > 5CR)
  - COMPOSITION:
    - Row 1: CMP08
    - Row 2: GSTR4
- New lead-day policy:
  - Monthly rows: 10 days
  - Quarterly rows (incl CMP08 cadence): 12 days
  - Annual/yearly rows: 7 days

### `app/gst_registration_filing/gst_filing_config.py`
- Filing config filter APIs

### `app/gst_registration_filing/gst_filing_document.py`
- Filing document CRUD/filter APIs
- Note: ensure router is mounted in `main.py` if endpoints are expected live


## E) Payments Domain

### `app/payments/registration_payments.py`
- Registration payment create/filter/deactivate/activate

### `app/payments/filing_payments.py`
- Filing payment create/filter/deactivate/activate

### `app/payments/payments_config.py`
- Payment config lookup and amount calculation endpoints

### `app/payments/schemas.py`
- Payment payload and validation schemas


## F) Follow-up Domain

### `app/follow_ups/gst_reg_manual_followups.py`
- Manual follow-up APIs for customer service/GST registration flow

### `app/follow_ups/gst_filing_manual_followups.py`
- Manual follow-up APIs for GST filing flow


## G) Dashboard and Audit

### `app/Dashboard/dashboard.py`
- Dashboard metrics endpoints (employees/customers/payments and related KPIs)

### `app/version/version.py`
- Version/audit log filter endpoint
- Reads from `versions` table to track entity changes over time


## H) Scheduler

### `app/schedular/schedular.py`
Runs every 60 seconds:
1. Marks overdue pending follow-ups as MISSED
2. Deactivates expired session tokens
3. Auto-generates future `gst_filing_return_details` rows when `next_auto_generate_at <= NOW()`

GST auto-generation behavior:
- Processes only when:
  - parent filing `is_auto_enabled = TRUE`
  - parent and detail row `is_active = TRUE`
  - current detail has due `next_auto_generate_at`
- Uses `FOR UPDATE SKIP LOCKED` to avoid duplicate processing in concurrent workers
- Inserts new row with:
  - shifted due dates by cadence
  - `is_auto_generated = TRUE`
  - recalculated `next_auto_generate_at` by cadence-specific lead days
- Marks source row processed by setting its `next_auto_generate_at = NULL`


## 7) Database Interaction Patterns

Common patterns used throughout modules:
- Schema-qualified SQL (`{DB_SCHEMA}.table`)
- `async with conn.transaction()` for multi-step consistency
- Soft delete via `is_active = FALSE`
- Re-activate via `is_active = TRUE`
- Version audit writes to `versions` table for create/update/delete/activate
- Role-based visibility restrictions through reusable SQL builders
- Frequent `FOR UPDATE` locks for safe edits/deletes and race prevention


## 8) Security and Access Model

- Middleware enforces JWT + active session token for protected routes
- RBAC feature permissions enforced with `require_permission(...)`
- Team-based scoping is applied in visibility SQL builders
- Public routes are intentionally limited to docs/health/auth recovery paths


## 9) Configuration (Environment)

Expected key env variables include:
- DB: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SCHEMA`
- Pool/app: `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `APP_NAME`
- API runtime: `HOST`, `PORT`, `WORKERS`
- Scheduler: `RUN_SCHEDULER`
- Azure blob: storage connection/container variables used by `utils.py`


## 10) Current Operational Notes

- Scheduler folder/module is named `schedular` (project naming kept as-is).
- DB pool is per-process; total DB connections scale with worker count.
- If filing document router endpoints are needed, verify `gst_filing_document` router inclusion in `main.py`.
- Some APIs are strict about active-state checks and will reject updates on inactive parent records.


## 11) Suggested Next Documentation Enhancements

To make this doc production-ready for onboarding, add:
- ER diagram and table-by-table DDL reference
- Sequence diagrams for:
  - Login + token/session validation
  - Customer/GST/GST-filing lifecycle
  - Scheduler auto-generation lifecycle
- Postman/OpenAPI examples per domain
- Error code matrix by endpoint family


## 12) Quick Start (Developer)

1. Set required env vars in `.env`.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run service:
   - `python -m app.main`
4. Open docs:
   - `/docs`
5. Verify health:
   - `/health`

