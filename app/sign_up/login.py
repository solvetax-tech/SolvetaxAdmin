from fastapi import APIRouter, status, HTTPException, Request, Body
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from app.utils import get_db_pool, DB_SCHEMA, hash_password
from dotenv import load_dotenv
import os
import jwt
from datetime import datetime, timedelta, timezone
import uuid
import logging
from pydantic import BaseModel, EmailStr
from typing import Optional

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

"""
POST /api/v1/login
Request JSON body:
{
  "email": "alice@example.com",
  "password": "SuperSecretPass!2024"
}
Both email and password are required.
"""

@router.post("/login", responses={
    200: {"description": "JWT token issued."},
    400: {"description": "Validation failed"},
    401: {"description": "Invalid credentials or MFA not verified"},
    503: {"description": "Service temporarily unavailable. Please try again later."},
})
async def login(
    request: Request,
    payload: LoginRequest = Body(
        ..., 
        example={
            "email": "bhanuvenkatsrikakulapu8@gmail.com",
            "password": "Nagaraju454@"
        }
    )
):
    logging.info(f"Received login request: {payload}")
    password = payload.password
    email = payload.email
    if not password or not email:
        logging.warning(f"Missing credentials: password={password}, email={email}")
        return JSONResponse(status_code=400, content={"error": "Validation failed", "fields": {"credentials": "Provide both email and password"}})
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Allow multiple sessions: do not deactivate previous sessions
        # 1. Lookup employee by email only
        logging.info(f"Looking up employee by email: {email}")
        employee = await conn.fetchrow(f"SELECT * FROM {DB_SCHEMA}.employees WHERE email = $1", email)
        logging.info(f"Employee lookup result: {employee}")
        if not employee:
            logging.warning("Employee not found or invalid credentials.")
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        # 2. Check password
        logging.info("Checking password hash...")
        if employee["password_hash"] != hash_password(password):
            logging.warning("Password hash does not match.")
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        # 3. Issue JWT with device and permissions
        try:
            now_aware = datetime.now(timezone.utc)
            now = now_aware.replace(tzinfo=None)
            exp = (now_aware + timedelta(minutes=JWT_EXPIRE_MINUTES)).replace(tzinfo=None)
            device = {"type": "browser", "os": "linux"}  # Mocked device info
            permissions = {}
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
            return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable. Please try again later."})
        # 4. Store JWT token as session_token in the database
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
        # Always use direct key access for asyncpg Record
        employee_profile = {
            "emp_id": employee["emp_id"],
            "username": employee["username"],
            "email": employee["email"],
            "first_name": employee["first_name"],
            "last_name": employee["last_name"],
            "phone_number": employee["phone_number"],
            "is_active": employee["is_active"],
            "role": employee["role"],
            "created_at": employee["created_at"],
            "updated_at": employee["updated_at"],
        }
        # 'token' is the Bearer JWT for Authorization header
        # 'session_token' is the JWT token for logout body
        return {
            "token": f"Bearer {token}",  # Use this as the Authorization header value
            "session_token": session_token,  # Use this in the logout request body
            "expires_at": exp.isoformat(),
            "profile": employee_profile
        }

class LogoutRequest(BaseModel):
    session_token: str  # This should be the JWT token

@router.post(
    "/logout",
    response_model=None,
    responses={
        200: {"description": "Session revoked successfully."},
        400: {"description": "Invalid session token."},
        401: {"description": "Unauthorized."},
        503: {"description": "Service temporarily unavailable."},
    },
)
async def logout(
    request: Request,
    payload: LogoutRequest = Body(..., example={"session_token": "example-session-token"})
):
    """
    POST /api/v1/logout

    Requires:
        - Authorization header: Bearer <JWT token> (from login response 'token' field)
        - JSON body: { "session_token": "..." } (from login response 'session_token' field)

    Example curl:
        curl -X POST \
            -H "Authorization: Bearer <JWT token>" \
            -H "Content-Type: application/json" \
            -d '{"session_token": "<session_token>"}' \
            http://localhost:8000/app/v1/logout

    Example request body:
    {
        "session_token": "example-session-token"
    }

    Example response:
    {
        "message": "Session revoked successfully."
    }
    """
    session_token = payload.session_token
    logging.info(f"Received logout request for session_token={session_token}")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            # Get emp_id from JWT token in Authorization header
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return JSONResponse(status_code=401, content={"error": "Missing or invalid Authorization header."})
            jwt_token = auth_header.split(" ", 1)[1]
            payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            emp_id = int(payload["sub"])
            ip_address = getattr(request, "client", None)
            if ip_address and hasattr(ip_address, "host") and ip_address.host:
                ip_address = ip_address.host
            else:
                ip_address = "Unknown"

            # Deactivate the session if it matches
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
            # Only log audit if session was actually deactivated
            if result == "UPDATE 1":
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.session_audit_log (emp_id, session_token, action, action_time, action_details, ip_address)
                    VALUES ($1, $2, $3, NOW(), $4, $5)
                    """,
                    emp_id, session_token, "LOGOUT", "Session logout successful", ip_address
                )
                logging.info(f"Session revoked successfully for session_token={session_token}")
                return JSONResponse(status_code=200, content={
                    "message": "Session is revoked",
                    "session_token": session_token
                })
            else:
                logging.info(f"Session already inactive or invalid session_token={session_token}")
                return JSONResponse(status_code=400, content={"error": "Session token is already inactive or does not exist."})
        except Exception as e:
            logging.error(f"Error revoking session: {e}")
            return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable."})