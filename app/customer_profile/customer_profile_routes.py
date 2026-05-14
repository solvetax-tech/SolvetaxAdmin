"""
Customer self-service API routes (signup, login, forgot password, profile).

- ``X-Public-Api-Key`` + rate limits on all paths.
- **Sessions:** short-lived **access** JWT + **refresh** token stored in ``customer_sessions``
  (see ``ddl_customer_sessions.sql``). Refresh has **no calendar expiry** until logout or password reset.
- Profile: **Bearer** access token or HTTP Basic.

Env: ``CUSTOMER_ACCESS_TOKEN_MINUTES`` (default 30) — only the access token rotates; the client should call
``POST /customer-profile/refresh`` when it receives ``ACCESS_TOKEN_EXPIRED``.
SMS / OTP storage: ``app/customer_profile/verify_customer_otp.py`` (``customer_otp_verify``) + ``CUSTOMER_FORGOT_OTP_EXPIRY_MINUTES``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.customer_registration.customer import (
    _insert_pending_customer_services_for_eligible_codes,
    _invalidate_customer_cache,
    _invalidate_customer_services_cache,
    _merge_service_required_with_existing,
    _service_required_minus_upper_codes,
    _sync_crm_leads_from_customer_service_required,
)
from app.logger import logger
from app.security.public_security import enforce_public_security
from app.customer_profile.customer_session import (
    create_customer_session,
    deactivate_all_sessions_for_customer,
    deactivate_session_by_jti,
    deactivate_session_by_refresh,
    load_customer_from_bearer,
    load_customer_from_bearer_for_update,
    rotate_refresh_token,
)
from app.customer_profile.verify_customer_otp import (
    OTP_PURPOSE_PASSWORD_RESET,
    generate_sms_otp,
    send_otp_sms,
)
from app.utils import (
    DB_SCHEMA,
    generate_uuid,
    get_db_pool,
    hash_password,
    is_password_strong,
    passwords_match,
    verify_password,
)

router = APIRouter(prefix="/app/v1", tags=["CustomerProfile"])

CUSTOMER_SIGNUP_FULL_NAME = "Customer"

# Forgot-password SMS OTP validity only (.env after deployment).
CUSTOMER_FORGOT_OTP_EXPIRY_MINUTES = int(os.getenv("CUSTOMER_FORGOT_OTP_EXPIRY_MINUTES", "10"))
FORGOT_OTP_COOLDOWN_SECONDS = 60
FORGOT_OTP_MAX_PER_WINDOW = 5
FORGOT_OTP_WINDOW_MINUTES = 10

_http_basic_optional = HTTPBasic(auto_error=False)


def _scrub_customer_row(row: asyncpg.Record) -> Dict[str, Any]:
    d = dict(row)
    d.pop("customer_password", None)
    return d


def _scrub_income_tax_row(row: asyncpg.Record) -> Dict[str, Any]:
    d = dict(row)
    d.pop("password", None)
    return d


def _basic_401() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials.",
        headers={"WWW-Authenticate": "Basic"},
    )


def _portal_auth_401() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Authentication required. Use access Bearer from login/signup, "
            "or HTTP Basic (mobile, password). If access expired, call POST /customer-profile/refresh."
        ),
        headers={"WWW-Authenticate": "Basic"},
    )


def _parse_mobile(mobile_raw: str) -> str:
    m = (mobile_raw or "").strip()
    if not m.isdigit() or len(m) != 10:
        raise HTTPException(status_code=400, detail="Mobile must be exactly 10 digits.")
    return m


async def _fetch_customer_basic_auth(
    conn: asyncpg.Connection,
    mobile_raw: str,
    password: str,
    log: logging.LoggerAdapter,
    *,
    for_update: bool = False,
) -> asyncpg.Record:
    q_suffix = "FOR UPDATE LIMIT 1" if for_update else "LIMIT 1"
    try:
        customer = await conn.fetchrow(
            f"""
            SELECT *
              FROM {DB_SCHEMA}.customers
             WHERE trim(mobile) = trim($1::text)
               AND is_active = TRUE
             {q_suffix}
            """,
            mobile_raw,
        )
    except asyncpg.UndefinedColumnError:
        log.error(
            "customers.customer_password column missing; run ddl_customers_customer_password.sql",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer portal is not configured.",
        )
    except asyncpg.PostgresError:
        log.exception("customer portal fetch failed")
        raise HTTPException(status_code=500, detail="Database error.")

    if not customer:
        raise _basic_401()

    stored = customer.get("customer_password")
    if not stored or not str(stored).strip():
        raise _basic_401()

    if not verify_password(password, str(stored)):
        raise _basic_401()

    return customer


async def _resolve_customer_row(
    request: Request,
    conn: asyncpg.Connection,
    log: logging.LoggerAdapter,
    *,
    basic_creds: Optional[HTTPBasicCredentials],
    for_update: bool,
) -> asyncpg.Record:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
        try:
            if for_update:
                return await load_customer_from_bearer_for_update(conn, token)
            return await load_customer_from_bearer(conn, token)
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("customer bearer resolve failed")
            raise HTTPException(status_code=500, detail="Database error.")

    if basic_creds is None:
        raise _portal_auth_401()

    mobile_raw = _parse_mobile(basic_creds.username or "")
    password = basic_creds.password or ""
    return await _fetch_customer_basic_auth(
        conn, mobile_raw, password, log, for_update=for_update
    )


def _normalize_incoming_services(values: List[str]) -> List[str]:
    if not isinstance(values, list):
        raise HTTPException(
            status_code=400,
            detail="service_required must be a list of strings.",
        )
    cleaned: List[str] = []
    for v in values:
        if not isinstance(v, str):
            raise HTTPException(
                status_code=400,
                detail="Each service code must be a string.",
            )
        t = v.strip()
        if t:
            cleaned.append(t)
    return list(dict.fromkeys(cleaned))


# --- Pydantic ---


class CustomerSignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mobile: str = Field(..., min_length=10, max_length=10)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("mobile")
    @classmethod
    def v_mobile(cls, v: str) -> str:
        m = v.strip()
        if not m.isdigit() or len(m) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return m


class CustomerLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mobile: str = Field(..., min_length=10, max_length=10)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("mobile")
    @classmethod
    def v_mobile(cls, v: str) -> str:
        m = v.strip()
        if not m.isdigit() or len(m) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return m


class CustomerRefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    refresh_token: str = Field(..., min_length=16, max_length=2048)


class CustomerLogoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    refresh_token: Optional[str] = Field(None, max_length=2048)


class CustomerForgotRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mobile: str = Field(..., min_length=10, max_length=10)

    @field_validator("mobile")
    @classmethod
    def v_mobile(cls, v: str) -> str:
        m = v.strip()
        if not m.isdigit() or len(m) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return m


class CustomerForgotVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mobile: str
    otp: str = Field(..., min_length=4, max_length=16)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("mobile")
    @classmethod
    def v_mobile(cls, v: str) -> str:
        m = v.strip()
        if not m.isdigit() or len(m) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return m


class CustomerPortalServiceAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    service_required: List[str] = Field(..., min_length=1)

    @field_validator("service_required", mode="before")
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            raise ValueError("service_required is required.")
        return v


# --- Signup / login / forgot ---


@router.post(
    "/customer-profile/signup",
    summary="Customer signup (mobile + password)",
    status_code=status.HTTP_201_CREATED,
)
async def customer_signup(request: Request, payload: CustomerSignupIn = Body(...)):
    await enforce_public_security(
        request=request,
        bucket="public:customer_signup",
        max_requests=10,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_signup"})
    if not is_password_strong(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters and include upper, lower, digit, and special character.",
        )

    mobile = payload.mobile.strip()
    pw_hash = hash_password(payload.password)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    f"""
                    SELECT customer_id
                      FROM {DB_SCHEMA}.customers
                     WHERE trim(mobile) = trim($1::text)
                     LIMIT 1
                    """,
                    mobile,
                )
                if existing:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "MOBILE_EXISTS",
                            "message": "An account with this mobile already exists. Use login.",
                        },
                    )

                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customers (
                        full_name, email, mobile, customer_password,
                        service_required, is_active, created_at, updated_at
                    )
                    VALUES ($1, NULL, $2, $3, ARRAY[]::text[], TRUE, NOW(), NOW())
                    RETURNING *
                    """,
                    CUSTOMER_SIGNUP_FULL_NAME,
                    mobile,
                    pw_hash,
                )
                access_token, refresh_token, expires_in = await create_customer_session(
                    conn,
                    customer_id=row["customer_id"],
                    mobile=mobile,
                    request=request,
                )
        except HTTPException:
            raise
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MOBILE_EXISTS",
                    "message": "An account with this mobile already exists. Use login.",
                },
            )
        except asyncpg.UndefinedColumnError:
            log.error("customer_password column missing")
            raise HTTPException(status_code=503, detail="Customer portal is not configured.")
        except asyncpg.PostgresError:
            log.exception("customer signup failed")
            raise HTTPException(status_code=500, detail="Database error.")

    log.info("Customer signup ok | customer_id=%s", row["customer_id"])
    return {
        "request_id": request_id,
        "message": "Account created.",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": "bearer",
        "customer": _scrub_customer_row(row),
    }


@router.post("/customer-profile/login", summary="Customer login (mobile + password)")
async def customer_login(request: Request, payload: CustomerLoginIn = Body(...)):
    await enforce_public_security(
        request=request,
        bucket="public:customer_login",
        max_requests=20,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_login"})
    mobile = payload.mobile.strip()

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        try:
            customer = await conn.fetchrow(
                f"""
                SELECT *
                  FROM {DB_SCHEMA}.customers
                 WHERE trim(mobile) = trim($1::text)
                   AND is_active = TRUE
                 LIMIT 1
                """,
                mobile,
            )
        except asyncpg.UndefinedColumnError:
            raise HTTPException(status_code=503, detail="Customer portal is not configured.")
        except asyncpg.PostgresError:
            log.exception("customer login failed")
            raise HTTPException(status_code=500, detail="Database error.")

        if not customer:
            raise HTTPException(status_code=401, detail="Invalid mobile or password.")

        stored = customer.get("customer_password")
        if not stored or not verify_password(payload.password, str(stored)):
            raise HTTPException(status_code=401, detail="Invalid mobile or password.")

        try:
            access_token, refresh_token, expires_in = await create_customer_session(
                conn,
                customer_id=customer["customer_id"],
                mobile=mobile,
                request=request,
            )
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("customer login session failed")
            raise HTTPException(status_code=500, detail="Database error.")

    log.info("Customer login ok | customer_id=%s", customer["customer_id"])
    return {
        "request_id": request_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": "bearer",
        "customer": _scrub_customer_row(customer),
    }


@router.post("/customer-profile/refresh", summary="Rotate refresh token and issue new access token")
async def customer_refresh(request: Request, payload: CustomerRefreshIn = Body(...)):
    await enforce_public_security(
        request=request,
        bucket="public:customer_refresh",
        max_requests=60,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_refresh"})
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                access_token, refresh_token, expires_in, customer_id = await rotate_refresh_token(
                    conn,
                    raw_refresh=payload.refresh_token,
                    request=request,
                )
                cust = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                       AND is_active = TRUE
                     LIMIT 1
                    """,
                    customer_id,
                )
        except HTTPException:
            raise
        except asyncpg.UndefinedTableError:
            raise HTTPException(
                status_code=503,
                detail="Customer sessions are not configured (run ddl_customer_sessions.sql).",
            )
        except asyncpg.PostgresError:
            log.exception("customer refresh failed")
            raise HTTPException(status_code=500, detail="Database error.")

    if not cust:
        raise HTTPException(status_code=401, detail="Account not found or inactive.")

    return {
        "request_id": request_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": "bearer",
        "customer": _scrub_customer_row(cust),
    }


@router.post("/customer-profile/logout", summary="End customer session (Bearer access and/or refresh_token body)")
async def customer_logout(request: Request, payload: CustomerLogoutIn = Body(default_factory=CustomerLogoutIn)):
    await enforce_public_security(
        request=request,
        bucket="public:customer_logout",
        max_requests=30,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_logout"})
    auth = (request.headers.get("Authorization") or "").strip()
    bearer_ok = False
    refresh_ok = False
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1].strip()
            if token:
                try:
                    bearer_ok = await deactivate_session_by_jti(conn, token)
                except asyncpg.PostgresError:
                    log.exception("customer logout bearer failed")
                    raise HTTPException(status_code=500, detail="Database error.")
        rt = (payload.refresh_token or "").strip()
        if rt:
            try:
                refresh_ok = await deactivate_session_by_refresh(conn, rt)
            except asyncpg.PostgresError:
                log.exception("customer logout refresh failed")
                raise HTTPException(status_code=500, detail="Database error.")

    if not bearer_ok and not refresh_ok:
        raise HTTPException(
            status_code=401,
            detail="Could not end session. Invalid token, or session already ended.",
        )
    return {"request_id": request_id, "message": "Logged out."}


@router.post("/customer-profile/forgot-password/request", summary="Request OTP to reset customer password")
async def customer_forgot_password_request(
    request: Request,
    payload: CustomerForgotRequestIn = Body(...),
):
    await enforce_public_security(
        request=request,
        bucket="public:customer_forgot_request",
        max_requests=10,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_forgot_req"})
    mobile = payload.mobile.strip()

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        customer = await conn.fetchrow(
            f"""
            SELECT customer_id
              FROM {DB_SCHEMA}.customers
             WHERE trim(mobile) = trim($1::text)
               AND is_active = TRUE
             LIMIT 1
            """,
            mobile,
        )
        if not customer:
            raise HTTPException(status_code=404, detail="No active account found for this mobile.")

        pwd = await conn.fetchval(
            f"""
            SELECT customer_password
              FROM {DB_SCHEMA}.customers
             WHERE customer_id = $1
            """,
            customer["customer_id"],
        )
        if not pwd or not str(pwd).strip():
            raise HTTPException(status_code=400, detail="Password is not set for this account. Complete signup first.")

        try:
            last_otp = await conn.fetchrow(
                f"""
                SELECT created_at
                  FROM {DB_SCHEMA}.customer_otp_verify
                 WHERE trim(mobile) = trim($1::text)
                   AND otp_purpose = $2
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                mobile,
                OTP_PURPOSE_PASSWORD_RESET,
            )
        except asyncpg.UndefinedTableError:
            log.error("customer_otp_verify table missing")
            raise HTTPException(status_code=503, detail="Forgot password is not configured.")
        except asyncpg.UndefinedColumnError:
            log.error("Run app/customer_profile/ddl_customer_otp_verify_migrate.sql (otp_purpose column).")
            raise HTTPException(status_code=503, detail="Forgot password storage needs migration.")

        now_utc = datetime.now(timezone.utc)
        if last_otp:
            if (now_utc - last_otp["created_at"]).total_seconds() < FORGOT_OTP_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {FORGOT_OTP_COOLDOWN_SECONDS} seconds before requesting another OTP.",
                )

        otp_count = await conn.fetchval(
            f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.customer_otp_verify
             WHERE trim(mobile) = trim($1::text)
               AND otp_purpose = $2
               AND created_at > NOW() - ($3::text)::interval
            """,
            mobile,
            OTP_PURPOSE_PASSWORD_RESET,
            f"{FORGOT_OTP_WINDOW_MINUTES} minutes",
        )
        if (otp_count or 0) >= FORGOT_OTP_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=429,
                detail="Too many OTP requests. Try again later.",
            )

        otp = generate_sms_otp()
        expires_at = now_utc + timedelta(minutes=CUSTOMER_FORGOT_OTP_EXPIRY_MINUTES)

        await send_otp_sms(mobile, otp)

        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_otp_verify
               SET is_active = FALSE
             WHERE trim(mobile) = trim($1::text)
               AND otp_purpose = $2
               AND is_active = TRUE
            """,
            mobile,
            OTP_PURPOSE_PASSWORD_RESET,
        )
        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.customer_otp_verify
                (mobile, otp, is_verified, is_active, created_at, expires_at, otp_purpose)
            VALUES ($1, $2, FALSE, TRUE, NOW(), $3, $4)
            """,
            mobile,
            otp,
            expires_at,
            OTP_PURPOSE_PASSWORD_RESET,
        )

    log.info("Customer forgot OTP sent | mobile=%s", mobile[:3] + "******")
    return {
        "request_id": request_id,
        "message": "OTP sent to your mobile.",
        "expires_at": expires_at,
    }


@router.post("/customer-profile/forgot-password/verify", summary="Verify OTP and set new customer password")
async def customer_forgot_password_verify(
    request: Request,
    payload: CustomerForgotVerifyIn = Body(...),
):
    await enforce_public_security(
        request=request,
        bucket="public:customer_forgot_verify",
        max_requests=15,
        window_seconds=60,
        block_seconds=300,
    )
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_forgot_verify"})
    mobile = payload.mobile.strip()
    otp = payload.otp.strip()

    if not passwords_match(payload.new_password, payload.confirm_password):
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    if not is_password_strong(payload.new_password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters and include upper, lower, digit, and special character.",
        )

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await conn.fetchrow(
                    f"""
                    SELECT id, otp, expires_at, is_active, is_verified
                      FROM {DB_SCHEMA}.customer_otp_verify
                     WHERE trim(mobile) = trim($1::text)
                       AND otp = $2
                       AND otp_purpose = $3
                       AND is_active = TRUE
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    mobile,
                    otp,
                    OTP_PURPOSE_PASSWORD_RESET,
                )
            except asyncpg.UndefinedTableError:
                raise HTTPException(status_code=503, detail="Forgot password is not configured.")
            except asyncpg.UndefinedColumnError:
                log.error("Run app/customer_profile/ddl_customer_otp_verify_migrate.sql (otp_purpose column).")
                raise HTTPException(status_code=503, detail="Forgot password storage needs migration.")

            if not row:
                raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

            if row.get("is_verified"):
                raise HTTPException(status_code=400, detail="OTP already used.")

            now_utc = datetime.now(timezone.utc)
            if row["expires_at"] and row["expires_at"] < now_utc:
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_otp_verify
                       SET is_active = FALSE
                     WHERE id = $1
                    """,
                    row["id"],
                )
                raise HTTPException(status_code=400, detail="OTP expired. Request a new one.")

            cust = await conn.fetchrow(
                f"""
                SELECT customer_id
                  FROM {DB_SCHEMA}.customers
                 WHERE trim(mobile) = trim($1::text)
                   AND is_active = TRUE
                 LIMIT 1
                """,
                mobile,
            )
            if not cust:
                raise HTTPException(status_code=404, detail="Account not found.")

            pw_hash = hash_password(payload.new_password)
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.customers
                   SET customer_password = $2,
                       updated_at = NOW()
                 WHERE customer_id = $1
                """,
                cust["customer_id"],
                pw_hash,
            )
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.customer_otp_verify
                   SET is_active = FALSE
                 WHERE trim(mobile) = trim($1::text)
                   AND otp_purpose = $2
                """,
                mobile,
                OTP_PURPOSE_PASSWORD_RESET,
            )
            await deactivate_all_sessions_for_customer(conn, cust["customer_id"])

    await _invalidate_customer_cache(cust["customer_id"])
    log.info("Customer password reset | customer_id=%s", cust["customer_id"])
    return {"request_id": request_id, "message": "Password updated. You can log in now."}


# --- Profile GET / PATCH ---


@router.get(
    "/customer-profile",
    summary="Customer profile (JWT Bearer or HTTP Basic + public API key)",
)
async def get_customer_profile(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(_http_basic_optional),
):
    await enforce_public_security(
        request=request,
        bucket="public:customer_profile",
        max_requests=30,
        window_seconds=60,
        block_seconds=300,
    )

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-", "api": "customer_profile"})

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        customer = await _resolve_customer_row(
            request, conn, log, basic_creds=credentials, for_update=False
        )
        mobile_raw = (customer.get("mobile") or "").strip()

        try:
            gst_registrations = await conn.fetch(
                f"""
                SELECT g.*
                  FROM {DB_SCHEMA}.gst_registration g
                 WHERE g.is_active = TRUE
                   AND (
                        trim(coalesce(g.mobile, '')) = trim($1::text)
                        OR EXISTS (
                           SELECT 1
                             FROM {DB_SCHEMA}.customers c
                            WHERE c.customer_id = g.customer_id
                              AND c.is_active = TRUE
                              AND trim(c.mobile) = trim($1::text)
                        )
                   )
                 ORDER BY g.id DESC
                """,
                mobile_raw,
            )

            gst_people = await conn.fetch(
                f"""
                SELECT DISTINCT p.*
                  FROM {DB_SCHEMA}.gst_registration_persons p
                 WHERE p.is_active = TRUE
                   AND (
                        trim(coalesce(p.mobile, '')) = trim($1::text)
                        OR EXISTS (
                           SELECT 1
                             FROM {DB_SCHEMA}.customers c
                            WHERE c.customer_id = p.customer_id
                              AND c.is_active = TRUE
                              AND trim(c.mobile) = trim($1::text)
                        )
                        OR EXISTS (
                           SELECT 1
                             FROM {DB_SCHEMA}.gst_registration g
                            WHERE g.id = p.gst_registration_id
                              AND g.is_active = TRUE
                              AND trim(coalesce(g.mobile, '')) = trim($1::text)
                        )
                        OR EXISTS (
                           SELECT 1
                             FROM {DB_SCHEMA}.gst_registration g
                             JOIN {DB_SCHEMA}.customers c
                               ON c.customer_id = g.customer_id
                            WHERE g.id = p.gst_registration_id
                              AND g.is_active = TRUE
                              AND c.is_active = TRUE
                              AND trim(c.mobile) = trim($1::text)
                        )
                   )
                 ORDER BY p.person_id DESC
                """,
                mobile_raw,
            )

            income_tax_rows = await conn.fetch(
                f"""
                SELECT *
                  FROM {DB_SCHEMA}.income_tax
                 WHERE is_active = TRUE
                   AND trim(mobile) = trim($1::text)
                 ORDER BY id DESC
                """,
                mobile_raw,
            )

            gst_filings = await conn.fetch(
                f"""
                SELECT f.*
                  FROM {DB_SCHEMA}.gst_filings f
                  JOIN {DB_SCHEMA}.customers c
                    ON c.customer_id = f.customer_id
                 WHERE f.is_active = TRUE
                   AND c.is_active = TRUE
                   AND trim(c.mobile) = trim($1::text)
                 ORDER BY f.created_at DESC
                """,
                mobile_raw,
            )

            customer_services = await conn.fetch(
                f"""
                SELECT cs.*,
                       sc.service_code AS service_code,
                       sc.service_name AS service_name
                  FROM {DB_SCHEMA}.customer_services cs
                  JOIN {DB_SCHEMA}.customers c
                    ON c.customer_id = cs.customer_id
                  LEFT JOIN {DB_SCHEMA}.service_config sc
                    ON sc.id = cs.service_id
                 WHERE c.is_active = TRUE
                   AND trim(c.mobile) = trim($1::text)
                 ORDER BY cs.id DESC
                """,
                mobile_raw,
            )
        except asyncpg.UndefinedTableError as e:
            log.warning("Optional table missing for customer profile | %s", e)
            raise HTTPException(
                status_code=503,
                detail="Profile dependencies are not fully available.",
            )
        except asyncpg.PostgresError:
            log.exception("customer profile related fetch failed")
            raise HTTPException(status_code=500, detail="Database error.")

    return {
        "request_id": request_id,
        "customer": _scrub_customer_row(customer),
        "gst_registrations": [dict(r) for r in gst_registrations],
        "gst_registration_persons": [dict(r) for r in gst_people],
        "income_tax": [_scrub_income_tax_row(r) for r in income_tax_rows],
        "gst_filings": [dict(r) for r in gst_filings],
        "customer_services": [dict(r) for r in customer_services],
    }


@router.patch(
    "/customer-profile",
    summary="Append service_required (JWT Bearer or HTTP Basic + public API key)",
)
async def patch_customer_profile_services(
    request: Request,
    body: CustomerPortalServiceAddIn = Body(...),
    credentials: Optional[HTTPBasicCredentials] = Depends(_http_basic_optional),
):
    await enforce_public_security(
        request=request,
        bucket="public:customer_profile_patch",
        max_requests=30,
        window_seconds=60,
        block_seconds=300,
    )

    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "customer_profile_patch"},
    )

    incoming = _normalize_incoming_services(body.service_required)
    if not incoming:
        raise HTTPException(status_code=400, detail="At least one service code is required.")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    pending_svcs_created = 0
    customer_id: int
    customer_row: asyncpg.Record

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                customer = await _resolve_customer_row(
                    request, conn, log, basic_creds=credentials, for_update=True
                )
                customer_id = customer["customer_id"]

                existing_sr = customer["service_required"]
                if existing_sr is None:
                    existing_list: List[str] = []
                elif isinstance(existing_sr, list):
                    existing_list = list(existing_sr)
                else:
                    existing_list = list(existing_sr)

                merged = _merge_service_required_with_existing(existing_list, incoming)

                customer_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET service_required = $2,
                           updated_at = NOW()
                     WHERE customer_id = $1
                     RETURNING *
                    """,
                    customer_id,
                    merged,
                )

                if not customer_row:
                    raise HTTPException(status_code=500, detail="Customer update failed.")

                service_codes_upper = [
                    s.strip().upper()
                    for s in merged
                    if isinstance(s, str) and s.strip()
                ]

                crm_strip_upper = await _sync_crm_leads_from_customer_service_required(
                    conn,
                    customer_row,
                    service_codes_upper,
                    tag=customer_row.get("tag"),
                    lead_source=customer_row.get("lead_source"),
                    lead_type=customer_row.get("lead_type"),
                )
                if crm_strip_upper:
                    new_sr = _service_required_minus_upper_codes(merged, crm_strip_upper)
                    customer_row = await conn.fetchrow(
                        f"""
                        UPDATE {DB_SCHEMA}.customers
                           SET service_required = $2,
                               updated_at = NOW()
                         WHERE customer_id = $1
                         RETURNING *
                        """,
                        customer_id,
                        new_sr,
                    )
                    if not customer_row:
                        log.error(
                            "Profile patch: service_required strip failed | customer_id=%s",
                            customer_id,
                        )
                        raise HTTPException(status_code=500, detail="Customer update failed.")

                pending_svcs_created = await _insert_pending_customer_services_for_eligible_codes(
                    conn,
                    customer_id,
                    service_codes_upper,
                    customer_row.get("rm_id"),
                    customer_row.get("op_id"),
                )

        except HTTPException:
            raise
        except asyncpg.UndefinedColumnError:
            log.error("customer_password column missing")
            raise HTTPException(status_code=503, detail="Customer portal is not configured.")
        except asyncpg.PostgresError:
            log.exception("customer profile patch failed")
            raise HTTPException(status_code=500, detail="Database error.")

    if pending_svcs_created > 0:
        await _invalidate_customer_services_cache()

    await _invalidate_customer_cache(customer_id)

    log.info(
        "Customer profile services patched | customer_id=%s pending_svcs=%s",
        customer_id,
        pending_svcs_created,
    )

    return {
        "request_id": request_id,
        "message": "service_required updated.",
        "customer": _scrub_customer_row(customer_row),
        "pending_customer_services_created": pending_svcs_created,
    }
