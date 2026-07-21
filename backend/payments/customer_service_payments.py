import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status

from backend.security.rbac import require_permission
from backend.payments.schemas import CustomerServicePaymentIn
from backend.payments.payment_ledger import PaymentLedgerError
from backend.payments.payment_ledger_db import (
    assert_payment_visible,
    fetch_entity_payment_totals,
    has_completed_payment,
    insert_payment_from_ledger,
    ledger_error_to_http,
    lock_entity_payment_rows,
    resolve_ledger_for_create,
)
from backend.utils import get_db_pool, DB_SCHEMA, generate_uuid
from backend.logger import logger
from backend.payments.payment_cache_invalidation import invalidate_payment_related_caches
import json

router = APIRouter(
    prefix="/api/v1/customer-service-payments",
    tags=["Customer Service Payments"],
)

ENTITY_TYPE = "CUSTOMER_SERVICE"


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

            # Open the transaction BEFORE taking the FOR UPDATE lock so the lock
            # is held through the insert. asyncpg runs statements outside an
            # explicit transaction in autocommit mode, which would release the
            # lock immediately and let two concurrent submits both pass the
            # balance check and double-insert against the same entity.
            async with conn.transaction():
                await lock_entity_payment_rows(
                    conn, DB_SCHEMA, customer_id, payload.entity_id, ENTITY_TYPE
                )

                # Re-check completion under the lock: a concurrent request may
                # have completed payment between our first check and this insert.
                if await has_completed_payment(
                    conn, DB_SCHEMA, customer_id, payload.entity_id, ENTITY_TYPE
                ):
                    raise HTTPException(409, "Payment already completed.")

                totals = await fetch_entity_payment_totals(
                    conn,
                    DB_SCHEMA,
                    customer_id,
                    payload.entity_id,
                    ENTITY_TYPE,
                    first_payment_amount=float(payload.amount),
                )

                try:
                    ledger = resolve_ledger_for_create(
                        totals,
                        new_discount=float(payload.discount or 0),
                        paid_amount=float(payload.paid_amount or 0),
                    )
                except PaymentLedgerError as exc:
                    raise ledger_error_to_http(exc) from exc

                payment_row = await insert_payment_from_ledger(
                    conn,
                    DB_SCHEMA,
                    customer_id=customer_id,
                    entity_id=payload.entity_id,
                    entity_type=ENTITY_TYPE,
                    ledger=ledger,
                    remarks=payload.remarks,
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

                # Payment fully settled ⇒ close the customer service's open
                # follow-up (the RM no longer needs to chase payment). completed_at
                # is required by chk_followup_completed_fields when COMPLETED.
                if payment_row["payment_status"] == "PAID":
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.customer_services
                           SET followup_status = 'COMPLETED',
                               completed_at = COALESCE(completed_at, NOW()),
                               updated_at = NOW()
                         WHERE id = $1
                           AND followup_status IN ('PENDING', 'MISSED')
                        """,
                        payload.entity_id,
                    )

            await invalidate_payment_related_caches(customer_service=True)
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
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

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

                # IDOR guard: only mutate a payment the caller can see.
                await assert_payment_visible(conn, role_norm, emp_id, payment_id)

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

                # Admins may delete completed (PAID) payments; soft-delete is
                # recoverable via /activate, so there is no PAID guard here.

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

            await invalidate_payment_related_caches(customer_service=True)

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
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

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
                # IDOR guard: only mutate a payment the caller can see.
                await assert_payment_visible(conn, role_norm, emp_id, payment_id)
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

            await invalidate_payment_related_caches(customer_service=True)
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
