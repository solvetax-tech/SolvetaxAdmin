import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
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
    entity_type_norm = entity_type.strip().upper()
    cache_key = build_cache_key(
        "payments_config:get_configs",
        entity_type=entity_type_norm,
        emp_id=emp_id,
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

    async def _load_payment_configs():
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
                    entity_type_norm,
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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_payment_configs,
        ttl_seconds=300,
        tags=["payments_config:get_configs:index"],
    )

@router.get(
    "/amount/{entity_id}",
    summary="Get Entity Payment Details",
)
async def get_payment_amount(
    entity_id: int,
    entity_type: str = Query("GST_REGISTRATION"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    entity_type_norm = entity_type.strip().upper()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    cache_key = build_cache_key(
        "payments_config:get_amount",
        entity_id=entity_id,
        entity_type=entity_type_norm,
        emp_id=emp_id,
    )

    pool = await get_db_pool()

    async def _load_payment_amount():
        async with pool.acquire() as conn:
            try:
                customer_id = None
                display_name = ""
                description = ""
                ownership_category = "N/A"

                if entity_type_norm == "GST_REGISTRATION":
                    gst_row = await conn.fetchrow(
                        f"""
                        SELECT id, customer_id, ownership_category, is_active
                        FROM {DB_SCHEMA}.gst_registration
                        WHERE id = $1
                        LIMIT 1
                        """,
                        entity_id,
                    )
                    if not gst_row:
                        raise HTTPException(404, "GST registration not found.")
                    if not gst_row["is_active"]:
                        raise HTTPException(400, "GST registration is inactive.")

                    customer_id = gst_row["customer_id"]
                    ownership_category = (
                        (gst_row["ownership_category"] or "N/A").strip().upper()
                    )
                    display_name = "GST Registration"

                elif entity_type_norm == "GST_FILING":
                    filing_row = await conn.fetchrow(
                        f"""
                        SELECT id, customer_id, filing_frequency, gstin, is_active
                        FROM {DB_SCHEMA}.gst_filings
                        WHERE id = $1
                        LIMIT 1
                        """,
                        entity_id,
                    )
                    if not filing_row:
                        raise HTTPException(404, "GST filing not found.")
                    if not filing_row["is_active"]:
                        raise HTTPException(400, "GST filing is inactive.")

                    customer_id = filing_row["customer_id"]
                    display_name = f"GST Filing ({filing_row['filing_frequency']})"
                    ownership_category = filing_row["filing_frequency"]

                else:
                    raise HTTPException(
                        400,
                        f"Unsupported entity type: {entity_type_norm}",
                    )

                payment_summary = await conn.fetchrow(
                    f"""
                    SELECT
                        (
                            SELECT amount
                            FROM {DB_SCHEMA}.payments
                            WHERE customer_id = $1
                              AND entity_id = $2
                              AND entity_type = $3
                              AND is_active = TRUE
                              AND payment_status != 'CANCELLED'
                            ORDER BY created_at ASC
                            LIMIT 1
                        ) AS original_amount,
                        COALESCE(SUM(discount), 0) AS total_discount,
                        COALESCE(SUM(paid_amount), 0) AS total_paid,
                        (
                            SELECT payment_status
                            FROM {DB_SCHEMA}.payments
                            WHERE customer_id = $1
                              AND entity_id = $2
                              AND entity_type = $3
                              AND is_active = TRUE
                              AND payment_status != 'CANCELLED'
                            ORDER BY created_at DESC
                            LIMIT 1
                        ) AS last_status
                    FROM {DB_SCHEMA}.payments
                    WHERE customer_id = $1
                      AND entity_id = $2
                      AND entity_type = $3
                      AND is_active = TRUE
                      AND payment_status != 'CANCELLED'
                    """,
                    customer_id,
                    entity_id,
                    entity_type_norm,
                )

                if payment_summary["original_amount"] is None:
                    config = await conn.fetchrow(
                        f"""
                        SELECT display_name, amount, description, is_active
                        FROM {DB_SCHEMA}.payment_config
                        WHERE upper(entity_type) = $1
                          AND config_type = 'PRICE'
                          AND (value = $2 OR value = 'DEFAULT')
                        ORDER BY CASE WHEN value = $2 THEN 0 ELSE 1 END ASC
                        LIMIT 1
                        """,
                        entity_type_norm,
                        ownership_category,
                    )

                    if not config:
                        original_amount = 0.0
                        display_name = display_name or entity_type_norm
                        description = f"Initial payment for {display_name}"
                    else:
                        if not config["is_active"]:
                            raise HTTPException(
                                400,
                                "Payment configuration is inactive.",
                            )
                        original_amount = float(config["amount"])
                        display_name = config["display_name"]
                        description = config["description"]

                    total_discount = 0.0
                    total_paid = 0.0

                else:
                    original_amount = float(payment_summary["original_amount"])
                    total_discount = float(
                        payment_summary["total_discount"] or 0
                    )
                    total_paid = float(payment_summary["total_paid"] or 0)
                    last_status = payment_summary["last_status"]

                    if entity_type_norm == "GST_REGISTRATION":
                        display_name = "GST Registration"
                        description = "Remaining payment for GST registration"
                    else:
                        description = f"Remaining payment for {display_name}"

                    if last_status == "PAID":
                        raise HTTPException(
                            409,
                            f"Payment already completed for this {entity_type_norm.lower().replace('_', ' ')}.",
                        )

                net_amount = original_amount - total_discount
                remaining_amount = net_amount - total_paid

                if remaining_amount <= 0 and (
                    original_amount > 0 or total_paid > 0
                ):
                    raise HTTPException(
                        409,
                        f"Payment already completed for this {entity_type_norm.lower().replace('_', ' ')}.",
                    )

                return {
                    "entity_id": entity_id,
                    "entity_type": entity_type_norm,
                    "ownership_category": ownership_category,
                    "display_name": display_name,
                    "original_amount": round(original_amount, 2),
                    "total_discount": round(total_discount, 2),
                    "total_paid": round(total_paid, 2),
                    "net_amount": round(net_amount, 2),
                    "remaining_amount": round(remaining_amount, 2),
                    "payable_amount": round(remaining_amount, 2),
                    "description": description,
                    "request_id": request_id,
                }
            except asyncpg.PostgresError:
                raise HTTPException(500, "Database error.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(500, "Internal server error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_payment_amount,
        ttl_seconds=300,
        tags=["payments_config:get_amount:index"],
    )
