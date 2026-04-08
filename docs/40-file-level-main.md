# File-Level Doc: `app/main.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Application bootstrap entrypoint: FastAPI app initialization, middleware registration, router inclusion, and scheduler startup integration.

## Responsibilities

- Creates FastAPI application instance.
- Exposes health endpoint (`GET /health`).
- Mounts `TokenValidatorMiddleware` globally.
- Includes all domain routers under their own prefixes.
- Starts scheduler loop on startup when enabled by environment flags.

## Core integrations

- Auth middleware: `app/token_validator.py`
- Scheduler: `app/schedular/schedular.py`
- Routers from:
  - sign_up
  - security
  - customer_registration
  - gst_registration
  - gst_registration_filing
  - payments
  - follow_ups
  - dashboard
  - version

## Operational notes

- Router inclusion order matters for endpoint availability and startup stability.
- This file is the best location to verify complete API surface wiring.
