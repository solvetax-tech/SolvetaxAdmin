from fastapi import APIRouter, status, HTTPException, Request, Body, Depends
from pydantic import BaseModel, EmailStr
from app.utils import get_db_pool, DB_SCHEMA, hash_password, get_user_permissions
from dotenv import load_dotenv
import os
import jwt
from datetime import datetime, timedelta, timezone
import logging
from app.security.rbac import require_permission
import time

# Load environment variables from project root .env
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

router = APIRouter(prefix="/app/v1", tags=["Login"])

logging.basicConfig(level=logging.INFO)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

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
    logging.info(f"Received login request: {payload}")
    password = payload.password
    email = payload.email
    if not password or not email:
        logging.warning(f"Missing credentials: password={password}, email={email}")
        raise HTTPException(status_code=400, detail="Validation failed: Provide both email and password")
    
    # Simple in-memory rate limiting by IP and email (demonstration only - replace with Redis or other durable store for production)
    ip_address = request.client.host
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
        logging.warning(f"Rate limit exceeded for {identifier}")
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    # Record current request
    request_times.append(now)
    rate_limit_store[identifier] = request_times

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # 1. Lookup employee by email only
        logging.info(f"Looking up employee by email: {email}")
        employee = await conn.fetchrow(f"SELECT * FROM {DB_SCHEMA}.employees WHERE email = $1", email)
        logging.info(f"Employee lookup result: {employee}")
        if not employee:
            logging.warning("Employee not found or invalid credentials.")
            raise HTTPException(status_code=401, detail="Invalid email credentials")
        # 2. Check password
        logging.info("Checking password hash...")
        if employee["password_hash"] != hash_password(password):
            logging.warning("Password hash does not match.")
            raise HTTPException(status_code=401, detail="Invalid password credentials")
        # 3. Issue JWT with device and permissions
        try:
            now_aware = datetime.now(timezone.utc)
            device = {"type": "browser", "os": "linux"}  # Mocked device info
            permissions = await get_user_permissions(employee["emp_id"], conn)
            jwt_payload = {
                "sub": str(employee["emp_id"]),
                "iat": int(now_aware.timestamp()),
                "exp": int((now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)).timestamp()),
                "device": device,
                "permissions": permissions
            }
            logging.info(f"Creating JWT with payload: {jwt_payload}")
            token = jwt.encode(jwt_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            logging.info(f"JWT created successfully.")
        except Exception as e:
            logging.error(f"Error creating JWT: {e}")
            raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again later.")
        session_token = token
        expires_at = now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        device_info = request.headers.get("User-Agent", "Unknown Device")
        ip_address = request.client.host

        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.session_token (emp_id, session_token, is_active, created_at, expires_at, device_info, ip_address)
            VALUES ($1, $2, true, NOW(), $3, $4, $5)
            """,
            employee["emp_id"], session_token, expires_at, device_info, ip_address
        )
        logging.info(f"Session created for emp_id={employee['emp_id']} with token={session_token}, device_info={device_info}, ip_address={ip_address}")

        return {"session_token": session_token}

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
    payload: LogoutRequest = Body(..., example={"session_token": "example-session-token"})
):
    session_token = payload.session_token
    logging.info(f"Received logout request for session_token={session_token}")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
            jwt_token = auth_header.split(" ", 1)[1]
            payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            emp_id = int(payload["sub"])
            ip_address = getattr(request, "client", None)
            if ip_address and hasattr(ip_address, "host") and ip_address.host:
                ip_address = ip_address.host
            else:
                ip_address = "Unknown"

            logging.info(f"LOGOUT DEBUG: emp_id={emp_id}, session_token={session_token}")
            result = await conn.execute(
                f"""
                UPDATE {DB_SCHEMA}.session_token
                SET is_active = false
                WHERE emp_id = $1 AND session_token = $2 AND is_active = true
                """,
                emp_id, session_token
            )
            logging.info(f"LOGOUT DEBUG: update result={result}")
            if result == "UPDATE 1":
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.session_audit_log (emp_id, session_token, action, action_time, action_details, ip_address)
                    VALUES ($1, $2, $3, NOW(), $4, $5)
                    """,
                    emp_id, session_token, "LOGOUT", "Session logout successful", ip_address
                )
                logging.info(f"Session revoked successfully for session_token={session_token}")
                return {
                    "message": "Session is revoked",
                    "session_token": session_token
                }
            else:
                logging.info(f"Session already inactive or invalid session_token={session_token}")
                raise HTTPException(status_code=400, detail="Session token is already inactive or does not exist.")
        except Exception as e:
            logging.error(f"Error revoking session: {e}")
            raise HTTPException(status_code=503, detail="Service temporarily unavailable.")
