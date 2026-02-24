from fastapi import APIRouter, HTTPException, Request, Body, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, hash_password, get_user_permissions, generate_uuid, generate_refresh_token, hash_refresh_token
from dotenv import load_dotenv
from app.sign_up.schemas import LoginRequest
import os
import jwt
from datetime import datetime, timedelta, timezone
import logging
from app.security.rbac import require_permission
from app.logger import logger
import time
import secrets
# Load environment variables from project root .env
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "15"))

router = APIRouter(prefix="/app/v1", tags=["Login"])

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

    email = payload.email.strip().lower()
    password = payload.password
    ip_address = request.client.host if request.client else "Unknown"
    device_info = request.headers.get("User-Agent", "Unknown Device")

    log.info("[login] Received login request email=%s ip=%s", email, ip_address)

    # --------------------------------------------------
    # Rate Limiting (Preserved)
    # --------------------------------------------------
    identifier = f"{ip_address}:{email}"
    now_epoch = int(time.time())
    window = 60
    max_requests = 5

    if not hasattr(request.app.state, "rate_limit_store"):
        request.app.state.rate_limit_store = {}

    rate_limit_store = request.app.state.rate_limit_store
    request_times = rate_limit_store.get(identifier, [])
    request_times = [t for t in request_times if t > now_epoch - window]

    if len(request_times) >= max_requests:
        log.warning("Rate limit exceeded for %s", identifier)
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")

    request_times.append(now_epoch)
    rate_limit_store[identifier] = request_times

    # --------------------------------------------------
    # DB Connection
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception as e:
        log.error("[login] DB pool init failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    try:
        async with pool.acquire() as conn:

            # --------------------------------------------------
            # Fetch Employee
            # --------------------------------------------------
            employee = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.employees WHERE lower(email) = $1",
                email
            )

            if not employee:
                log.warning("[login] Invalid credentials (email not found)")
                raise HTTPException(status_code=401, detail="Invalid credentials")

            emp_id = employee["emp_id"]
            log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

            if not employee.get("is_active", False):
                log.warning("[login] Inactive employee")
                raise HTTPException(status_code=401, detail="Employee account is inactive")

            # --------------------------------------------------
            # Password Validation (Constant-Time)
            # --------------------------------------------------
            computed_hash = hash_password(password)

            if not secrets.compare_digest(
                str(employee["password_hash"]),
                str(computed_hash)
            ):
                log.warning("[login] Invalid password")
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # --------------------------------------------------
            # JWT Creation (Access Token - Short Expiry)
            # --------------------------------------------------
            if not JWT_SECRET or not JWT_ALGORITHM:
                log.error("[login] JWT configuration missing")
                raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

            now_aware = datetime.now(timezone.utc)
            access_expiry = now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)

            permissions = await get_user_permissions(emp_id, conn)
            jti = generate_uuid()

            jwt_payload = {
                "sub": str(emp_id),
                "iat": int(now_aware.timestamp()),
                "exp": int(access_expiry.timestamp()),
                "jti": jti,
                "permissions": permissions,
            }

            try:
                access_token = jwt.encode(jwt_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            except Exception as e:
                log.error("[login] JWT encode failed: %s", e, exc_info=True)
                raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

            # --------------------------------------------------
            # Secure Refresh Token Creation (HASHED STORAGE)
            # --------------------------------------------------
            raw_refresh_token = generate_refresh_token()
            refresh_hash = hash_refresh_token(raw_refresh_token)
            refresh_expiry = now_aware + timedelta(days=14)

            # Remove tzinfo for DB compatibility
            access_expiry_db = access_expiry.replace(tzinfo=None)
            refresh_expiry_db = refresh_expiry.replace(tzinfo=None)

            # --------------------------------------------------
            # Persist Session
            # --------------------------------------------------
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
                refresh_hash,        # 🔐 Store HASH only
                access_expiry_db,
                refresh_expiry_db,
                device_info,
                ip_address
            )

            log.info(
                "[login] Session created | emp_id=%s device=%s ip=%s",
                emp_id,
                device_info,
                ip_address
            )

            return {
                "access_token": access_token,
                "refresh_token": raw_refresh_token,  # 🔐 Return raw token only once
                "expires_in_minutes": JWT_EXPIRE_MINUTES
            }

    except HTTPException:
        raise
    except Exception as e:
        log.error("[login] Unexpected error: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")



class RefreshRequest(BaseModel):
    refresh_token: str


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
    payload: RefreshRequest = Body(...),
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    raw_refresh_token = payload.refresh_token.strip()
    ip_address = request.client.host if request.client else "Unknown"
    device_info = request.headers.get("User-Agent", "Unknown Device")

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.error("[refresh] DB pool error: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    refresh_hash = hash_refresh_token(raw_refresh_token)

    async with pool.acquire() as conn:
        async with conn.transaction():

            session = await conn.fetchrow(
                f"""
                SELECT *
                FROM {DB_SCHEMA}.session_token
                WHERE refresh_token = $1
                AND is_active = true
                """,
                refresh_hash
            )

            if not session:
                log.warning("[refresh] Invalid refresh token attempt")
                raise HTTPException(status_code=401, detail="Invalid refresh token.")

            # --------------------------------------------------
            # Expiry Check (Authoritative DB Check)
            # --------------------------------------------------
            refresh_expiry = session["refresh_expires_at"]
            now_utc = datetime.now(timezone.utc)

            if refresh_expiry:
                if refresh_expiry.tzinfo is None:
                    refresh_expiry = refresh_expiry.replace(tzinfo=timezone.utc)

                if refresh_expiry < now_utc:
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.session_token
                        SET is_active = false
                        WHERE id = $1
                        """,
                        session["id"]
                    )
                    log.warning("[refresh] Expired refresh token used")
                    raise HTTPException(status_code=401, detail="Refresh token expired.")

            emp_id = session["emp_id"]
            log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

            # --------------------------------------------------
            # Rotate Refresh Token (CRITICAL SECURITY)
            # --------------------------------------------------
            new_refresh_raw = generate_refresh_token()
            new_refresh_hash = hash_refresh_token(new_refresh_raw)

            access_expiry = now_utc + timedelta(minutes=JWT_EXPIRE_MINUTES)
            refresh_expiry_new = now_utc + timedelta(days=14)

            # --------------------------------------------------
            # Create New Access Token (Fresh Permissions)
            # --------------------------------------------------
            permissions = await get_user_permissions(emp_id, conn)

            new_payload = {
                "sub": str(emp_id),
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

            # --------------------------------------------------
            # Update Session Record (Rotation)
            # --------------------------------------------------
            await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.session_token
                SET session_token = $1,
                    refresh_token = $2,
                    expires_at = $3,
                    refresh_expires_at = $4,
                    ip_address = $5,
                    device_info = $6
                WHERE id = $7
                """,
                new_access_token,
                new_refresh_hash,
                access_expiry.replace(tzinfo=None),
                refresh_expiry_new.replace(tzinfo=None),
                ip_address,
                device_info,
                session["id"]
            )

            log.info("[refresh] Token rotated successfully")

            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_raw,
                "expires_in_minutes": JWT_EXPIRE_MINUTES
            }

class LogoutRequest(BaseModel):
    session_token: str

@router.post(
    "/logout",
    response_model=None,
    responses={
        200: {"description": "Session revoked successfully."},
        400: {"description": "Invalid session token."},
        401: {"description": "Unauthorized."},
        503: {"description": "Service temporarily unavailable."},
    },
    dependencies=[Depends(require_permission("EMPLOYEE", "READ"))]
)
async def logout(
    request: Request,
    payload: LogoutRequest = Body(..., example={"session_token": "example-session-token"}),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("sub")  # from JWT
    try:
        emp_id = int(emp_id)
    except (TypeError, ValueError):
        emp_id = "-"
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    session_token = payload.session_token
    log.info("[logout] Received logout request")

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.error("[logout] DB pool init failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    if not JWT_SECRET:
        log.error("[logout] JWT_SECRET missing in environment")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    async with pool.acquire() as conn:
        try:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
            jwt_token = auth_header.split(" ", 1)[1]
            jwt_payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            emp_id = int(jwt_payload["sub"])
            ip_address = request.client.host if request.client else "Unknown"

            result = await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.session_token
                SET is_active = false
                WHERE emp_id = $1 AND session_token = $2 AND is_active = true
                """,
                emp_id, session_token
            )
            if result == "UPDATE 1":
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.session_audit_log (emp_id, session_token, action, action_time, action_details, ip_address)
                    VALUES ($1, $2, $3, NOW(), $4, $5)
                    """,
                    emp_id, session_token, "LOGOUT", "Session logout successful", ip_address
                )
                log.info("[logout] Session revoked successfully for emp_id=%s ip=%s", emp_id, ip_address)
                return {
                    "message": "Session is revoked",
                    "session_token": session_token
                }

            raise HTTPException(status_code=400, detail="Session token is already inactive or does not exist.")
        except HTTPException:
            raise
        except Exception as e:
            log.error("[logout] Error revoking session: %s", e, exc_info=True)
            raise HTTPException(status_code=503, detail="Service temporarily unavailable.")
