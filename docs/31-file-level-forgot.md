# File-Level Doc: `app/sign_up/forgot.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Implements forgot-password OTP request and verify/reset flows.

## Router

- Prefix: `/app/v1`
- Tag: `ForgotPassword`

## Endpoints in this file

- `POST /app/v1/forgot-password/request`
- `POST /app/v1/forgot-password/verify`

## Permission usage

- Public auth flow endpoints (no bearer permission dependency).

## Core behaviors

- Request endpoint:
  - validates account existence.
  - applies OTP cooldown/rate controls.
  - creates or updates OTP record for password reset use.
- Verify endpoint:
  - validates OTP correctness and expiry.
  - updates employee password hash on success.
  - marks OTP as used/consumed.

## Main tables touched

- `password_reset_otps`
- `employees`
