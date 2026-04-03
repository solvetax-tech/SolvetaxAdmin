import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import FilingPaymentIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_visibility
from app.logger import logger
from datetime import datetime
import json

router = APIRouter(
    prefix="/api/v1/filing-payments",
    tags=["Filing Payments"]
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing Payment",
)
async def create_gst_filing_payment(
    payload: FilingPaymentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    entity_type = "GST_FILING"

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:

            # --------------------------------------------------
            # 1️⃣ Validate GST Filing
            # --------------------------------------------------

            entity_row = await conn.fetchrow(
                f"""
                SELECT id, customer_id, is_active
                FROM {DB_SCHEMA}.gst_filings
                WHERE id = $1
                """,
                payload.entity_id,
            )

            if not entity_row:
                raise HTTPException(404, "GST filing not found.")

            if not entity_row["is_active"]:
                raise HTTPException(400, "GST filing is inactive.")

            customer_id = entity_row["customer_id"]

            # --------------------------------------------------
            # 2️⃣ Reject if already PAID
            # --------------------------------------------------
            already_paid = await conn.fetchrow(
                f"""
                SELECT 1
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                AND payment_status = 'PAID'
                AND is_active = TRUE
                LIMIT 1
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            if already_paid:
                raise HTTPException(409, "Payment already completed.")

            # --------------------------------------------------
            # 3️⃣ LOCK rows
            # --------------------------------------------------

            await conn.fetch(
                f"""
                SELECT id
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                FOR UPDATE
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            # --------------------------------------------------
            # 4️⃣ Fetch ORIGINAL + TOTAL DISCOUNT
            # --------------------------------------------------
            base_row = await conn.fetchrow(
                f"""
                SELECT
                    (
                        SELECT amount
                        FROM {DB_SCHEMA}.registration_payments
                        WHERE
                            customer_id = $1
                        AND entity_id = $2
                        AND entity_type = $3
                        AND is_active = TRUE
                        AND payment_status != 'CANCELLED'
                        ORDER BY created_at ASC
                        LIMIT 1
                    ) AS original_amount,
                    COALESCE(SUM(discount), 0) AS total_discount
                FROM {DB_SCHEMA}.registration_payments
                WHERE
                    customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                AND is_active = TRUE
                AND payment_status != 'CANCELLED'
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            if not base_row or base_row["original_amount"] is None:
                original_amount = float(payload.amount)
                total_discount = 0.0
            else:
                original_amount = float(base_row["original_amount"])
                total_discount = float(base_row["total_discount"] or 0)

            # --------------------------------------------------
            # 5️⃣ Total paid
            # --------------------------------------------------
            paid_row = await conn.fetchrow(
                f"""
                SELECT COALESCE(SUM(paid_amount),0) AS total_paid
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                AND is_active = TRUE
                AND payment_status != 'CANCELLED'
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )
            total_paid = float(paid_row["total_paid"])

            # --------------------------------------------------
            # 6️⃣ Remaining BEFORE discount
            # --------------------------------------------------
            remaining_before_discount = original_amount - total_discount - total_paid
            if remaining_before_discount <= 0:
                raise HTTPException(409, "Payment already completed.")

            # --------------------------------------------------
            # 7️⃣ Apply NEW discount
            # --------------------------------------------------

            new_discount = float(payload.discount or 0)
            paid_amount = float(payload.paid_amount or 0)

            if new_discount < 0:
                raise HTTPException(400, "Discount cannot be negative.")

            if new_discount > remaining_before_discount:
                raise HTTPException(
                    400,
                    f"Discount cannot exceed remaining amount ({remaining_before_discount}).",
                )

            total_discount += new_discount

            # --------------------------------------------------
            # 8️⃣ Remaining AFTER discount
            # --------------------------------------------------
            remaining_after_discount = original_amount - total_discount - total_paid
            if paid_amount <= 0:
                raise HTTPException(400, "Paid amount must be greater than 0.")

            if paid_amount > remaining_after_discount:
                raise HTTPException(
                    400,
                    f"Paid amount exceeds remaining balance ({remaining_after_discount}).",
                )

            # --------------------------------------------------
            # 9️⃣ Net amount + status
            # --------------------------------------------------
            net_amount = original_amount - total_discount

            if paid_amount == remaining_after_discount:
                payment_status = "PAID"
            else:
                payment_status = "PENDING"

            # --------------------------------------------------
            # 🔟 INSERT
            # --------------------------------------------------

            async with conn.transaction():

                payment_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_payments
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
                        NULL,$1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),NOW()
                    )
                    RETURNING *
                    """,
                    customer_id,
                    payload.entity_id,
                    entity_type,
                    original_amount,
                    total_discount,
                    paid_amount,
                    net_amount,
                    payment_status,
                    payload.remarks,
                )

                # --------------------------------------------------
                # Version Audit
                # --------------------------------------------------

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
                    "GST_FILING_PAYMENT",
                    payment_row["id"],
                    customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            return {
                **dict(payment_row),
                "message": "GST filing payment created successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            raise HTTPException(500, "Internal server error.")


# -------------------------------------------------------------------
# LIST FILING PAYMENTS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Filing Payments (Table Only)",
)
async def list_filing_payments(
    payment_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    payment_status: Optional[str] = None,
    payment_mode: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    amount: Optional[float] = None,
    amount_operator: Optional[str] = None,
    min_remaining: Optional[float] = None,
    max_remaining: Optional[float] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "from_date cannot be greater than to_date.")

    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(400, "min_amount cannot be greater than max_amount.")

    if min_remaining is not None and max_remaining is not None and min_remaining > max_remaining:
        raise HTTPException(400, "min_remaining cannot be greater than max_remaining.")

    allowed_operators = {">", "<", "="}
    if amount_operator and amount_operator not in allowed_operators:
        raise HTTPException(400, "Invalid amount_operator. Allowed values are > < =")

    allowed_status = {"PENDING", "PAID", "CANCELLED"}
    if payment_status and payment_status.strip():
        payment_status = payment_status.strip().upper()
        if payment_status not in allowed_status:
            raise HTTPException(400, "Invalid payment_status value.")

    allowed_modes = {"CASH", "UPI", "BANK_TRANSFER", "CARD", "GATEWAY"}
    if payment_mode and payment_mode.strip():
        payment_mode = payment_mode.strip().upper()
        if payment_mode not in allowed_modes:
            raise HTTPException(400, "Invalid payment_mode value.")

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error.")

    try:
        conditions = ["rp.entity_type = 'GST_FILING'"]
        values = []
        param_index = 1

        if payment_id is not None:
            conditions.append(f"rp.id = ${param_index}")
            values.append(payment_id)
            param_index += 1
        if customer_id is not None:
            conditions.append(f"rp.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1
        if entity_id is not None:
            conditions.append(f"rp.entity_id = ${param_index}")
            values.append(entity_id)
            param_index += 1
        if entity_type and entity_type.strip():
            conditions.append(f"rp.entity_type = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1
        if payment_status:
            conditions.append(f"rp.payment_status = ${param_index}")
            values.append(payment_status)
            param_index += 1
        if payment_mode:
            conditions.append(f"rp.payment_mode = ${param_index}")
            values.append(payment_mode)
            param_index += 1
        if min_amount is not None:
            conditions.append(f"rp.net_amount >= ${param_index}")
            values.append(min_amount)
            param_index += 1
        if max_amount is not None:
            conditions.append(f"rp.net_amount <= ${param_index}")
            values.append(max_amount)
            param_index += 1
        if min_remaining is not None:
            conditions.append(f"rp.remaining_amount >= ${param_index}")
            values.append(min_remaining)
            param_index += 1
        if max_remaining is not None:
            conditions.append(f"rp.remaining_amount <= ${param_index}")
            values.append(max_remaining)
            param_index += 1
        if amount is not None:
            operator = amount_operator if amount_operator else "="
            conditions.append(f"rp.net_amount {operator} ${param_index}")
            values.append(amount)
            param_index += 1
        if is_active is not None:
            conditions.append(f"rp.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("rp.is_active = TRUE")
        if from_date:
            conditions.append(f"rp.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1
        if to_date:
            conditions.append(f"rp.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        visibility_sql, visibility_values, param_index = build_customer_visibility(
            role,
            int(current_emp_id) if str(current_emp_id).isdigit() else None,
            param_index,
            DB_SCHEMA,
        )
        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.registration_payments rp
            LEFT JOIN {DB_SCHEMA}.customers c
                   ON rp.customer_id = c.customer_id
            {where_clause}
        """

        data_sql = f"""
            SELECT
                rp.*,
                rp.remaining_amount,
                c.full_name,
                c.rm_id,
                c.op_id,
                e_rm.first_name AS rm_name,
                e_op.first_name AS op_name
            FROM {DB_SCHEMA}.registration_payments rp
            LEFT JOIN {DB_SCHEMA}.customers c
                   ON rp.customer_id = c.customer_id
            LEFT JOIN {DB_SCHEMA}.employees e_rm
                   ON c.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_op
                   ON c.op_id = e_op.emp_id
            {where_clause}
            ORDER BY rp.created_at DESC, rp.id DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total_count = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        return {
            "data": [dict(row) for row in rows],
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    except asyncpg.PostgresError:
        raise HTTPException(500, "Database error occurred during filtering.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Internal server error.")


# -------------------------------------------------------------------
# SOFT DELETE FILING PAYMENT
# -------------------------------------------------------------------
@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete Filing Payment",
)
async def soft_delete_filing_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    payment_id,
                )
                if not row:
                    raise HTTPException(404, "Filing payment not found.")
                if row["entity_type"] != "GST_FILING":
                    raise HTTPException(400, "This payment does not belong to GST filing.")
                if not row["is_active"]:
                    raise HTTPException(400, "Filing payment already inactive.")
                if row["payment_status"] == "PAID":
                    raise HTTPException(400, "Cannot delete a completed (PAID) payment.")

                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_payments
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
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_FILING_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            return {
                **dict(deleted_row),
                "message": "GST filing payment soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Foreign key constraint violation.")
        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format.")
        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "Internal server error.")


# -------------------------------------------------------------------
# ACTIVATE FILING PAYMENT
# -------------------------------------------------------------------
@router.post(
    "/{payment_id}/activate",
    summary="Activate Filing Payment",
)
async def activate_filing_payment(
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
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    payment_id,
                )
                if not payment_row:
                    raise HTTPException(404, "Filing payment not found.")
                if payment_row["entity_type"] != "GST_FILING":
                    raise HTTPException(400, "This payment does not belong to GST filing.")
                if payment_row["is_active"]:
                    raise HTTPException(400, "Filing payment already active.")

                if payment_row["payment_status"] == "PAID":
                    existing_paid = await conn.fetchrow(
                        f"""
                        SELECT id
                        FROM {DB_SCHEMA}.registration_payments
                        WHERE customer_id = $1
                        AND entity_id = $2
                        AND entity_type = $3
                        AND payment_status = 'PAID'
                        AND is_active = TRUE
                        """,
                        payment_row["customer_id"],
                        payment_row["entity_id"],
                        payment_row["entity_type"],
                    )
                    if existing_paid:
                        raise HTTPException(409, "Another active PAID payment already exists for this filing.")

                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_payments
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
                    "GST_FILING_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            return {
                **dict(activated_row),
                "message": "GST filing payment activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Foreign key constraint violation.")
        except asyncpg.exceptions.DataError:
            raise HTTPException(400, "Invalid data format.")
        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error occurred.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "Internal server error.")
