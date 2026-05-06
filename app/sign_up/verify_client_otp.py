from datetime import datetime, timedelta, timezone
import logging
import os
import random

import httpx

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.logger import logger
from app.security.public_security import enforce_public_security
from app.utils import generate_uuid, get_db_pool


router = APIRouter(prefix="/app/v1", tags=["ClientOtp"])

OTP_EXPIRY_MINUTES = 2
OTP_RESEND_COOLDOWN_SECONDS = 30
OTP_MAX_PER_WINDOW = 5
OTP_WINDOW_MINUTES = 10
MSG91_SEND_URL = "https://control.msg91.com/api/v5/otp"


def generate_otp() -> str:
    return f"{random.randint(100000, 999999)}"


async def _send_otp_via_msg91(mobile: str, otp: str) -> None:
    auth_key = (os.getenv("MSG91_AUTH_KEY") or "dummy_msg91_auth_key").strip()
    template_id = (os.getenv("MSG91_TEMPLATE_ID") or "dummy_msg91_template_id").strip()
    country_code = (os.getenv("MSG91_COUNTRY_CODE") or "91").strip()
    timeout_seconds = float(os.getenv("MSG91_TIMEOUT_SECONDS", "10"))
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


class RequestClientOtpIn(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=10, description="10-digit mobile number")

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        mobile = value.strip()
        if not mobile.isdigit() or len(mobile) != 10:
            raise ValueError("Mobile must be exactly 10 digits.")
        return mobile


class RequestClientOtpOut(BaseModel):
    message: str
    mobile: str
    expires_at: datetime


class VerifyClientOtpIn(BaseModel):
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


class VerifyClientOtpOut(BaseModel):
    message: str
    mobile: str
    verified_at: datetime


@router.post(
    "/client-otp/request",
    response_model=RequestClientOtpOut,
    summary="Request client OTP (public)",
)
async def request_client_otp(
    request: Request,
    payload: RequestClientOtpIn = Body(...),
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "request_client_otp"},
    )

    await enforce_public_security(
        request=request,
        bucket="public:client_otp_request",
        max_requests=20,
        window_seconds=60,
        block_seconds=300,
    )

    pool = await get_db_pool()
    now_utc = datetime.now(timezone.utc)
    otp_value = generate_otp()
    expires_at = now_utc + timedelta(minutes=OTP_EXPIRY_MINUTES)

    async with pool.acquire() as conn:
        recent_otp = await conn.fetchrow(
            """
            SELECT created_at
            FROM solvetax.client_otp_verify
            WHERE mobile = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            payload.mobile,
        )
        if recent_otp:
            seconds_since_last = (now_utc - recent_otp["created_at"]).total_seconds()
            if seconds_since_last < OTP_RESEND_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {OTP_RESEND_COOLDOWN_SECONDS} seconds before requesting another OTP.",
                )

        otp_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM solvetax.client_otp_verify
            WHERE mobile = $1
              AND created_at > NOW() - ($2::interval)
            """,
            payload.mobile,
            f"{OTP_WINDOW_MINUTES} minutes",
        )
        if (otp_count or 0) >= OTP_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=429,
                detail=f"Too many OTP requests. Please try again after {OTP_WINDOW_MINUTES} minutes.",
            )

        await _send_otp_via_msg91(payload.mobile, otp_value)

        # Only keep the latest OTP active for this mobile.
        await conn.execute(
            """
            UPDATE solvetax.client_otp_verify
            SET is_active = FALSE
            WHERE mobile = $1
              AND is_active = TRUE
            """,
            payload.mobile,
        )

        await conn.execute(
            """
            INSERT INTO solvetax.client_otp_verify (mobile, otp, is_verified, is_active, created_at, expires_at)
            VALUES ($1, $2, FALSE, TRUE, NOW(), $3)
            """,
            payload.mobile,
            otp_value,
            expires_at,
        )

    log.info("Client OTP requested successfully for mobile=%s", payload.mobile)
    return RequestClientOtpOut(
        message="OTP sent successfully.",
        mobile=payload.mobile,
        expires_at=expires_at,
    )


@router.post(
    "/client-otp/verify",
    response_model=VerifyClientOtpOut,
    summary="Verify client OTP (public)",
)
async def verify_client_otp(
    request: Request,
    payload: VerifyClientOtpIn = Body(...),
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "verify_client_otp"},
    )

    await enforce_public_security(
        request=request,
        bucket="public:client_otp_verify",
        max_requests=30,
        window_seconds=60,
        block_seconds=300,
    )

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        otp_row = await conn.fetchrow(
            """
            SELECT id, mobile, otp, is_verified, is_active, created_at, expires_at
            FROM solvetax.client_otp_verify
            WHERE mobile = $1
              AND otp = $2
              AND is_active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            payload.mobile,
            payload.otp,
        )

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid OTP.")

        if otp_row["is_verified"]:
            raise HTTPException(status_code=400, detail="OTP already verified.")

        now_utc = datetime.now(timezone.utc)
        expires_at = otp_row["expires_at"] or (otp_row["created_at"] + timedelta(minutes=OTP_EXPIRY_MINUTES))
        if expires_at < now_utc:
            await conn.execute(
                """
                UPDATE solvetax.client_otp_verify
                SET is_active = FALSE
                WHERE id = $1
                """,
                otp_row["id"],
            )
            raise HTTPException(status_code=400, detail="OTP expired. Please request a new OTP.")

        await conn.execute(
            """
            UPDATE solvetax.client_otp_verify
            SET is_verified = TRUE,
                is_active = FALSE
            WHERE id = $1
            """,
            otp_row["id"],
        )

        verified_at = now_utc
        log.info("Client OTP verified successfully for mobile=%s", payload.mobile)

        return VerifyClientOtpOut(
            message="OTP verified successfully.",
            mobile=payload.mobile,
            verified_at=verified_at,
        )
