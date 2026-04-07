import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_visibility
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Registration Payments"]
)

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Payment",
)
async def create_registration_payment(
    payload: RegistrationPaymentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    entity_type = "GST_REGISTRATION"

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:

            # --------------------------------------------------
            # 1️⃣ Validate GST Registration
            # --------------------------------------------------

            entity_row = await conn.fetchrow(
                f"""
                SELECT id, customer_id, is_active
                FROM {DB_SCHEMA}.gst_registration
                WHERE id = $1
                """,
                payload.entity_id,
            )

            if not entity_row:
                raise HTTPException(404, "GST registration not found.")

            if not entity_row["is_active"]:
                raise HTTPException(400, "GST registration is inactive.")

            customer_id = entity_row["customer_id"]

            # --------------------------------------------------
            # 2️⃣ Reject if already PAID
            # --------------------------------------------------

            already_paid = await conn.fetchrow(
                f"""
                SELECT 1
                FROM {DB_SCHEMA}.payments
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
            # 3️⃣ LOCK rows (race condition safety)
            # --------------------------------------------------

            await conn.fetch(
                f"""
                SELECT id
                FROM {DB_SCHEMA}.payments
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
            # 4️⃣ Fetch ORIGINAL + TOTAL DISCOUNT (FIXED)
            # --------------------------------------------------

            base_row = await conn.fetchrow(
                f"""
                SELECT
                    (
                        SELECT amount
                        FROM {DB_SCHEMA}.payments
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

                FROM {DB_SCHEMA}.payments
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

            # First payment
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
                FROM {DB_SCHEMA}.payments
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

            paid_amount = float(payload.paid_amount or 0)

            if paid_amount <= 0:
                raise HTTPException(400, "Paid amount must be greater than 0.")

            if paid_amount > remaining_after_discount:
                raise HTTPException(
                    400,
                    f"Paid amount exceeds remaining balance ({remaining_after_discount}).",
                )

            # --------------------------------------------------
            # 9️⃣ Net amount
            # --------------------------------------------------

            net_amount = original_amount - total_discount

            # --------------------------------------------------
            # 🔟 Status
            # --------------------------------------------------

            if paid_amount == remaining_after_discount:
                payment_status = "PAID"
            else:
                payment_status = "PENDING"

            # --------------------------------------------------
            # 1️⃣1️⃣ INSERT
            # --------------------------------------------------

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
                    "GST_REGISTRATION_PAYMENT",
                    payment_row["id"],
                    customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            # --------------------------------------------------
            # RESPONSE
            # --------------------------------------------------

            return {
                **dict(payment_row),
                "message": "Payment created successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            raise HTTPException(500, "Internal server error.")
# -------------------------------------------------------------------
# LIST REGISTRATION PAYMENTS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter payments (unified ledger)",
    description=(
        "Lists rows from `registration_payments` with the same filters and joins for all flows. "
        "Pass `entity_type=GST_REGISTRATION` or `entity_type=GST_FILING` to match the old scoped lists; "
        "omit `entity_type` to return every payment type."
    ),
    responses={
        200: {"description": "Payments filtered successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_registration_payments(
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

    # NEW FILTER (Remaining amount)
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

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming payments dynamic_filter | limit=%s offset=%s entity_type=%s",
        limit,
        offset,
        entity_type,
    )

    # --------------------------------------------------
    # Date Validation
    # --------------------------------------------------

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    # --------------------------------------------------
    # Amount Range Validation
    # --------------------------------------------------

    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(
            status_code=400,
            detail="min_amount cannot be greater than max_amount.",
        )

    # --------------------------------------------------
    # Remaining Amount Validation (NEW)
    # --------------------------------------------------

    if min_remaining is not None and max_remaining is not None and min_remaining > max_remaining:
        raise HTTPException(
            status_code=400,
            detail="min_remaining cannot be greater than max_remaining.",
        )

    # --------------------------------------------------
    # Operator Validation
    # --------------------------------------------------

    ALLOWED_OPERATORS = {">", "<", "="}

    if amount_operator and amount_operator not in ALLOWED_OPERATORS:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount_operator. Allowed values are > < =",
        )

    # --------------------------------------------------
    # Enum Validation
    # --------------------------------------------------

    ALLOWED_STATUS = {
        "PENDING",
        "PAID",
        "CANCELLED",
    }

    ALLOWED_MODES = {
        "CASH",
        "UPI",
        "BANK_TRANSFER",
        "CARD",
        "GATEWAY",
    }

    if payment_status and payment_status.strip():

        payment_status = payment_status.strip().upper()

        if payment_status not in ALLOWED_STATUS:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_status value.",
            )

    if payment_mode and payment_mode.strip():

        payment_mode = payment_mode.strip().upper()

        if payment_mode not in ALLOWED_MODES:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_mode value.",
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

        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Exact Match Filters
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Net Amount Range Filtering
        # --------------------------------------------------

        if min_amount is not None:
            conditions.append(f"rp.net_amount >= ${param_index}")
            values.append(min_amount)
            param_index += 1

        if max_amount is not None:
            conditions.append(f"rp.net_amount <= ${param_index}")
            values.append(max_amount)
            param_index += 1

        # --------------------------------------------------
        # Remaining Amount Filtering (NEW)
        # --------------------------------------------------

        if min_remaining is not None:
            conditions.append(f"rp.remaining_amount >= ${param_index}")
            values.append(min_remaining)
            param_index += 1

        if max_remaining is not None:
            conditions.append(f"rp.remaining_amount <= ${param_index}")
            values.append(max_remaining)
            param_index += 1

        # --------------------------------------------------
        # Net Amount Comparison Filtering
        # --------------------------------------------------

        if amount is not None:

            operator = amount_operator if amount_operator else "="

            conditions.append(f"rp.net_amount {operator} ${param_index}")
            values.append(amount)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"rp.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1

        elif not include_inactive:
            conditions.append("rp.is_active = TRUE")

        # --------------------------------------------------
        # Date Filters
        # --------------------------------------------------

        if from_date:
            conditions.append(f"rp.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"rp.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY (CUSTOMER → PAYMENT)
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_customer_visibility(
            role,
            int(current_emp_id) if str(current_emp_id).isdigit() else None,
            param_index,
            DB_SCHEMA,
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT QUERY
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.payments rp
            LEFT JOIN {DB_SCHEMA}.customers c
                   ON rp.customer_id = c.customer_id
            {where_clause}
        """

        # --------------------------------------------------
        # DATA QUERY
        # --------------------------------------------------

        data_sql = f"""
            SELECT
                rp.*,
                rp.remaining_amount,   -- NEW FIELD
                c.full_name,
                c.rm_id,
                c.op_id,
                e_rm.first_name AS rm_name,
                e_op.first_name AS op_name
            FROM {DB_SCHEMA}.payments rp
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

        log.info(
            "Payments dynamic_filter success | returned=%s total=%s",
            len(rows),
            total_count,
        )

        return {
            "data": [dict(row) for row in rows],
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    except asyncpg.PostgresError as e:

        log.error(
            "Database error during payments filtering | error=%s",
            str(e),
            exc_info=True,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error occurred during filtering.",
        )

    except HTTPException:
        raise

    except Exception:

        log.exception("Unexpected error during payments filtering")

        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION PAYMENT (Production Ready + Audit)
# -------------------------------------------------------------------
@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete Registration Payment",
    responses={
        200: {"description": "Registration payment soft deleted successfully."},
        400: {"description": "Validation failed or already inactive."},
        404: {"description": "Registration payment not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_payment(
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

    log.info("Incoming payment soft delete | payment_id=%s", payment_id)

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
                    raise HTTPException(
                        status_code=404,
                        detail="Registration payment not found.",
                    )

                if not row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration payment already inactive.",
                    )

                # Optional protection (recommended)
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
                    "GST_REGISTRATION_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info(
                "Registration payment soft deleted successfully | payment_id=%s",
                payment_id,
            )

            return {
                **dict(deleted_row),
                "message": "Registration payment soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during payment soft delete")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during payment soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# ACTIVATE REGISTRATION PAYMENT (Production Ready + Audit)
# -------------------------------------------------------------------
@router.post(
    "/{payment_id}/activate",
    summary="Activate Registration Payment",
    responses={
        200: {"description": "Registration payment activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "Registration payment not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_registration_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming payment activation | payment_id=%s", payment_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

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
                    raise HTTPException(
                        status_code=404,
                        detail="Registration payment not found.",
                    )

                if payment_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration payment already active.",
                    )

                # --------------------------------------------------
                # Prevent duplicate active PAID payment
                # --------------------------------------------------
                if payment_row["payment_status"] == "PAID":

                    existing_paid = await conn.fetchrow(
                        f"""
                        SELECT id
                        FROM {DB_SCHEMA}.payments
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
                        raise HTTPException(
                            status_code=409,
                            detail="Another active PAID payment already exists for this registration.",
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
                    "GST_REGISTRATION_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info(
                "Registration payment activated successfully | payment_id=%s",
                payment_id,
            )

            return {
                **dict(activated_row),
                "message": "Registration payment activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during payment activation")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during payment activation")
            raise HTTPException(status_code=500, detail="Internal server error.")
