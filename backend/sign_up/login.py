from fastapi import APIRouter, HTTPException, Request, Body, Depends
from pydantic import BaseModel
from backend.utils import (
    get_db_pool,
    DB_SCHEMA,
    hash_password,
    verify_password,
    get_user_permissions,
    generate_uuid,
    generate_refresh_token,
    hash_refresh_token
)
from dotenv import load_dotenv
from backend.sign_up.schemas import LoginRequest
import os
import jwt
from datetime import datetime, timedelta, timezone
import logging
from backend.security.rbac import require_permission
from backend.logger import logger
import time
import secrets

# Load environment variables from project root .env
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
REFRESH_COOKIE_PATH = "/app/v1"

router = APIRouter(prefix="/app/v1", tags=["Login"])
from fastapi.responses import JSONResponse


@router.post(
    "/login",
    responses={
        200: {"description": "JWT token issued."},
        400: {"description": "Validation failed"},
        401: {"description": "Invalid credentials"},
        429: {"description": "Too many requests"},
        503: {"description": "Service temporarily unavailable"},
    }
)
async def login(
    request: Request,
    payload: LoginRequest = Body(...)
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    email = (payload.email or "").strip().lower()
    password = payload.password or ""

    ip_address = request.client.host if request.client else "Unknown"
    device_info = request.headers.get("User-Agent", "Unknown Device")

    log.info("[login] Attempt email=%s ip=%s", email, ip_address)

    # --------------------------------------------------
    # Rate Limiting
    # --------------------------------------------------
    identifier = f"{ip_address}:{email}"
    now_epoch = int(time.time())
    window = 60
    max_requests = 5

    if not hasattr(request.app.state, "rate_limit_store"):
        request.app.state.rate_limit_store = {}

    store = request.app.state.rate_limit_store
    attempts = store.get(identifier, [])
    attempts = [t for t in attempts if t > now_epoch - window]

    if len(attempts) >= max_requests:
        log.warning("[login] Rate limit exceeded")
        raise HTTPException(status_code=429, detail="Too many login attempts.")

    attempts.append(now_epoch)
    store[identifier] = attempts

    # --------------------------------------------------
    # DB Connection
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("[login] DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    try:
        async with pool.acquire() as conn:

            employee = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.employees WHERE lower(email)=$1",
                email
            )

            if not employee:
                hash_password(password)
                log.warning("[login] Invalid credentials")
                raise HTTPException(status_code=401, detail="Invalid credentials")

            emp_id = employee["emp_id"]
            role = employee.get("role")

            log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

            if not employee.get("is_active", False):
                log.warning("[login] Inactive employee")
                raise HTTPException(status_code=401, detail="Employee account is inactive")

            # --------------------------------------------------
            # Password Verification
            # --------------------------------------------------
            if not verify_password(password, employee["password_hash"]):
                log.warning("[login] Invalid password")
                raise HTTPException(status_code=401, detail="Invalid credentials")

            if not JWT_SECRET or not JWT_ALGORITHM:
                log.error("[login] JWT configuration missing")
                raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

            now_aware = datetime.now(timezone.utc)
            access_expiry = now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)
            refresh_expiry = now_aware + timedelta(days=14)

            permissions = await get_user_permissions(emp_id, conn)

            jwt_payload = {
                "sub": str(emp_id),
                "role": role,
                "iat": int(now_aware.timestamp()),
                "exp": int(access_expiry.timestamp()),
                "jti": generate_uuid(),
                "permissions": permissions,
            }

            access_token = jwt.encode(
                jwt_payload,
                JWT_SECRET,
                algorithm=JWT_ALGORITHM
            )

            raw_refresh_token = generate_refresh_token()
            refresh_hash = hash_refresh_token(raw_refresh_token)

            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.session_token
                (
                    emp_id,
                    session_token,
                    refresh_token,
                    is_active,
                    created_at,
                    expires_at,
                    refresh_expires_at,
                    device_info,
                    ip_address
                )
                VALUES ($1,$2,$3,true,NOW(),$4,$5,$6,$7)
                """,
                emp_id,
                access_token,
                refresh_hash,
                access_expiry,
                refresh_expiry,
                device_info,
                ip_address
            )

            log.info("[login] Session created successfully")

            response = JSONResponse(
                content={
                    "access_token": access_token,
                    "expires_in_minutes": JWT_EXPIRE_MINUTES
                }
            )

            response.set_cookie(
                key="refresh_token",
                value=raw_refresh_token,
                httponly=True,
                secure=True,
                samesite="Strict",
                max_age=14 * 24 * 60 * 60,
                path=REFRESH_COOKIE_PATH,
            )

            return response

    except HTTPException:
        raise
    except Exception:
        log.exception("[login] Unexpected error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")


@router.post(
    "/refresh",
    summary="Refresh access token",
    responses={
        200: {"description": "New access token issued."},
        401: {"description": "Invalid or expired refresh token."},
        503: {"description": "Service unavailable."},
    },
)
async def refresh_token_endpoint(
    request: Request,
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    raw_refresh_token = request.cookies.get("refresh_token")
    ip_address = request.client.host if request.client else "Unknown"
    device_info = request.headers.get("User-Agent", "Unknown Device")

    if not raw_refresh_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("[refresh] DB pool error")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    refresh_hash = hash_refresh_token(raw_refresh_token)

    async with pool.acquire() as conn:
        async with conn.transaction():

            session = await conn.fetchrow(
                f"""
                SELECT *
                FROM {DB_SCHEMA}.session_token
                WHERE refresh_token=$1
                AND is_active=true
                """,
                refresh_hash
            )

            if not session:
                log.warning("[refresh] Invalid refresh token")
                raise HTTPException(status_code=401, detail="Invalid refresh token.")

            refresh_expiry = session["refresh_expires_at"]
            now_utc = datetime.now(timezone.utc)

            if refresh_expiry and refresh_expiry < now_utc:
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.session_token
                    SET is_active=false
                    WHERE id=$1
                    """,
                    session["id"]
                )
                log.warning("[refresh] Expired refresh token used")
                raise HTTPException(status_code=401, detail="Refresh token expired.")

            emp_id = session["emp_id"]
            log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

            employee = await conn.fetchrow(
                f"SELECT is_active, role FROM {DB_SCHEMA}.employees WHERE emp_id=$1",
                emp_id
            )

            if not employee or not employee["is_active"]:
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.session_token
                    SET is_active=false
                    WHERE id=$1
                    """,
                    session["id"]
                )
                raise HTTPException(status_code=401, detail="Employee account inactive.")

            new_refresh_raw = generate_refresh_token()
            new_refresh_hash = hash_refresh_token(new_refresh_raw)

            access_expiry = now_utc + timedelta(minutes=JWT_EXPIRE_MINUTES)
            refresh_expiry_new = now_utc + timedelta(days=14)

            permissions = await get_user_permissions(emp_id, conn)

            new_payload = {
                "sub": str(emp_id),
                "role": employee["role"],
                "iat": int(now_utc.timestamp()),
                "exp": int(access_expiry.timestamp()),
                "jti": generate_uuid(),
                "permissions": permissions,
            }

            new_access_token = jwt.encode(
                new_payload,
                JWT_SECRET,
                algorithm=JWT_ALGORITHM
            )

            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.session_token
                SET session_token=$1,
                    refresh_token=$2,
                    expires_at=$3,
                    refresh_expires_at=$4,
                    ip_address=$5,
                    device_info=$6
                WHERE id=$7
                """,
                new_access_token,
                new_refresh_hash,
                access_expiry,
                refresh_expiry_new,
                ip_address,
                device_info,
                session["id"]
            )

            log.info("[refresh] Token rotated successfully")

            response = JSONResponse(
                content={
                    "access_token": new_access_token,
                    "expires_in_minutes": JWT_EXPIRE_MINUTES
                }
            )

            response.set_cookie(
                key="refresh_token",
                value=new_refresh_raw,
                httponly=True,
                secure=True,
                samesite="Strict",
                max_age=14 * 24 * 60 * 60,
                path=REFRESH_COOKIE_PATH,
            )

            return response


class LogoutRequest(BaseModel):
    session_token: str


@router.post(
    "/logout",
    response_model=None,
    responses={
        200: {"description": "Session revoked successfully."},
        401: {"description": "Unauthorized."},
        503: {"description": "Service temporarily unavailable."},
    },
    dependencies=[Depends(require_permission("EMPLOYEE", "READ"))]
)
async def logout(
    request: Request,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("sub")

    try:
        emp_id = int(emp_id)
    except (TypeError, ValueError):
        emp_id = "-"

    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})
    log.info("[logout] Received logout request")

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.error("[logout] DB pool init failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    raw_refresh_token = request.cookies.get("refresh_token")

    if not raw_refresh_token:
        raise HTTPException(status_code=401, detail="No active session found.")

    refresh_hash = hash_refresh_token(raw_refresh_token)
    ip_address = request.client.host if request.client else "Unknown"

    async with pool.acquire() as conn:
        try:
            result = await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.session_token
                SET is_active = false
                WHERE emp_id = $1
                AND refresh_token = $2
                AND is_active = true
                """,
                emp_id,
                refresh_hash
            )

            if result != "UPDATE 1":
                raise HTTPException(status_code=401, detail="Session already inactive or invalid.")

            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.session_audit_log
                (emp_id, session_token, action, action_time, action_details, ip_address)
                VALUES ($1, $2, $3, NOW(), $4, $5)
                """,
                emp_id,
                refresh_hash,
                "LOGOUT",
                "Session logout successful",
                ip_address
            )

            log.info("[logout] Session revoked successfully")

            response = JSONResponse(
                content={"message": "Session revoked successfully."}
            )

            response.delete_cookie(
                key="refresh_token",
                httponly=True,
                secure=True,
                samesite="Strict",
                path=REFRESH_COOKIE_PATH,
            )

            return response

        except HTTPException:
            raise
        except Exception as e:
            log.error("[logout] Error revoking session: %s", e, exc_info=True)
            raise HTTPException(status_code=503, detail="Service temporarily unavailable.")