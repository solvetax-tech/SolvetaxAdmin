from fastapi import APIRouter, HTTPException, Request, Body, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, hash_password, get_user_permissions, generate_uuid
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
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

router = APIRouter(prefix="/app/v1", tags=["Login"])


@router.post(
    "/login",
    responses={
        200: {"description": "JWT token issued."},
        400: {"description": "Validation failed"},
        401: {"description": "Invalid credentials or MFA not verified"},
        429: {"description": "Too many requests - rate limited"},
        503: {"description": "Service temporarily unavailable. Please try again later."},
    }
)
async def login(
    request: Request,
    payload: LoginRequest = Body(..., example={"email": "bhanuvenkatsrikakulapu8@gmail.com","password": "Nagaraju454@"})
):
    request_id = generate_uuid()
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": "-"})

    email = payload.email
    password = payload.password
    ip_address = request.client.host if request.client else "Unknown"
    log.info("[login] Received login request email=%s ip=%s", email, ip_address)
    
    # Simple in-memory rate limiting by IP and email (demonstration only - replace with Redis or other durable store for production)
    identifier = f"{ip_address}:{email}"
    now = int(time.time())
    window = 60  # 60 seconds rate limit window
    max_requests = 5  # Max 5 login attempts per window
    
    # Initialize simple in-memory rate limiting storage on the app state once
    if not hasattr(request.app.state, "rate_limit_store"):
        request.app.state.rate_limit_store = {}

    rate_limit_store = request.app.state.rate_limit_store
    request_times = rate_limit_store.get(identifier, [])
    # Remove requests outside current window
    request_times = [t for t in request_times if t > now - window]
    if len(request_times) >= max_requests:
        log.warning("Rate limit exceeded for %s", identifier)
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    # Record current request
    request_times.append(now)
    rate_limit_store[identifier] = request_times

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.error("[login] DB pool init failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again later.")

    try:
        async with pool.acquire() as conn:
            # 1. Lookup employee by email only
            log.info("[login] Looking up employee by email=%s", email)
            employee = await conn.fetchrow(f"SELECT * FROM {DB_SCHEMA}.employees WHERE email = $1", email)
            if not employee:
                log.warning("[login] Employee not found or invalid credentials.")
                raise HTTPException(status_code=401, detail="Invalid credentials")

            emp_id = employee["emp_id"]
            # From here we know the user: use real emp_id in logs
            log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

            # Check if employee is active
            if not employee.get("is_active", False):
                log.warning("[login] Inactive employee emp_id=%s", emp_id)
                raise HTTPException(status_code=401, detail="Employee account is inactive")

            # 2. Check password (avoid logging secrets)
            computed_hash = hash_password(password)
            if not secrets.compare_digest(str(employee["password_hash"]), str(computed_hash)):
                log.warning("[login] Invalid password for emp_id=%s", emp_id)
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # 3. Issue JWT with permissions
            if not JWT_SECRET:
                log.error("[login] JWT_SECRET missing in environment")
                raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again later.")

            now_aware = datetime.now(timezone.utc)
            permissions = await get_user_permissions(emp_id, conn)
            jwt_payload = {
                "sub": str(emp_id),
                "iat": int(now_aware.timestamp()),
                "exp": int((now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)).timestamp()),
                "permissions": permissions,
            }

            try:
                session_token = jwt.encode(jwt_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            except Exception as e:
                log.error("[login] Error creating JWT: %s", e, exc_info=True)
                raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again later.")

            # Persist session token
            expires_at = now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)
            if expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
            device_info = request.headers.get("User-Agent", "Unknown Device")

            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.session_token (emp_id, session_token, is_active, created_at, expires_at, device_info, ip_address)
                VALUES ($1, $2, true, NOW(), $3, $4, $5)
                """,
                emp_id, session_token, expires_at, device_info, ip_address
            )
            log.info("[login] Session created for emp_id=%s device_info=%s ip=%s", emp_id, device_info, ip_address)

            return {"session_token": session_token}
    except HTTPException:
        raise
    except Exception as e:
        log.error("[login] Unexpected error during login: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again later.")

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
