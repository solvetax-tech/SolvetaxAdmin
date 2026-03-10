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
# -------------------------------------------------------------------
# GET PAYMENT CONFIG (UI DROPDOWN)
# -------------------------------------------------------------------

@router.get(
    "/payment-config",
    summary="Get Payment Configurations",
    responses={
        200: {"description": "Payment configs fetched successfully."},
        500: {"description": "Database error."},
    },
)
async def get_payment_configs(
    entity_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_payment_configs"},
    )

    log.info(
        "Incoming payment config request | entity_type=%s",
        entity_type,
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

            rows = await conn.fetch(
                f"""
                SELECT
                    id,
                    entity_type,
                    config_type,
                    value,
                    display_name,
                    amount,
                    description,
                    sort_order
                FROM {DB_SCHEMA}.payment_config
                WHERE upper(entity_type) = upper($1)
                AND is_active = TRUE
                ORDER BY sort_order ASC
                """,
                entity_type,
            )

        log.info(
            "Payment configs fetched successfully | count=%s",
            len(rows),
        )

        return {
            "data": [dict(r) for r in rows],
            "count": len(rows),
            "request_id": request_id,
        }

    except asyncpg.PostgresError:
        log.exception("Database error during payment config fetch")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except Exception:
        log.exception("Unexpected error during payment config fetch")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# GET GST REGISTRATION PAYMENT AMOUNT USING ENTITY_ID
# -------------------------------------------------------------------
@router.get(
    "/amount/{entity_id}",
    summary="Get GST Registration Payment Amount",
    responses={
        200: {"description": "Amount fetched successfully."},
        400: {"description": "Invalid request."},
        404: {"description": "GST registration or payment configuration not found."},
        500: {"description": "Database error."},
    },
)
async def get_payment_amount(
    entity_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    entity_type = "GST_REGISTRATION"

    log.info(
        "Fetching GST payment amount | entity_id=%s",
        entity_id,
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

    async with pool.acquire() as conn:

        try:

            # --------------------------------------------------
            # 1️⃣ Fetch GST registration
            # --------------------------------------------------
            gst_row = await conn.fetchrow(
                f"""
                SELECT
                    id,
                    ownership_category,
                    is_active
                FROM {DB_SCHEMA}.gst_registration
                WHERE id = $1
                LIMIT 1
                """,
                entity_id,
            )

            if not gst_row:
                raise HTTPException(
                    status_code=404,
                    detail="GST registration not found.",
                )

            if not gst_row["is_active"]:
                raise HTTPException(
                    status_code=400,
                    detail="GST registration is inactive.",
                )

            ownership_category = gst_row["ownership_category"].strip().upper()

            # --------------------------------------------------
            # 2️⃣ Fetch payment configuration
            # --------------------------------------------------
            config_row = await conn.fetchrow(
                """
                SELECT
                    display_name,
                    amount,
                    description,
                    is_active
                FROM solvetax.payment_config
                WHERE entity_type = 'GST_REGISTRATION'
                AND config_type = 'PRICE'
                AND value = $1
                LIMIT 1
                """,
                ownership_category,
            )

            if not config_row:
                raise HTTPException(
                    status_code=404,
                    detail="Payment configuration not found.",
                )

            if not config_row["is_active"]:
                raise HTTPException(
                    status_code=400,
                    detail="Payment configuration is inactive.",
                )

            log.info(
                "Payment amount fetched | entity_id=%s | ownership=%s | amount=%s",
                entity_id,
                ownership_category,
                config_row["amount"],
            )

            return {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "ownership_category": ownership_category,
                "display_name": config_row["display_name"],
                "amount": float(config_row["amount"]),
                "description": config_row["description"],
                "request_id": request_id,
            }

        # --------------------------------------------------
        # DATABASE ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:

            log.error(
                "Database error while fetching payment amount | %s",
                str(e),
                exc_info=True,
            )

            raise HTTPException(
                status_code=500,
                detail="Database error.",
            )

        except HTTPException:
            raise

        except Exception:

            log.exception(
                "Unexpected error while fetching GST payment amount"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )