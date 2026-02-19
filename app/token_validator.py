import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt
import os
from app.utils import get_db_pool, DB_SCHEMA
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

PUBLIC_PATHS = [
    "/docs",
    "/docs/",
    "/openapi.json",
    "/redoc",
    "/redoc/",
    "/favicon.ico",
    "/health",
    "/app/v1/login",
    "/app/v1/signup",
    "/app/v1/forgot-password/request",
    "/app/v1/forgot-password/verify",
]

def _get_client_ip(request: Request | None) -> str:
    """Get client IP from request (same logic as login.py)."""
    if request is None:
        return "Unknown"
    # Prefer X-Forwarded-For when behind a proxy (use first hop = client)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "Unknown"


async def validate_token(token: str, request: Request | None = None):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logging.info(f"DEBUG: jwt.decode returned type={type(payload)}, value={payload}")
        # Fix: If payload is not a dict, try to convert or raise a clear error
        if isinstance(payload, dict):
            emp_id = payload.get("sub")
        else:
            # Try to convert to dict if possible
            try:
                payload_dict = dict(payload)
                emp_id = payload_dict.get("sub")
            except Exception as e:
                logging.error(f"JWT decode did not return a dict and cannot convert: {type(payload)}. Value: {payload}. Error: {e}")
                return False, f"JWT decode error: {e}"
        # Ensure emp_id is int for DB query
        try:
            emp_id = int(emp_id)
        except (TypeError, ValueError):
            return False, "Invalid emp_id in token"
        # Check session in DB
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            session = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.session_token WHERE emp_id = $1 AND session_token = $2 AND is_active = true",
                emp_id, token
            )
            if not session:
                return False, "Session not active"

            # Improvement: Add detailed logging for session validation
            logging.info(f"Validating session for emp_id={emp_id} with token={token}")

            # Improvement: Log session expiry time for better tracking
            logging.info(f"Session expiry time for emp_id={emp_id}: {session['expires_at']}")

            # Ensure both datetimes are offset-aware (UTC)
            expires_at = session["expires_at"]
            # If naive, assume UTC
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)

            # Improvement: Add audit logging for session expiry
            if expires_at < now_utc:
                logging.info(f"Session expired for emp_id={emp_id}, marking as inactive.")
                await conn.execute(
                    f"UPDATE {DB_SCHEMA}.session_token SET is_active = false WHERE emp_id = $1 AND session_token = $2",
                    emp_id, token
                )
                return False, "Session expired"

            # Improvement: Add audit logging for revoked sessions
            if not session["is_active"]:
                logging.info(f"Session revoked for emp_id={emp_id}.")
                return False, "Session revoked"

            ip_address = _get_client_ip(request)

            # Record session validation actions
            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.session_audit_log (emp_id, session_token, action, action_time, action_details, ip_address)
                VALUES ($1, $2, $3, NOW(), $4, $5)
                """,
                emp_id, token, "VALIDATION", "Session validation successful", ip_address
            )
            logging.info(f"Session validation recorded for emp_id={emp_id} with token={token}, ip_address={ip_address}")
        return True, "Valid"
    except jwt.ExpiredSignatureError:
        return False, "Token expired"
    except jwt.InvalidTokenError:
        return False, "Invalid token"
    except Exception as e:
        return False, f"Error: {str(e)}"

class TokenValidatorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow OPTIONS requests to pass through for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Check if path matches any public path pattern
        request_path = request.url.path
        is_public = any(request_path == path or request_path.startswith(path) for path in PUBLIC_PATHS)
        if is_public:
            return await call_next(request)
        auth = request.headers.get("Authorization")
        request_id = request.headers.get("X-Request-ID", "N/A")
        if not auth or not auth.startswith("Bearer "):
            logging.info(f"Request_ID={request_id} Token_ID=N/A Valid=Invalid Reason=Missing token")
            return JSONResponse(status_code=403, content={"detail": "Forbidden: Missing or invalid token"})
        token = auth.split(" ", 1)[1]
        valid, reason = await validate_token(token, request)
        token_id = "N/A"
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
            if isinstance(payload, dict):
                token_id = payload.get("sub", "N/A")
            else:
                token_id = str(payload)
        except Exception:
            pass
        logging.info(f"Request_ID={request_id} Token_ID={token_id} Valid={'Valid' if valid else 'Invalid'} Reason={reason}")
        if not valid:
            # Show the actual reason for session invalidity to the user
            return JSONResponse(status_code=403, content={"detail": reason})
        return await call_next(request)
