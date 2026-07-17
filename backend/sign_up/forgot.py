from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel,EmailStr
from datetime import datetime, timedelta, timezone
import secrets
import logging
import os

from backend.utils import (
    get_db_pool,
    hash_password,
    verify_password,
    is_password_strong,
    passwords_match,
    generate_uuid
)

from backend.logger import logger
from backend.utils import send_email_otp
from backend.redis_cache import incr_with_ttl, get_int, delete_key
from backend.security.public_security import get_client_ip
from backend.security.rate_limit import enforce_rate_limit


router = APIRouter(prefix="/app/v1", tags=["ForgotPassword"])

OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", 10))
MAX_VERIFY_ATTEMPTS = int(os.getenv("OTP_MAX_VERIFY_ATTEMPTS", 5))


def _verify_attempts_key(emp_id) -> str:
    return f"pwreset:verify_attempts:{emp_id}"


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
    # Cryptographically secure 6-digit OTP (100000-999999).
    return f"{secrets.randbelow(900000) + 100000}"


@router.post("/forgot-password/request", response_model=ForgotPasswordResponse)
async def forgot_password_request(request: Request, payload: ForgotPasswordRequest = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    # Pre-lookup IP throttle (defense-in-depth over the per-email OTP limits below).
    await enforce_rate_limit(get_client_ip(request), bucket="forgot-req-ip", max_requests=20, window_seconds=60)

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

        # Enumeration-safe: never reveal whether an email is registered. Unknown
        # emails get the same generic 200 as a real request (minus the OTP work).
        if not employee:
            log.info("Password reset requested for unknown email (enumeration-safe response)")
            return ForgotPasswordResponse(
                message="If an account exists for that email, a password reset OTP has been sent."
            )

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

        # Fresh OTP issued → reset the verify guess counter so a legitimate user
        # who mistyped earlier gets a clean attempt budget on the new code.
        await delete_key(_verify_attempts_key(emp_id))

        log.info("Password reset OTP generated for emp_id=%s", emp_id)

        return ForgotPasswordResponse(
            message="If an account exists for that email, a password reset OTP has been sent."
        )


@router.post("/forgot-password/verify", response_model=ForgotPasswordResponse)
async def forgot_password_verify(request: Request, payload: ForgotPasswordVerify = Body(...)):

    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    # Pre-lookup IP throttle (per-email attempt counter still applies below).
    await enforce_rate_limit(get_client_ip(request), bucket="forgot-verify-ip", max_requests=30, window_seconds=60)

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

        # Enumeration-safe: an unknown email returns the same generic "Invalid OTP"
        # as a wrong code, so verify can't be used to probe which emails exist.
        if not employee:
            log.info("OTP verify for unknown email (enumeration-safe response)")
            raise HTTPException(status_code=400, detail="Invalid OTP")

        emp_id = employee["emp_id"]

        log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

        # ------------------------------------------------------------------
        # BRUTE-FORCE LOCKOUT - cap wrong OTP guesses per employee within the
        # OTP window. Fails open when Redis is unavailable (get_int -> None) so
        # a Redis outage never blocks a legitimate reset.
        # ------------------------------------------------------------------
        attempts_key = _verify_attempts_key(emp_id)
        prior_attempts = await get_int(attempts_key)
        if prior_attempts is not None and prior_attempts >= MAX_VERIFY_ATTEMPTS:
            log.warning("OTP verify locked (too many attempts) for emp_id=%s", emp_id)
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Please request a new OTP.",
            )

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
            # Wrong code → count this guess against the lockout budget.
            await incr_with_ttl(attempts_key, OTP_EXPIRY_MINUTES * 60)
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

        # bcrypt salts each hash, so compare via verify_password rather than
        # re-hashing and checking equality (which would never match).
        if verify_password(payload.new_password, current_hash):
            raise HTTPException(
                status_code=400,
                detail="New password cannot be same as existing password."
            )

        new_hash = hash_password(payload.new_password)

        # Consume the OTP and rotate the password atomically. Re-read the OTP
        # under FOR UPDATE so two concurrent submits of the same code can't both
        # pass the is_used check (OTP-reuse race).
        async with conn.transaction():
            locked_otp = await conn.fetchrow(
                """
                SELECT is_used
                FROM solvetax.password_reset_otps
                WHERE id = $1
                FOR UPDATE
                """,
                otp_row["id"]
            )

            if not locked_otp or locked_otp["is_used"]:
                raise HTTPException(status_code=400, detail="OTP already used")

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

            # Invalidate every active session for this employee: a password reset
            # must eject any stolen/active token, not just change the credential.
            await conn.execute(
                """
                UPDATE solvetax.session_token
                SET is_active = false
                WHERE emp_id = $1
                """,
                emp_id
            )

        # Successful reset → clear the brute-force counter.
        await delete_key(attempts_key)

        log.info("Password successfully reset for emp_id=%s", emp_id)

        return ForgotPasswordResponse(
            message="Password reset successfully."
        )