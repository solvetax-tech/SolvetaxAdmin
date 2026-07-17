import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt
import os
from backend.utils import get_db_pool, DB_SCHEMA, hash_session_token
from backend.security.rate_limit import enforce_rate_limit
from dotenv import load_dotenv
from datetime import datetime, timezone

# Per-employee global cap on authenticated API calls (fleet-wide via Redis).
# Generous enough for interactive dashboards; caps runaway/abusive clients.
_API_RATE_LIMIT_PER_MIN = int(os.getenv("API_RATE_LIMIT_PER_MIN", "600"))

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
    "/ready",
    "/app/v1/login",
    "/app/v1/refresh",
    "/app/v1/forgot-password/request",
    "/app/v1/forgot-password/verify",
]

PUBLIC_EXACT_ENDPOINTS = {
    ("POST", "/api/v1/crm/leads/marketing"),
    ("POST", "/api/v1/customers"),
    ("POST", "/api/v1/contact-support"),
    ("POST", "/api/v1/event-logs"),
    ("POST", "/api/v1/event-logs/debug/smoke"),
    ("GET", "/api/v1/payments_config/payment-config/public"),
    ("GET", "/api/v1/payments_config/payment-config/public/service-prices"),
}

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
        if not JWT_SECRET or not JWT_ALGORITHM:
            return False, "Server misconfiguration"

        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        emp_id_raw = payload.get("sub")
        if not emp_id_raw:
            return False, "Invalid token payload"

        try:
            emp_id = int(emp_id_raw)
        except (TypeError, ValueError):
            return False, "Invalid token subject"

        pool = await get_db_pool()

        # Sessions are stored as a SHA-256 hash of the access token, so hash
        # the incoming bearer token before every lookup / audit write.
        token_hash = hash_session_token(token)

        async with pool.acquire() as conn:

            # --------------------------------------------------
            # 1️⃣ Session Check
            # --------------------------------------------------
            session = await conn.fetchrow(
                f"""
                SELECT *
                FROM {DB_SCHEMA}.session_token
                WHERE emp_id=$1
                AND session_token=$2
                AND is_active=true
                """,
                emp_id,
                token_hash
            )

            if not session:

                # 🔐 Minimal Audit Log (Failure Only)
                if request:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.session_audit_log
                        (emp_id, session_token, action, action_details, ip_address)
                        VALUES ($1,$2,$3,$4,$5)
                        """,
                        emp_id,
                        token_hash,
                        "VALIDATION_FAILED",
                        "Session not active",
                        request.client.host if request.client else None
                    )

                return False, "Session not active"

            # --------------------------------------------------
            # 2️⃣ Expiry Check
            # --------------------------------------------------
            expires_at = session["expires_at"]

            if expires_at and expires_at < datetime.now(timezone.utc):
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.session_token
                    SET is_active=false
                    WHERE id=$1
                    """,
                    session["id"]
                )

                # 🔐 Minimal Audit Log
                if request:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.session_audit_log
                        (emp_id, session_token, action, action_details, ip_address)
                        VALUES ($1,$2,$3,$4,$5)
                        """,
                        emp_id,
                        token_hash,
                        "VALIDATION_FAILED",
                        "Session expired",
                        request.client.host if request.client else None
                    )

                return False, "Session expired"

            # --------------------------------------------------
            # 3️⃣ 🔥 EMPLOYEE ACTIVE RE-CHECK
            # --------------------------------------------------
            employee = await conn.fetchrow(
                f"SELECT is_active FROM {DB_SCHEMA}.employees WHERE emp_id=$1",
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

                # 🔐 Minimal Audit Log
                if request:
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.session_audit_log
                        (emp_id, session_token, action, action_details, ip_address)
                        VALUES ($1,$2,$3,$4,$5)
                        """,
                        emp_id,
                        token_hash,
                        "VALIDATION_FAILED",
                        "Employee account inactive",
                        request.client.host if request.client else None
                    )

                return False, "Employee account inactive"

        # ✅ SUCCESS → NO LOG (Prevents log explosion)
        return True, "Valid"

    except jwt.ExpiredSignatureError:
        return False, "Token expired"

    except jwt.InvalidTokenError:
        return False, "Invalid token"

    except Exception:
        return False, "Token validation failed"

class TokenValidatorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow OPTIONS requests to pass through for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Check if path matches any public path pattern
        request_path = request.url.path
        is_public_prefix = any(request_path == path or request_path.startswith(path) for path in PUBLIC_PATHS)
        is_public_exact = (request.method.upper(), request_path) in PUBLIC_EXACT_ENDPOINTS
        if is_public_prefix or is_public_exact:
            return await call_next(request)

        # Vite build + React Router: GET non-API paths serve static/SPA (no JWT).
        if request.method == "GET" and not request_path.startswith("/api/"):
            if not request_path.startswith(("/docs", "/redoc")) and request_path != "/openapi.json":
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

        # Global per-employee API rate limit (fleet-wide via Redis; fails open
        # on Redis outage). Middleware isn't a route context, so translate the
        # limiter's 429 into a JSONResponse rather than letting it propagate.
        try:
            await enforce_rate_limit(
                f"emp:{token_id}",
                bucket="api",
                max_requests=_API_RATE_LIMIT_PER_MIN,
                window_seconds=60,
            )
        except HTTPException as rl_exc:
            return JSONResponse(
                status_code=rl_exc.status_code,
                content={"detail": rl_exc.detail},
                headers=getattr(rl_exc, "headers", None) or {},
            )

        return await call_next(request)
