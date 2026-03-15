from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta, timezone
import random
import logging
import os

from app.utils import get_db_pool, generate_uuid, send_email_otp
from app.logger import logger

router = APIRouter(prefix="/app/v1", tags=["EmailVerification"])

OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", 10))


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationVerify(BaseModel):
    email: EmailStr
    otp: str


class EmailVerificationResponse(BaseModel):
    message: str


def generate_otp():
    return f"{random.randint(100000,999999)}"


# --------------------------------------------------
# REQUEST OTP
# --------------------------------------------------

@router.post("/email-verification/request", response_model=EmailVerificationResponse)
async def request_email_verification(payload: EmailVerificationRequest = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()

    async with pool.acquire() as conn:

        email = payload.email.strip().lower()

        # --------------------------------------------------
        # Check if employee already exists
        # --------------------------------------------------

        exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM solvetax.employees
                WHERE lower(trim(email)) = lower(trim($1))
            )
            """,
            email
        )

        if exists:
            raise HTTPException(status_code=400, detail="Email already registered")

        # --------------------------------------------------
        # Check if email already verified
        # --------------------------------------------------

        verified = await conn.fetchval(
            """
            SELECT is_verified
            FROM solvetax.employee_email_verifications
            WHERE email=$1
            """,
            email
        )

        if verified:
            raise HTTPException(status_code=400, detail="Email already verified")

        # --------------------------------------------------
        # Cooldown check (60 sec)
        # --------------------------------------------------

        last_record = await conn.fetchrow(
            """
            SELECT created_at
            FROM solvetax.employee_email_verifications
            WHERE email=$1
            """,
            email
        )

        if last_record:

            seconds_since_last = (
                datetime.now(timezone.utc) - last_record["created_at"]
            ).total_seconds()

            if seconds_since_last < 60:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait 60 seconds before requesting another OTP."
                )

        # --------------------------------------------------
        # Generate OTP
        # --------------------------------------------------

        otp = generate_otp()

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

        await conn.execute(
            """
            INSERT INTO solvetax.employee_email_verifications
            (email, otp_code, expires_at, is_used, is_verified, created_at)
            VALUES ($1,$2,$3,false,false,NOW())
            ON CONFLICT (email)
            DO UPDATE SET
                otp_code = EXCLUDED.otp_code,
                expires_at = EXCLUDED.expires_at,
                is_used = false,
                is_verified = false,
                created_at = NOW()
            """,
            email,
            otp,
            expires_at
        )

        # --------------------------------------------------
        # Send Email
        # --------------------------------------------------

        await send_email_otp(email, otp, "email_verification")

        log.info("Email verification OTP sent for email=%s", email)

        return EmailVerificationResponse(
            message="Verification OTP sent to email."
        )


# --------------------------------------------------
# VERIFY OTP
# --------------------------------------------------

@router.post("/email-verification/verify", response_model=EmailVerificationResponse)
async def verify_email(payload: EmailVerificationVerify = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()

    async with pool.acquire() as conn:

        email = payload.email.strip().lower()

        otp_row = await conn.fetchrow(
            """
            SELECT id, otp_code, expires_at, is_used, is_verified
            FROM solvetax.employee_email_verifications
            WHERE email=$1
            """,
            email
        )

        if not otp_row:
            raise HTTPException(status_code=400, detail="OTP not requested")

        if otp_row["is_verified"]:
            raise HTTPException(status_code=400, detail="Email already verified")

        if otp_row["is_used"]:
            raise HTTPException(status_code=400, detail="OTP already used")

        if otp_row["otp_code"] != payload.otp:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        if otp_row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="OTP expired")

        # --------------------------------------------------
        # Mark Email Verified
        # --------------------------------------------------

        await conn.execute(
            """
            UPDATE solvetax.employee_email_verifications
            SET is_verified=true,
                is_used=true,
                verified_at=NOW()
            WHERE id=$1
            """,
            otp_row["id"]
        )

        log.info("Email verified successfully email=%s", email)

        return EmailVerificationResponse(
            message="Email verified successfully."
        )