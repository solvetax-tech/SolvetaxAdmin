import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn, RegistrationPaymentEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/payments_config",
    tags=["Payments Config"]
)


@router.get(
    "/payment-config/amount",
    summary="Get Amount for Selected Service",
    responses={
        200: {"description": "Amount fetched successfully."},
        404: {"description": "Config not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_payment_amount(
    entity_type: str,
    value: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming payment config lookup | entity_type=%s value=%s",
        entity_type,
        value,
    )

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:

        async with pool.acquire() as conn:

            row = await conn.fetchrow(
                f"""
                SELECT
                    entity_type,
                    config_type,
                    value,
                    display_name,
                    amount,
                    description
                FROM {DB_SCHEMA}.payment_config
                WHERE upper(entity_type) = upper($1)
                  AND upper(value) = upper($2)
                  AND is_active = TRUE
                LIMIT 1
                """,
                entity_type,
                value,
            )

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Payment configuration not found.",
                )

        log.info(
            "Payment config fetched successfully | entity_type=%s value=%s",
            entity_type,
            value,
        )

        return {
            **dict(row),
            "message": "Payment amount fetched successfully.",
            "request_id": request_id,
        }

    except asyncpg.PostgresError:
        log.exception("Database error during payment config lookup")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during payment config lookup")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )