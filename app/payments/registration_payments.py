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
    prefix="/api/v1/payments",
    tags=["Registration Payments"]
)
# -------------------------------------------------------------------
# CREATE REGISTRATION PAYMENT (Production Standard + Version Audit + IST)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Payment",
    responses={
        201: {"description": "Registration payment created successfully."},
        400: {"description": "Validation failed or GST not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_payment(
    payload: RegistrationPaymentIn,
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

    log.info(
        "Incoming Registration Payment create | gst_registration_id=%s | ownership_category=%s",
        payload.entity_id,
        payload.ownership_category,
    )

    # --------------------------------------------------
    # IST Timestamp
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT id,
                           customer_id,
                           is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                     LIMIT 1
                    """,
                    payload.entity_id,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration not found.",
                    )

                if not gst_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Derive Customer From GST
                # --------------------------------------------------
                derived_customer_id = gst_row["customer_id"]

                # --------------------------------------------------
                # 3️⃣ Fetch Amount From payment_config
                # --------------------------------------------------
                amount_value = await conn.fetchval(
                    """
                    SELECT amount
                    FROM solvetax.payment_config
                    WHERE entity_type = 'GST_REGISTRATION'
                    AND value = $1
                    AND is_active = TRUE
                    LIMIT 1
                    """,
                    payload.ownership_category,
                )

                if not amount_value:
                    raise HTTPException(
                        status_code=400,
                        detail="Payment configuration not found for selected ownership category.",
                    )

                # --------------------------------------------------
                # 4️⃣ Insert Registration Payment
                # --------------------------------------------------
                payment_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_payments (
                        transaction_id,
                        customer_id,
                        entity_id,
                        entity_type,
                        amount,
                        discount,
                        paid_amount,
                        remarks,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        NULL,$1,$2,$3,$4,$5,$6,$7,$8,$9
                    )
                    RETURNING *
                    """,
                    derived_customer_id,
                    payload.entity_id,
                    "GST_REGISTRATION",
                    amount_value,
                    payload.discount or 0,
                    payload.paid_amount or 0,
                    payload.remarks,
                    now,
                    now,
                )

                if not payment_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration payment creation failed.",
                    )

                # --------------------------------------------------
                # 5️⃣ Version Audit Insert
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
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
                    "REGISTRATION_PAYMENT",
                    payment_row["id"],
                    derived_customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            log.info(
                "Registration payment created successfully | payment_id=%s",
                payment_row["id"],
            )

            return {
                **dict(payment_row),
                "message": "Registration payment created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "registration_payments_transaction_id_key":
                    "Transaction ID already exists.",
            }

            log.warning(
                "Unique constraint violation | constraint=%s",
                constraint,
                exc_info=True,
            )

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_amount_positive": "Amount cannot be negative.",
                "chk_discount_positive": "Discount cannot be negative.",
                "chk_paid_amount_positive": "Paid amount cannot be negative.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # GENERAL DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:
            log.error("Database error | %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during Registration Payment creation")
            raise HTTPException(status_code=500, detail="Internal server error.")
# -------------------------------------------------------------------
# LIST REGISTRATION PAYMENTS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Registration Payments (Table Only)",
    responses={
        200: {"description": "Registration payments filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
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

    # --------------------------------------------------
    # NEW FILTER PARAMETERS (ADDED)
    # --------------------------------------------------
    amount: Optional[float] = None,
    amount_operator: Optional[str] = None,
    remaining_amount: Optional[float] = None,
    remaining_amount_operator: Optional[str] = None,

    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Enterprise Registration Payment Filtering

    ✔ Filters only from registration_payments table
    ✔ Supports entity_id filtering (GST safe)
    ✔ Supports status filtering
    ✔ Supports amount range filtering
    ✔ Active filtering pattern aligned
    ✔ Pagination safe
    ✔ Structured logging
    ✔ Enum validation added
    ✔ Range validation added
    ✔ NEW: amount comparison filters
    ✔ NEW: remaining_amount comparison filters
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming registration payments filter | limit=%s offset=%s",
        limit,
        offset,
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
    if (
        min_amount is not None
        and max_amount is not None
        and min_amount > max_amount
    ):
        raise HTTPException(
            status_code=400,
            detail="min_amount cannot be greater than max_amount.",
        )

    # --------------------------------------------------
    # Operator Validation (NEW)
    # --------------------------------------------------
    ALLOWED_OPERATORS = {">", "<", "="}

    if amount_operator and amount_operator not in ALLOWED_OPERATORS:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount_operator. Allowed values are > < =",
        )

    if remaining_amount_operator and remaining_amount_operator not in ALLOWED_OPERATORS:
        raise HTTPException(
            status_code=400,
            detail="Invalid remaining_amount_operator. Allowed values are > < =",
        )

    # --------------------------------------------------
    # Enum Validation
    # --------------------------------------------------
    ALLOWED_STATUS = {
        "PENDING",
        "PARTIAL_PAID",
        "PAID",
        "FAILED",
        "CANCELLED",
        "REFUNDED",
    }

    ALLOWED_MODES = {
        "CASH",
        "UPI",
        "BANK_TRANSFER",
        "CARD",
        "GATEWAY",
    }

    if payment_status and payment_status.strip():
        status_clean = payment_status.strip().upper()
        if status_clean not in ALLOWED_STATUS:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_status value.",
            )
        payment_status = status_clean

    if payment_mode and payment_mode.strip():
        mode_clean = payment_mode.strip().upper()
        if mode_clean not in ALLOWED_MODES:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_mode value.",
            )
        payment_mode = mode_clean

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
            conditions.append(f"id = ${param_index}")
            values.append(payment_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if entity_id is not None:
            conditions.append(f"entity_id = ${param_index}")
            values.append(entity_id)
            param_index += 1

        if entity_type and entity_type.strip():
            conditions.append(f"entity_type = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1

        if payment_status:
            conditions.append(f"payment_status = ${param_index}")
            values.append(payment_status)
            param_index += 1

        if payment_mode:
            conditions.append(f"payment_mode = ${param_index}")
            values.append(payment_mode)
            param_index += 1

        # --------------------------------------------------
        # Amount Range Filtering
        # --------------------------------------------------

        if min_amount is not None:
            conditions.append(f"net_amount >= ${param_index}")
            values.append(min_amount)
            param_index += 1

        if max_amount is not None:
            conditions.append(f"net_amount <= ${param_index}")
            values.append(max_amount)
            param_index += 1

        # --------------------------------------------------
        # NEW: Amount Operator Filtering
        # --------------------------------------------------

        if amount is not None:
            operator = amount_operator if amount_operator else "="
            conditions.append(f"amount {operator} ${param_index}")
            values.append(amount)
            param_index += 1

        # --------------------------------------------------
        # NEW: Remaining Amount Operator Filtering
        # --------------------------------------------------

        if remaining_amount is not None:
            operator = remaining_amount_operator if remaining_amount_operator else "="
            conditions.append(f"remaining_amount {operator} ${param_index}")
            values.append(remaining_amount)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filters
        # --------------------------------------------------

        if from_date:
            conditions.append(f"created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.registration_payments
              {where_clause}
        """

        data_sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.registration_payments
              {where_clause}
             ORDER BY created_at DESC, id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total_count = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "Registration payments filter success | returned=%s total=%s",
            len(rows),
            total_count,
        )

        return {
            "data": [dict(row) for row in rows],
            "total": total_count,
            "limit": limit,
            "offset": offset,
        }

    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration payments filtering | error=%s",
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
        log.exception("Unexpected error during registration payments filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# EDIT REGISTRATION PAYMENT (Discount / Paid Amount / Remarks Only)
# -------------------------------------------------------------------
@router.post(
    "/{payment_id}/edit",
    summary="Edit Registration Payment",
    responses={
        200: {"description": "Registration payment updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "Payment not found or inactive."},
        409: {"description": "Duplicate field value or state conflict."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_payment(
    payment_id: int,
    payload: RegistrationPaymentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming Registration Payment edit | payment_id=%s", payment_id)

    # --------------------------------------------------
    # Extract Update Data
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="No editable fields provided.")

    # --------------------------------------------------
    # Normalize Input
    # --------------------------------------------------
    if "discount" in update_data and update_data["discount"] is not None:
        if update_data["discount"] < 0:
            raise HTTPException(status_code=400, detail="Discount cannot be negative.")

    if "paid_amount" in update_data and update_data["paid_amount"] is not None:
        if update_data["paid_amount"] < 0:
            raise HTTPException(status_code=400, detail="Paid amount cannot be negative.")

    if "remarks" in update_data and update_data["remarks"]:
        update_data["remarks"] = update_data["remarks"].strip()

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # Fetch Existing Row (Row Lock)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    AND is_active = TRUE
                    FOR UPDATE
                    """,
                    payment_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration payment not found or inactive.",
                    )

                # --------------------------------------------------
                # Business Validations
                # --------------------------------------------------

                new_discount = update_data.get("discount", old_row["discount"])
                new_paid = update_data.get("paid_amount", old_row["paid_amount"])

                if new_discount > old_row["amount"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Discount cannot exceed original amount.",
                    )

                new_net_amount = old_row["amount"] - new_discount

                if new_paid > new_net_amount:
                    raise HTTPException(
                        status_code=400,
                        detail="Paid amount cannot exceed net amount.",
                    )

                # --------------------------------------------------
                # Detect No Change
                # --------------------------------------------------
                no_change = True
                for k, v in update_data.items():
                    if k in old_row and old_row[k] != v:
                        no_change = False
                        break

                if no_change:
                    raise HTTPException(
                        status_code=400,
                        detail="No changes detected to update.",
                    )

                # --------------------------------------------------
                # Build Dynamic Update
                # --------------------------------------------------
                fields = []
                values = []
                idx = 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")

                values.append(payment_id)

                update_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_payments
                    SET {', '.join(fields)}
                    WHERE id = ${idx}
                    AND is_active = TRUE
                    RETURNING *
                """

                new_row = await conn.fetchrow(update_sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Payment state changed. Please retry.",
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    old_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

                log.info(
                    "Registration payment updated successfully | payment_id=%s",
                    payment_id,
                )

                return {
                    **dict(new_row),
                    "message": "Registration payment updated successfully.",
                    "request_id": request_id,
                }

        # --------------------------------------------------
        # Error Handling
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(
                status_code=409,
                detail="Duplicate field value violates unique constraint.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_amount_positive": "Amount cannot be negative.",
                "chk_discount_positive": "Discount cannot be negative.",
                "chk_paid_amount_positive": "Paid amount cannot be negative.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference provided.",
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(
                status_code=400,
                detail="Missing required field value.",
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format provided.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during payment update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during payment update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION PAYMENT (Production Ready + Audit)
# -------------------------------------------------------------------
@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete Registration Payment (Production Ready + Audit)",
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
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "soft_delete_registration_payment",
        },
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

                # --------------------------------------------------
                # Soft Delete With Customer Fetch
                # --------------------------------------------------
                delete_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_payments p
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE p.id = $1
                       AND p.is_active = TRUE
                     RETURNING p.*
                """

                deleted_row = await conn.fetchrow(delete_sql, payment_id)

                # --------------------------------------------------
                # Determine failure reason
                # --------------------------------------------------
                if not deleted_row:

                    existing_row = await conn.fetchrow(
                        f"""
                        SELECT id, is_active
                          FROM {DB_SCHEMA}.registration_payments
                         WHERE id = $1
                        """,
                        payment_id,
                    )

                    if not existing_row:
                        raise HTTPException(
                            status_code=404,
                            detail="Registration payment not found.",
                        )

                    if existing_row["is_active"] is False:
                        raise HTTPException(
                            status_code=400,
                            detail="Registration payment already inactive.",
                        )

                    raise HTTPException(
                        status_code=409,
                        detail="Payment state changed. Please retry.",
                    )

                # Optional warning if deleting PAID payment
                if deleted_row.get("payment_status") == "PAID":
                    log.warning(
                        "Soft deleting PAID payment | payment_id=%s",
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
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

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(status_code=400, detail="Constraint validation failed.")

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
    summary="Activate Registration Payment (Production Ready + Audit)",
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
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_registration_payment",
        },
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

                # --------------------------------------------------
                # Fetch Payment With Row Lock
                # --------------------------------------------------
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
                # Activate Payment
                # --------------------------------------------------
                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_payments
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    payment_id,
                )

                if not activated_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Payment state changed. Please retry.",
                    )

                if activated_row.get("payment_status") == "PAID":
                    log.warning(
                        "Activating fully paid payment | payment_id=%s",
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    json.dumps(dict(activated_row), default=str),
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

        except asyncpg.exceptions.CheckViolationError:
            raise HTTPException(status_code=400, detail="Constraint validation failed.")

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