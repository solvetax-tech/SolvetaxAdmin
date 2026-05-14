"""
Customer portal sessions: short-lived access JWT + refresh token stored in DB (no refresh expiry until logout).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import asyncpg
import jwt
from fastapi import HTTPException, Request

from app.utils import (
    DB_SCHEMA,
    generate_refresh_token,
    hash_refresh_token,
)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
CUSTOMER_JWT_AUD = "customer"
# Short access token — client refreshes silently; user is not prompted until refresh is revoked (logout / password reset).
CUSTOMER_ACCESS_TOKEN_MINUTES = int(os.getenv("CUSTOMER_ACCESS_TOKEN_MINUTES", "30"))


def _encode_access_token(customer_id: int, mobile: str, jti: str) -> Tuple[str, int]:
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="Server misconfiguration.")
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=CUSTOMER_ACCESS_TOKEN_MINUTES)
    exp_i = int(exp.timestamp())
    now_i = int(now.timestamp())
    token = jwt.encode(
        {
            "sub": str(customer_id),
            "mobile": mobile,
            "aud": CUSTOMER_JWT_AUD,
            "jti": jti,
            "iat": now_i,
            "exp": exp_i,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return token, exp_i - now_i


async def create_customer_session(
    conn: asyncpg.Connection,
    *,
    customer_id: int,
    mobile: str,
    request: Request,
) -> Tuple[str, str, int]:
    """
    Insert session row; return (access_token, raw_refresh_token, expires_in_seconds).
    """
    jti = str(uuid.uuid4())
    access_token, expires_in = _encode_access_token(customer_id, mobile, jti)
    raw_refresh = generate_refresh_token()
    ref_hash = hash_refresh_token(raw_refresh)
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    try:
        await conn.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.customer_sessions
                (customer_id, jti, refresh_token_hash, is_active, created_at, updated_at, ip_address, user_agent)
            VALUES ($1, $2, $3, TRUE, NOW(), NOW(), $4, $5)
            """,
            customer_id,
            jti,
            ref_hash,
            ip,
            ua,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(
            status_code=503,
            detail="Customer sessions are not configured (run ddl_customer_sessions.sql).",
        )
    return access_token, raw_refresh, expires_in


async def load_customer_from_bearer(
    conn: asyncpg.Connection,
    bearer_token: str,
) -> asyncpg.Record:
    """
    Validate access JWT (incl. expiry) and active session row; return customers row.
    """
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="Server misconfiguration.")
    try:
        payload: Dict[str, Any] = jwt.decode(
            bearer_token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "ACCESS_TOKEN_EXPIRED",
                "message": "Access token expired. Call POST /app/v1/customer-profile/refresh with your refresh_token.",
            },
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token.")

    if payload.get("aud") != CUSTOMER_JWT_AUD:
        raise HTTPException(status_code=401, detail="Invalid access token.")

    try:
        cid = int(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid access token.")

    jti = payload.get("jti")
    if not jti or not isinstance(jti, str):
        raise HTTPException(status_code=401, detail="Invalid access token.")

    mobile = (str(payload.get("mobile") or "")).strip()
    if len(mobile) != 10 or not mobile.isdigit():
        raise HTTPException(status_code=401, detail="Invalid access token.")

    try:
        sess = await conn.fetchrow(
            f"""
            SELECT id
              FROM {DB_SCHEMA}.customer_sessions
             WHERE jti = $1
               AND customer_id = $2
               AND is_active = TRUE
             LIMIT 1
            """,
            jti,
            cid,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(
            status_code=503,
            detail="Customer sessions are not configured (run ddl_customer_sessions.sql).",
        )

    if not sess:
        raise HTTPException(
            status_code=401,
            detail="Session is no longer active. Please log in again.",
        )

    row = await conn.fetchrow(
        f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE customer_id = $1
           AND trim(mobile) = trim($2::text)
           AND is_active = TRUE
         LIMIT 1
        """,
        cid,
        mobile,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Account not found or inactive.")
    return row


async def load_customer_from_bearer_for_update(
    conn: asyncpg.Connection,
    bearer_token: str,
) -> asyncpg.Record:
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="Server misconfiguration.")
    try:
        payload: Dict[str, Any] = jwt.decode(
            bearer_token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "ACCESS_TOKEN_EXPIRED",
                "message": "Access token expired. Call POST /app/v1/customer-profile/refresh with your refresh_token.",
            },
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token.")

    if payload.get("aud") != CUSTOMER_JWT_AUD:
        raise HTTPException(status_code=401, detail="Invalid access token.")

    try:
        cid = int(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid access token.")

    jti = payload.get("jti")
    if not jti or not isinstance(jti, str):
        raise HTTPException(status_code=401, detail="Invalid access token.")

    mobile = (str(payload.get("mobile") or "")).strip()

    sess = await conn.fetchrow(
        f"""
        SELECT id
          FROM {DB_SCHEMA}.customer_sessions
         WHERE jti = $1
           AND customer_id = $2
           AND is_active = TRUE
         LIMIT 1
        """,
        jti,
        cid,
    )
    if not sess:
        raise HTTPException(
            status_code=401,
            detail="Session is no longer active. Please log in again.",
        )

    row = await conn.fetchrow(
        f"""
        SELECT *
          FROM {DB_SCHEMA}.customers
         WHERE customer_id = $1
           AND trim(mobile) = trim($2::text)
           AND is_active = TRUE
         FOR UPDATE LIMIT 1
        """,
        cid,
        mobile,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Account not found or inactive.")
    return row


async def rotate_refresh_token(
    conn: asyncpg.Connection,
    *,
    raw_refresh: str,
    request: Request,
) -> Tuple[str, str, int, int]:
    """
    Validate refresh hash, rotate refresh token, return (access_token, new_raw_refresh, expires_in_seconds, customer_id).
    """
    ref_hash = hash_refresh_token(raw_refresh.strip())
    row = await conn.fetchrow(
        f"""
        SELECT s.id, s.customer_id, c.mobile
          FROM {DB_SCHEMA}.customer_sessions s
          JOIN {DB_SCHEMA}.customers c ON c.customer_id = s.customer_id
         WHERE s.refresh_token_hash = $1
           AND s.is_active = TRUE
           AND c.is_active = TRUE
         LIMIT 1
        """,
        ref_hash,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    mobile = (row["mobile"] or "").strip()
    customer_id = int(row["customer_id"])
    session_id = int(row["id"])

    new_jti = str(uuid.uuid4())
    access_token, expires_in = _encode_access_token(customer_id, mobile, new_jti)
    new_raw = generate_refresh_token()
    new_hash = hash_refresh_token(new_raw)
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")

    await conn.execute(
        f"""
        UPDATE {DB_SCHEMA}.customer_sessions
           SET jti = $2,
               refresh_token_hash = $3,
               updated_at = NOW(),
               ip_address = COALESCE($4, ip_address),
               user_agent = COALESCE($5, user_agent)
         WHERE id = $1
           AND is_active = TRUE
        """,
        session_id,
        new_jti,
        new_hash,
        ip,
        ua,
    )

    return access_token, new_raw, expires_in, customer_id


async def deactivate_session_by_jti(conn: asyncpg.Connection, bearer_token: str) -> bool:
    """Deactivate session matching token jti (exp ignored). Returns True if a row was updated."""
    if not JWT_SECRET:
        return False
    try:
        payload = jwt.decode(
            bearer_token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return False
    jti = payload.get("jti")
    cid = payload.get("sub")
    if not jti or cid is None:
        return False
    try:
        tag = await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_sessions
               SET is_active = FALSE, updated_at = NOW()
             WHERE jti = $1
               AND customer_id = $2::bigint
               AND is_active = TRUE
            """,
            str(jti),
            str(cid),
        )
    except asyncpg.UndefinedTableError:
        return False
    last = (tag or "").strip().split()[-1] if tag else ""
    return last.isdigit() and int(last) > 0


async def deactivate_session_by_refresh(conn: asyncpg.Connection, raw_refresh: str) -> bool:
    ref_hash = hash_refresh_token(raw_refresh.strip())
    try:
        tag = await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_sessions
               SET is_active = FALSE, updated_at = NOW()
             WHERE refresh_token_hash = $1
               AND is_active = TRUE
            """,
            ref_hash,
        )
    except asyncpg.UndefinedTableError:
        return False
    last = (tag or "").strip().split()[-1] if tag else ""
    return last.isdigit() and int(last) > 0


async def deactivate_all_sessions_for_customer(conn: asyncpg.Connection, customer_id: int) -> None:
    try:
        await conn.execute(
            f"""
            UPDATE {DB_SCHEMA}.customer_sessions
               SET is_active = FALSE, updated_at = NOW()
             WHERE customer_id = $1
               AND is_active = TRUE
            """,
            customer_id,
        )
    except asyncpg.UndefinedTableError:
        pass
