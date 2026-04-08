# File-Level Doc: `app/sign_up/email_verification.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Handles signup email verification lifecycle through OTP request and OTP verification.

## Router

- Prefix: `/app/v1`
- Tag: `EmailVerification`

## Endpoints in this file

- `POST /app/v1/email-verification/request`
- `POST /app/v1/email-verification/verify`

## Permission usage

- Public onboarding endpoints.

## Core behaviors

- Request endpoint:
  - validates uniqueness/eligibility for signup verification.
  - enforces resend throttling.
  - stores/updates verification OTP record.
- Verify endpoint:
  - checks OTP validity and expiry.
  - marks verification as complete and prevents OTP replay.

## Main tables touched

- `employee_email_verifications`
- `employees` (existence/uniqueness checks)
