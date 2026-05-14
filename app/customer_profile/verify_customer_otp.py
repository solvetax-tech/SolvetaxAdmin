"""
Customer OTP: MSG91 SMS + ``customer_otp_verify`` storage.

- Public routes: ``POST /app/v1/customer-otp/request`` and ``POST /app/v1/customer-otp/verify`` (purpose ``customer``).
- Forgot-password uses the same table with ``otp_purpose = 'password_reset'`` (see ``customer_profile_routes``).

Run ``app/customer_profile/ddl_customer_otp_verify_migrate.sql`` once (rename + ``otp_purpose``).

Env (deployment): ``MSG91_AUTH_KEY``, ``MSG91_TEMPLATE_ID``, optional ``MSG91_COUNTRY_CODE``, ``MSG91_TIMEOUT_SECONDS``, ``MSG91_SEND_URL``.
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.logger import logger
from app.security.public_security import enforce_public_security
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

# --- MSG91 ---

MSG91_SEND_URL = (os.getenv("MSG91_SEND_URL") or "https://control.msg91.com/api/v5/otp").strip()


def get_msg91_config() -> dict:
    return {
        "auth_key_set": bool((os.getenv("MSG91_AUTH_KEY") or "").strip()),
        "template_id_set": bool((os.getenv("MSG91_TEMPLATE_ID") or "").strip()),
        "country_code": (os.getenv("MSG91_COUNTRY_CODE") or "91").strip(),
        "timeout_seconds": float(os.getenv("MSG91_TIMEOUT_SECONDS", "10")),
        "send_url": MSG91_SEND_URL,
    }


def generate_sms_otp() -> str:
    return f"{random.randint(100000, 999999)}"


async def send_otp_sms(mobile: str, otp: str) -> None:
    cfg = get_msg91_config()
    auth_key = (os.getenv("MSG91_AUTH_KEY") or "").strip()
    template_id = (os.getenv("MSG91_TEMPLATE_ID") or "").strip()
    country_code = cfg["country_code"]
    timeout_seconds = cfg["timeout_seconds"]

    if not auth_key or not template_id:
        raise HTTPException(
            status_code=503,
            detail="SMS provider is not configured (MSG91_AUTH_KEY / MSG91_TEMPLATE_ID).",
        )

    payload = {
        "mobile": f"{country_code}{mobile}",
        "otp": otp,
        "template_id": template_id,
    }
    headers = {
        "authkey": auth_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(MSG91_SEND_URL, json=payload, headers=headers)
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail="Failed to send OTP via SMS service. Please try again.",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect OTP SMS service. Please try again.",
        )


# --- OTP table purposes ---

OTP_PURPOSE_CUSTOMER = "customer"
OTP_PURPOSE_PASSWORD_RESET = "password_reset"

router = APIRouter(prefix="/app/v1", tags=["CustomerOtp"])

OTP_EXPIRY_MINUTES = 2
OTP_RESEND_COOLDOWN_SECONDS = 30
OTP_MAX_PER_WINDOW = 5
OTP_WINDOW_MINUTES = 10


class RequestCustomerOtpIn(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=10, description="10-digit mobile number")

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        mobile = value.strip()
        if not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return mobile


class RequestCustomerOtpOut(BaseModel):
    message: str
    mobile: str
    expires_at: datetime


class VerifyCustomerOtpIn(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=10, description="10-digit mobile number")
    otp: str = Field(..., min_length=4, max_length=8, description="OTP sent to mobile")

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        mobile = value.strip()
        if not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return mobile

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        otp = value.strip()
        if not otp.isdigit():
            raise ValueError("OTP must contain only digits.")
        return otp


class VerifyCustomerOtpOut(BaseModel):
    message: str
    mobile: str
    verified_at: datetime


@router.post(
    "/customer-otp/request",
    response_model=RequestCustomerOtpOut,
    summary="Request customer OTP (public)",
)
async def request_customer_otp(
    request: Request,
    payload: RequestCustomerOtpIn = Body(...),
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "request_customer_otp"},
    )

    await enforce_public_security(
        request=request,
        bucket="public:customer_otp_request",
        max_requests=20,
        window_seconds=60,
        block_seconds=300,
    )

    pool = await get_db_pool()
    now_utc = datetime.now(timezone.utc)
    otp_value = generate_sms_otp()
    expires_at = now_utc + timedelta(minutes=OTP_EXPIRY_MINUTES)

    async with pool.acquire() as conn:
        recent_otp = await conn.fetchrow(
            f"""
            SELECT created_at
              FROM {DB_SCHEMA}.customer_otp_verify
             WHERE mobile = $1
               AND otp_purpose = $2
             ORDER BY created_at DESC
             LIMIT 1
            """,
            payload.mobile,
            OTP_PURPOSE_CUSTOMER,
        )
        if recent_otp:
            seconds_since_last = (now_utc - recent_otp["created_at"]).total_seconds()
            if seconds_since_last < OTP_RESEND_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {OTP_RESEND_COOLDOWN_SECONDS} seconds before requesting another OTP.",
                )

        otp_count = await conn.fetchval(
            f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.customer_otp_verify
             WHERE mobile = $1
               AND otp_purpose = $2
               AND created_at > NOW() - ($3::interval)
            """,
            payload.mobile,
            OTP_PURPOSE_CUSTOMER,
            f"{OTP_WINDOW_MINUTES} minutes",
        )
        if (otp_count or 0) >= OTP_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=429,
                detail=f"Too many OTP requests. Please try again after {OTP_WINDOW_MINUTES} minutes.",
            )

        await send_otp_sms(payload.mobile, otp_value)

        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_otp_verify
               SET is_active = FALSE
             WHERE mobile = $1
               AND otp_purpose = $2
               AND is_active = TRUE
            """,
            payload.mobile,
            OTP_PURPOSE_CUSTOMER,
        )

        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.customer_otp_verify
                (mobile, otp, is_verified, is_active, created_at, expires_at, otp_purpose)
            VALUES ($1, $2, FALSE, TRUE, NOW(), $3, $4)
            """,
            payload.mobile,
            otp_value,
            expires_at,
            OTP_PURPOSE_CUSTOMER,
        )

    log.info("Customer OTP requested successfully for mobile=%s", payload.mobile)
    return RequestCustomerOtpOut(
        message="OTP sent successfully.",
        mobile=payload.mobile,
        expires_at=expires_at,
    )


@router.post(
    "/customer-otp/verify",
    response_model=VerifyCustomerOtpOut,
    summary="Verify customer OTP (public)",
)
async def verify_customer_otp(
    request: Request,
    payload: VerifyCustomerOtpIn = Body(...),
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "verify_customer_otp"},
    )

    await enforce_public_security(
        request=request,
        bucket="public:customer_otp_verify",
        max_requests=30,
        window_seconds=60,
        block_seconds=300,
    )

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        otp_row = await conn.fetchrow(
            f"""
            SELECT id, mobile, otp, is_verified, is_active, created_at, expires_at
              FROM {DB_SCHEMA}.customer_otp_verify
             WHERE mobile = $1
               AND otp = $2
               AND otp_purpose = $3
               AND is_active = TRUE
             ORDER BY created_at DESC
             LIMIT 1
            """,
            payload.mobile,
            payload.otp,
            OTP_PURPOSE_CUSTOMER,
        )

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid OTP.")

        if otp_row["is_verified"]:
            raise HTTPException(status_code=400, detail="OTP already verified.")

        now_utc = datetime.now(timezone.utc)
        expires_at = otp_row["expires_at"] or (
            otp_row["created_at"] + timedelta(minutes=OTP_EXPIRY_MINUTES)
        )
        if expires_at < now_utc:
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.customer_otp_verify
                   SET is_active = FALSE
                 WHERE id = $1
                """,
                otp_row["id"],
            )
            raise HTTPException(status_code=400, detail="OTP expired. Please request a new OTP.")

        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_otp_verify
               SET is_verified = TRUE,
                   is_active = FALSE
             WHERE id = $1
            """,
            otp_row["id"],
        )

        verified_at = now_utc
        log.info("Customer OTP verified successfully for mobile=%s", payload.mobile)

        return VerifyCustomerOtpOut(
            message="OTP verified successfully.",
            mobile=payload.mobile,
            verified_at=verified_at,
        )
