from fastapi import APIRouter, status, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from pydantic import Field
from app.sign_up.schemas import ForgotPasswordRequest, ForgotPasswordVerify, ForgotPasswordResponse
from app.utils import get_db_pool, hash_password, is_password_strong, passwords_match, generate_uuid
from app.logger import logger
from datetime import datetime, timedelta, timezone
import random
import logging

router = APIRouter(prefix="/app/v1", tags=["ForgotPassword"])

OTP_EXPIRY_MINUTES = 10

# Schemas now imported from api.signup.schemas

def generate_otp():
    return f"{random.randint(1000, 9999):04d}"

import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()  # Ensure .env variables are loaded

async def send_sms(phone_number: str, otp: str):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    if not all([account_sid, auth_token, from_number]):
        raise RuntimeError("Twilio credentials are not set in the environment variables.")

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        body=f"Your OTP is: {otp}",
        from_=from_number,
        to=phone_number
    )
    logger.info("Twilio SMS sent: SID=%s to=%s", message.sid, phone_number)

@router.post("/forgot-password/request", response_model=ForgotPasswordResponse)
async def forgot_password_request(
    payload: ForgotPasswordRequest = Body(...)
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # 1. Find employee by email
        employee = await conn.fetchrow("SELECT emp_id, phone_number FROM solvetax.employees WHERE email = $1", payload.email)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        emp_id = employee["emp_id"]
        log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
        phone_number = employee["phone_number"]
        if not phone_number:
            raise HTTPException(status_code=400, detail="No phone number registered for this employee")
        # 2. Generate OTP and expiry
        otp = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
        # 3. Save OTP to DB
        await conn.execute(
            """
            INSERT INTO solvetax.password_reset_otps (emp_id, otp_code, expires_at, is_used, created_at)
            VALUES ($1, $2, $3, false, NOW())
            """,
            emp_id, otp, expires_at
        )
        # 4. Send OTP via SMS (stub)
        await send_sms(phone_number, otp)
        log.info("OTP generated for emp_id=%s, expires at %s", emp_id, expires_at)
        return ForgotPasswordResponse(message="OTP sent to your registered phone number.")

@router.post("/forgot-password/verify", response_model=ForgotPasswordResponse)
async def forgot_password_verify(
    payload: ForgotPasswordVerify = Body(...)
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # 1. Find employee by email
        employee = await conn.fetchrow("SELECT emp_id FROM solvetax.employees WHERE email = $1", payload.email)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        emp_id = employee["emp_id"]
        log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
        # 2. Find valid OTP
        otp_row = await conn.fetchrow(
            """
            SELECT id, expires_at, is_used FROM solvetax.password_reset_otps
            WHERE emp_id = $1 AND otp_code = $2
            ORDER BY created_at DESC LIMIT 1
            """,
            emp_id, payload.otp
        )
        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid OTP")
        if otp_row["is_used"]:
            raise HTTPException(status_code=400, detail="OTP already used")
        if otp_row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="OTP expired")
        # 3. Validate password strength
        if not is_password_strong(payload.new_password):
            raise HTTPException(
                status_code=400,
                detail="Password is not strong enough. It must be at least 8 characters long and include uppercase, lowercase, digit, and special character."
            )
        # 4. Check confirm password
        if not passwords_match(payload.new_password, payload.confirm_password):
            raise HTTPException(
                status_code=400,
                detail="New password and confirm password do not match."
            )
        # 5. Check if new password matches existing password
        employee_row = await conn.fetchrow(
            "SELECT password_hash FROM solvetax.employees WHERE emp_id = $1",
            emp_id
        )
        if employee_row:
            current_hash = employee_row["password_hash"]
            new_hash = hash_password(payload.new_password)
            if current_hash == new_hash:
                raise HTTPException(
                    status_code=400,
                    detail="New password cannot be the same as the existing password."
                )
        else:
            raise HTTPException(status_code=404, detail="Employee not found")
        # 6. Update password (hash)
        await conn.execute(
            "UPDATE solvetax.employees SET password_hash = $1, updated_at = NOW() WHERE emp_id = $2",
            new_hash, emp_id
        )
        # 7. Mark OTP as used
        await conn.execute(
            "UPDATE solvetax.password_reset_otps SET is_used = true WHERE id = $1",
            otp_row["id"]
        )
        log.info("Password reset for emp_id=%s", emp_id)
        return ForgotPasswordResponse(message="Password has been reset successfully.")
