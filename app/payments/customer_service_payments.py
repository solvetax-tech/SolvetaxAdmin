import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status

from app.security.rbac import require_permission
from app.payments.schemas import CustomerServicePaymentIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from app.redis_cache import invalidate_tag as redis_invalidate_tag
import json

router = APIRouter(
    prefix="/api/v1/customer-service-payments",
    tags=["Customer Service Payments"],
)

ENTITY_TYPE = "CUSTOMER_SERVICE"


async def _invalidate_customer_service_payments_cache() -> None:
    await redis_invalidate_tag("registration_payments:filter:index")
    await redis_invalidate_tag("payments_config:get_amount:index")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create payment for a customer_services row",
    description=(
        "Stores `entity_type=CUSTOMER_SERVICE` and `entity_id=customer_services.id` "
        "(covers catalog services linked via `customer_services`)."
    ),
)
async def create_customer_service_payment(
    payload: CustomerServicePaymentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            entity_row = await conn.fetchrow(
                f"""
                SELECT id, customer_id, is_active
                  FROM {DB_SCHEMA}.customer_services
                 WHERE id = $1
                """,
                payload.entity_id,
            )

            if not entity_row:
                raise HTTPException(404, "Customer service not found.")

            if not entity_row["is_active"]:
                raise HTTPException(400, "Customer service is inactive.")

            customer_id = entity_row["customer_id"]

            already_paid = await conn.fetchrow(
                f"""
                SELECT 1
                  FROM {DB_SCHEMA}.payments
                 WHERE customer_id IS NOT DISTINCT FROM $1
                   AND entity_id = $2
                   AND entity_type = $3
                   AND payment_status = 'PAID'
                   AND is_active = TRUE
                 LIMIT 1
                """,
                customer_id,
                payload.entity_id,
                ENTITY_TYPE,
            )

            if already_paid:
                raise HTTPException(409, "Payment already completed.")

            await conn.fetch(
                f"""
                SELECT id
                  FROM {DB_SCHEMA}.payments
                 WHERE customer_id IS NOT DISTINCT FROM $1
                   AND entity_id = $2
                   AND entity_type = $3
                 FOR UPDATE
                """,
                customer_id,
                payload.entity_id,
                ENTITY_TYPE,
            )

            base_row = await conn.fetchrow(
                f"""
                SELECT
                    (
                        SELECT amount
                          FROM {DB_SCHEMA}.payments
                         WHERE customer_id IS NOT DISTINCT FROM $1
                           AND entity_id = $2
                           AND entity_type = $3
                           AND is_active = TRUE
                           AND payment_status != 'CANCELLED'
                         ORDER BY created_at ASC
                         LIMIT 1
                    ) AS original_amount,
                    COALESCE(SUM(discount), 0) AS total_discount
                  FROM {DB_SCHEMA}.payments
                 WHERE customer_id IS NOT DISTINCT FROM $1
                   AND entity_id = $2
                   AND entity_type = $3
                   AND is_active = TRUE
                   AND payment_status != 'CANCELLED'
                """,
                customer_id,
                payload.entity_id,
                ENTITY_TYPE,
            )

            if not base_row or base_row["original_amount"] is None:
                original_amount = float(payload.amount)
                total_discount = 0.0
            else:
                original_amount = float(base_row["original_amount"])
                total_discount = float(base_row["total_discount"] or 0)

            paid_row = await conn.fetchrow(
                f"""
                SELECT COALESCE(SUM(paid_amount), 0) AS total_paid
                  FROM {DB_SCHEMA}.payments
                 WHERE customer_id IS NOT DISTINCT FROM $1
                   AND entity_id = $2
                   AND entity_type = $3
                   AND is_active = TRUE
                   AND payment_status != 'CANCELLED'
                """,
                customer_id,
                payload.entity_id,
                ENTITY_TYPE,
            )

            total_paid = float(paid_row["total_paid"])

            remaining_before_discount = original_amount - total_discount - total_paid

            if remaining_before_discount <= 0:
                raise HTTPException(409, "Payment already completed.")

            new_discount = float(payload.discount or 0)

            if new_discount < 0:
                raise HTTPException(400, "Discount cannot be negative.")

            if new_discount > remaining_before_discount:
                raise HTTPException(
                    400,
                    f"Discount cannot exceed remaining amount ({remaining_before_discount}).",
                )

            total_discount += new_discount

            remaining_after_discount = original_amount - total_discount - total_paid

            paid_amount = float(payload.paid_amount or 0)

            if paid_amount <= 0:
                raise HTTPException(400, "Paid amount must be greater than 0.")

            if paid_amount > remaining_after_discount:
                raise HTTPException(
                    400,
                    f"Paid amount exceeds remaining balance ({remaining_after_discount}).",
                )

            net_amount = original_amount - total_discount

            if paid_amount == remaining_after_discount:
                payment_status = "PAID"
            else:
                payment_status = "PENDING"

            async with conn.transaction():
                payment_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.payments
                    (
                        transaction_id,
                        customer_id,
                        entity_id,
                        entity_type,
                        amount,
                        discount,
                        paid_amount,
                        net_amount,
                        payment_status,
                        remarks,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        NULL, $1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW()
                    )
                    RETURNING *
                    """,
                    customer_id,
                    payload.entity_id,
                    ENTITY_TYPE,
                    original_amount,
                    total_discount,
                    paid_amount,
                    net_amount,
                    payment_status,
                    payload.remarks,
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    emp_id,
                    "CUSTOMER_SERVICE_PAYMENT",
                    payment_row["id"],
                    customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            await _invalidate_customer_service_payments_cache()
            return {
                **dict(payment_row),
                "message": "Customer service payment created successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "Internal server error.")


@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete customer service payment",
)
async def soft_delete_customer_service_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )
    log.info("Incoming customer service payment soft delete | payment_id=%s", payment_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.payments
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    payment_id,
                )

                if not row:
                    raise HTTPException(status_code=404, detail="Payment not found.")

                if row["entity_type"] != ENTITY_TYPE:
                    raise HTTPException(
                        status_code=400,
                        detail="This payment does not belong to customer service.",
                    )

                if not row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Payment already inactive.",
                    )

                if row["payment_status"] == "PAID":
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot delete a completed (PAID) payment.",
                    )

                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.payments
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                     RETURNING *
                    """,
                    payment_id,
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    emp_id,
                    "CUSTOMER_SERVICE_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            await _invalidate_customer_service_payments_cache()

            return {
                **dict(deleted_row),
                "message": "Customer service payment soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during customer service payment soft delete")
            raise HTTPException(status_code=500, detail="Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error during customer service payment soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")


@router.post(
    "/{payment_id}/activate",
    summary="Activate customer service payment",
)
async def activate_customer_service_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                payment_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.payments
                     WHERE id = $1
                     FOR UPDATE
                    """,
                    payment_id,
                )
                if not payment_row:
                    raise HTTPException(404, "Payment not found.")
                if payment_row["entity_type"] != ENTITY_TYPE:
                    raise HTTPException(400, "This payment does not belong to customer service.")
                if payment_row["is_active"]:
                    raise HTTPException(400, "Payment already active.")

                if payment_row["payment_status"] == "PAID":
                    existing_paid = await conn.fetchrow(
                        f"""
                        SELECT id
                          FROM {DB_SCHEMA}.payments
                         WHERE customer_id IS NOT DISTINCT FROM $1
                           AND entity_id = $2
                           AND entity_type = $3
                           AND payment_status = 'PAID'
                           AND is_active = TRUE
                           AND id <> $4
                        """,
                        payment_row["customer_id"],
                        payment_row["entity_id"],
                        payment_row["entity_type"],
                        payment_id,
                    )
                    if existing_paid:
                        raise HTTPException(
                            409,
                            "Another active PAID payment already exists for this customer service.",
                        )

                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.payments
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                     RETURNING *
                    """,
                    payment_id,
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    emp_id,
                    "CUSTOMER_SERVICE_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            await _invalidate_customer_service_payments_cache()
            return {
                **dict(activated_row),
                "message": "Customer service payment activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "Internal server error.")
