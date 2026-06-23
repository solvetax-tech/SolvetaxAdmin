from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel,EmailStr
from datetime import datetime, timedelta, timezone
import random
import logging
import os

from backend.utils import (
    get_db_pool,
    hash_password,
    is_password_strong,
    passwords_match,
    generate_uuid
)

from backend.logger import logger
from backend.utils import send_email_otp


router = APIRouter(prefix="/app/v1", tags=["ForgotPassword"])

OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", 10))


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordVerify(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
    confirm_password: str


class ForgotPasswordResponse(BaseModel):
    message: str


def generate_otp():
    return f"{random.randint(100000, 999999)}"


@router.post("/forgot-password/request", response_model=ForgotPasswordResponse)
async def forgot_password_request(payload: ForgotPasswordRequest = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()

    async with pool.acquire() as conn:

        employee = await conn.fetchrow(
            """
            SELECT emp_id, email
            FROM solvetax.employees
            WHERE lower(trim(email)) = lower(trim($1))
            """,
            payload.email
        )

        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        emp_id = employee["emp_id"]
        email = employee["email"]

        log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

        # ------------------------------------------------------------------
        # OTP RATE LIMITING - COOLDOWN CHECK (60 seconds)
        # ------------------------------------------------------------------
        last_otp = await conn.fetchrow(
            """
            SELECT created_at
            FROM solvetax.password_reset_otps
            WHERE emp_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            emp_id
        )

        if last_otp:
            seconds_since_last = (
                datetime.now(timezone.utc) - last_otp["created_at"]
            ).total_seconds()

            if seconds_since_last < 60:
                log.warning("OTP requested too quickly for emp_id=%s", emp_id)
                raise HTTPException(
                    status_code=429,
                    detail="Please wait 60 seconds before requesting another OTP."
                )

        # ------------------------------------------------------------------
        # OTP RATE LIMITING - MAX 5 OTPs PER 10 MINUTES
        # ------------------------------------------------------------------
        otp_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM solvetax.password_reset_otps
            WHERE emp_id = $1
            AND created_at > NOW() - INTERVAL '10 minutes'
            """,
            emp_id
        )

        if otp_count >= 5:
            log.warning("Too many OTP requests for emp_id=%s", emp_id)
            raise HTTPException(
                status_code=429,
                detail="Too many OTP requests. Please try again after 10 minutes."
            )

        otp = generate_otp()

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

        await conn.execute(
            """
            INSERT INTO solvetax.password_reset_otps
            (emp_id, otp_code, expires_at, is_used, created_at)
            VALUES ($1, $2, $3, false, NOW())
            """,
            emp_id,
            otp,
            expires_at
        )

        await send_email_otp(email, otp)

        log.info("Password reset OTP generated for emp_id=%s", emp_id)

        return ForgotPasswordResponse(
            message="OTP sent to your registered email."
        )


@router.post("/forgot-password/verify", response_model=ForgotPasswordResponse)
async def forgot_password_verify(payload: ForgotPasswordVerify = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()

    async with pool.acquire() as conn:

        employee = await conn.fetchrow(
            """
            SELECT emp_id
            FROM solvetax.employees
            WHERE lower(trim(email)) = lower(trim($1))
            """,
            payload.email
        )

        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        emp_id = employee["emp_id"]

        log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

        otp_row = await conn.fetchrow(
            """
            SELECT id, expires_at, is_used
            FROM solvetax.password_reset_otps
            WHERE emp_id = $1
            AND otp_code = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            emp_id,
            payload.otp
        )

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        if otp_row["is_used"]:
            raise HTTPException(status_code=400, detail="OTP already used")

        if otp_row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="OTP expired")

        if not is_password_strong(payload.new_password):
            raise HTTPException(
                status_code=400,
                detail="Password must contain uppercase, lowercase, digit, special character and minimum 8 characters."
            )

        if not passwords_match(payload.new_password, payload.confirm_password):
            raise HTTPException(
                status_code=400,
                detail="New password and confirm password do not match."
            )

        employee_row = await conn.fetchrow(
            """
            SELECT password_hash
            FROM solvetax.employees
            WHERE emp_id = $1
            """,
            emp_id
        )

        if not employee_row:
            raise HTTPException(status_code=404, detail="Employee not found")

        current_hash = employee_row["password_hash"]
        new_hash = hash_password(payload.new_password)

        if current_hash == new_hash:
            raise HTTPException(
                status_code=400,
                detail="New password cannot be same as existing password."
            )

        await conn.execute(
            """
            UPDATE solvetax.employees
            SET password_hash = $1,
                updated_at = NOW()
            WHERE emp_id = $2
            """,
            new_hash,
            emp_id
        )

        await conn.execute(
            """
            UPDATE solvetax.password_reset_otps
            SET is_used = true
            WHERE id = $1
            """,
            otp_row["id"]
        )

        log.info("Password successfully reset for emp_id=%s", emp_id)

        return ForgotPasswordResponse(
            message="Password reset successfully."
        )