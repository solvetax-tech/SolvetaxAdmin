import asyncpg
import json
from fastapi import APIRouter, Depends, HTTPException, status

from backend.logger import logger
from backend.payments.payment_cache_invalidation import invalidate_payment_related_caches
from backend.payments.schemas import FilingPaymentIn
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
from backend.security.rbac import require_permission
from backend.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(
    prefix="/api/v1/income-tax-payments",
    tags=["Income Tax Payments"],
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Income Tax Payment",
)
async def create_income_tax_payment(
    payload: FilingPaymentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    entity_type = "INCOME_TAX"

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            entity_row = await conn.fetchrow(
                f"""
                SELECT id, is_active
                FROM {DB_SCHEMA}.income_tax
                WHERE id = $1
                """,
                payload.entity_id,
            )
            if not entity_row:
                raise HTTPException(404, "Income tax record not found.")
            if not entity_row["is_active"]:
                raise HTTPException(400, "Income tax record is inactive.")

            # income_tax has no customer_id column and no validated customer link,
            # so a client-supplied customer_id would let the same ITR be billed
            # twice under different ids (each id forms its own ledger). Scope the
            # entire ledger by the ITR id only (customer_id = None) so an ITR can
            # be fully paid exactly once. This flows through has_completed_payment,
            # lock, totals and insert consistently.
            customer_id = None

            # Open the transaction BEFORE taking the FOR UPDATE lock so the lock
            # is held through the insert. asyncpg runs statements outside an
            # explicit transaction in autocommit mode, which would release the
            # lock immediately and let two concurrent submits both pass the
            # balance check and double-insert against the same entity.
            async with conn.transaction():
                await lock_entity_payment_rows(
                    conn, DB_SCHEMA, customer_id, payload.entity_id, entity_type
                )

                # Re-check completion under the lock: a concurrent request may
                # have completed payment between our first check and this insert.
                if await has_completed_payment(
                    conn, DB_SCHEMA, customer_id, payload.entity_id, entity_type
                ):
                    raise HTTPException(409, "Payment already completed.")

                totals = await fetch_entity_payment_totals(
                    conn,
                    DB_SCHEMA,
                    customer_id,
                    payload.entity_id,
                    entity_type,
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
                    entity_type=entity_type,
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
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX_PAYMENT",
                    payment_row["id"],
                    customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            await invalidate_payment_related_caches(
                income_tax_id=int(payload.entity_id),
                crm=True,
            )
            return {
                **dict(payment_row),
                "message": "Income tax payment created successfully.",
                "request_id": request_id,
            }
        except asyncpg.PostgresError:
            logger.exception("Database error while creating income tax payment")
            raise HTTPException(500, "Database error.")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unexpected error while creating income tax payment")
            raise HTTPException(500, "Internal server error.")


@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete Income Tax Payment",
)
async def soft_delete_income_tax_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

    pool = await get_db_pool()
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
                    raise HTTPException(404, "Income tax payment not found.")
                # IDOR guard: only mutate a payment the caller can see.
                await assert_payment_visible(
                    conn, role_norm, emp_id, payment_id, "Income tax payment not found.",
                )
                if row["entity_type"] != "INCOME_TAX":
                    raise HTTPException(400, "This payment does not belong to income tax.")
                if not row["is_active"]:
                    raise HTTPException(400, "Income tax payment already inactive.")
                if row["payment_status"] == "PAID":
                    raise HTTPException(400, "Cannot delete a completed (PAID) payment.")

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
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            await invalidate_payment_related_caches(
                income_tax_id=int(deleted_row["entity_id"]),
                crm=True,
            )
            return {
                **dict(deleted_row),
                "message": "Income tax payment soft deleted successfully.",
                "request_id": request_id,
            }
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Foreign key constraint violation.")
        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format.")
        except asyncpg.PostgresError:
            logger.exception("Database error while soft deleting income tax payment")
            raise HTTPException(500, "Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unexpected error while soft deleting income tax payment")
            raise HTTPException(500, "Internal server error.")


@router.post(
    "/{payment_id}/activate",
    summary="Activate Income Tax Payment",
)
async def activate_income_tax_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

    pool = await get_db_pool()
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
                    raise HTTPException(404, "Income tax payment not found.")
                # IDOR guard: only mutate a payment the caller can see.
                await assert_payment_visible(
                    conn, role_norm, emp_id, payment_id, "Income tax payment not found.",
                )
                if payment_row["entity_type"] != "INCOME_TAX":
                    raise HTTPException(400, "This payment does not belong to income tax.")
                if payment_row["is_active"]:
                    raise HTTPException(400, "Income tax payment already active.")

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
                        raise HTTPException(409, "Another active PAID payment already exists for this income tax record.")

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
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            await invalidate_payment_related_caches(
                income_tax_id=int(activated_row["entity_id"]),
                crm=True,
            )
            return {
                **dict(activated_row),
                "message": "Income tax payment activated successfully.",
                "request_id": request_id,
            }
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Foreign key constraint violation.")
        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format.")
        except asyncpg.PostgresError:
            logger.exception("Database error while activating income tax payment")
            raise HTTPException(500, "Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unexpected error while activating income tax payment")
            raise HTTPException(500, "Internal server error.")
